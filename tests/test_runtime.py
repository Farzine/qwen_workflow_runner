"""CPU tests with tiny random networks; no pretrained weights or image-quality claims."""
import importlib.util
import json
import tempfile
import types
import unittest
from pathlib import Path
from PIL import Image

RUNTIME = all(importlib.util.find_spec(name) for name in ('torch', 'diffusers', 'gguf', 'psutil', 'accelerate', 'peft'))


@unittest.skipUnless(RUNTIME, 'Install requirements.txt to run tiny-model tests')
class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import torch
        torch.set_num_threads(2)

    def tiny_transformer(self):
        from diffusers import QwenImage21Transformer2DModel
        return QwenImage21Transformer2DModel(num_layers=1, attention_head_dim=32, num_attention_heads=1,
                                           context_in_dim=32, axes_dims_rope=(8,12,12))

    def test_packed_gguf_load_and_forward(self):
        import gguf, torch
        import numpy as np
        from diffusers.quantizers.gguf.utils import GGUFLinear
        from qwen_runner.gguf_loader import load_gguf_transformer
        model = self.tiny_transformer()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); model.save_config(root)
            filename = root / 'tiny.gguf'
            writer = gguf.GGUFWriter(str(filename), 'qwen_image21')
            for name, value in model.state_dict().items():
                array = value.detach().float().numpy()
                if array.ndim == 2 and array.shape[-1] % 32 == 0:
                    qtype = gguf.GGMLQuantizationType.Q8_0
                    array = gguf.quants.quantize(array, qtype)
                    writer.add_tensor(name, array, raw_dtype=qtype)
                else: writer.add_tensor(name, array)
            writer.write_header_to_file(); writer.write_kv_data_to_file(); writer.write_tensors_to_file(); writer.close()
            loaded, meta = load_gguf_transformer(filename, root, torch.float32)
            self.assertEqual(meta['tensor_count'], len(model.state_dict()))
            self.assertIsInstance(loaded.img_in, GGUFLinear)
            x = torch.randn(2,64)
            self.assertEqual(loaded.img_in(x).shape, (2,32))
            self.assertTrue(torch.allclose(loaded.img_in(x), model.img_in(x), atol=.025, rtol=.025))
            loaded.to('cpu')  # Device transfer must preserve packed parameters.
            self.assertEqual(loaded.img_in.weight.dtype, torch.uint8)

    def test_reviewed_remote_gguf_inventory_matches_full_model(self):
        from accelerate import init_empty_weights
        from diffusers import QwenImage21Transformer2DModel
        with init_empty_weights(): model = QwenImage21Transformer2DModel()
        expected = {k:list(v.shape) for k,v in model.state_dict().items()}
        inventory = json.loads((Path(__file__).parents[1] / 'workflow/reviewed_gguf_tensor_inventory.json').read_text())
        self.assertEqual(expected, {x['name']:x['shape'] for x in inventory})

    def test_real_transformer_and_vae_two_reference_denoising(self):
        import torch
        from diffusers import AutoencoderKLQwenImage21, FlowMatchEulerDiscreteScheduler
        from qwen_runner.pipeline import WorkflowQwenImage21Pipeline
        from qwen_runner.backend import QwenBackend
        from qwen_runner.config import Config
        vae = AutoencoderKLQwenImage21(base_dim=8, decoder_base_dim=8, dim_mult=[1,1,1,1,1],
                                      num_res_blocks=1, is_residual=False,
                                      latents_mean=[0.]*64, latents_std=[1.]*64)
        class Processor:
            tokenizer = types.SimpleNamespace(encode=lambda text: [99])
            def apply_chat_template(self, *a, **kw): return [[1]]
        class TextEncoder(torch.nn.Linear):
            @property
            def device(self): return self.weight.device
            @property
            def dtype(self): return self.weight.dtype
        processor = Processor()
        pipe = WorkflowQwenImage21Pipeline(vae=vae, text_encoder=TextEncoder(1,1), processor=processor,
                transformer=self.tiny_transformer(), scheduler=FlowMatchEulerDiscreteScheduler(shift=1, use_dynamic_shifting=False))
        seen = []
        def encode(self, image, prompt, **kwargs):
            seen.append([x.size for x in image])
            slots = sum((i.width // 32) * (i.height // 32) for i in image)
            batch = kwargs['num_images_per_prompt']
            embeds = torch.zeros(batch, slots + 1, 32)
            mask = torch.tensor([[True]*slots + [False]]).repeat(batch, 1)
            return embeds, None, mask
        pipe.encode_prompt = types.MethodType(encode, pipe)
        pipe.set_progress_bar_config(disable=True)
        config = Config(); config.generation.steps = 2
        config.runtime.device = 'cpu'; config.runtime.dtype='float32'; config.runtime.offload='none'
        backend = QwenBackend(config); backend.torch=torch; backend.pipe=pipe
        images = [Image.new('RGB',(64,64)), Image.new('RGB',(32,64))]
        output = backend.generate(images, (64,64), 42)
        self.assertEqual(output[0].size, (64,64))
        self.assertEqual(seen[0], [(64,64), (32,64)])
        config.generation.cfg = .5; config.generation.strength=.5
        second = backend.generate(images, (64,64), 42)
        self.assertEqual(second[0].size, (64,64))
        self.assertEqual(len(seen), 3)  # one conditional + conditional/unconditional

    def test_failed_generation_resets_offload_state_before_reuse(self):
        import torch
        from qwen_runner.backend import QwenBackend
        from qwen_runner.config import Config

        class Pipe:
            cleanup_calls = 0
            interrupted_transfer = False
            fail = True
            fail_cleanup = False
            _pack_latents = staticmethod(lambda noise, *args: noise)

            def __call__(self, **kwargs):
                if self.fail:
                    self.interrupted_transfer = True
                    raise torch.OutOfMemoryError('component transfer failed')
                if self.interrupted_transfer:
                    raise RuntimeError('cached component still on mixed devices')
                return types.SimpleNamespace(images=['recovered'])

            def maybe_free_model_hooks(self):
                self.cleanup_calls += 1
                if self.fail_cleanup:
                    raise RuntimeError('cleanup failed')
                self.interrupted_transfer = False

        backend = QwenBackend(Config()); backend.torch = torch; backend.pipe = Pipe()
        with self.assertRaisesRegex(torch.OutOfMemoryError, 'component transfer failed'):
            backend.generate([], (64, 64), 42)
        self.assertEqual(backend.pipe.cleanup_calls, 1)
        backend.pipe.fail = False
        self.assertEqual(backend.generate([], (64, 64), 42), ['recovered'])
        self.assertEqual(backend.pipe.cleanup_calls, 1)  # Successful calls handle their own hooks.
        backend.pipe.fail = backend.pipe.fail_cleanup = True
        with self.assertLogs('qwen_runner.backend', level='ERROR') as logs:
            with self.assertRaisesRegex(torch.OutOfMemoryError, 'component transfer failed'):
                backend.generate([], (64, 64), 42)
        self.assertIn('Pipeline cleanup failed', logs.output[0])

    def test_qwen_lora_is_loaded_scaled_activated_and_unloaded(self):
        import hashlib
        import torch
        from peft import LoraConfig
        from peft.utils import get_peft_model_state_dict
        from safetensors.torch import save_file
        from diffusers import AutoencoderKLQwenImage21, FlowMatchEulerDiscreteScheduler
        from qwen_runner.backend import QwenBackend
        from qwen_runner.config import Config
        from qwen_runner.pipeline import WorkflowQwenImage21Pipeline

        class Processor:
            tokenizer = types.SimpleNamespace(encode=lambda text: [99])
            def apply_chat_template(self, *args, **kwargs):
                return [[1]]

        class TextEncoder(torch.nn.Linear):
            @property
            def device(self): return self.weight.device
            @property
            def dtype(self): return self.weight.dtype

        def make_pipe(transformer):
            vae = AutoencoderKLQwenImage21(
                base_dim=8, decoder_base_dim=8, dim_mult=[1, 1, 1, 1, 1],
                num_res_blocks=1, is_residual=False,
                latents_mean=[0.] * 64, latents_std=[1.] * 64,
            )
            return WorkflowQwenImage21Pipeline(
                vae=vae,
                text_encoder=TextEncoder(1, 1),
                processor=Processor(),
                transformer=transformer,
                scheduler=FlowMatchEulerDiscreteScheduler(shift=1, use_dynamic_shifting=False),
            )

        source = self.tiny_transformer()
        source.add_adapter(
            LoraConfig(r=2, lora_alpha=2, target_modules=['to_q']),
            adapter_name='source',
        )
        for name, parameter in source.named_parameters():
            if 'lora_B' in name:
                torch.nn.init.constant_(parameter, 0.25)
        state = get_peft_model_state_dict(source, adapter_name='source')

        with tempfile.TemporaryDirectory() as directory:
            WorkflowQwenImage21Pipeline.save_lora_weights(
                directory,
                transformer_lora_layers=state,
                weight_name='tiny.safetensors',
            )
            path = Path(directory) / 'tiny.safetensors'
            config = Config()
            config.model.lora_path = str(path)
            config.model.lora_scale = 0.7
            backend = QwenBackend(config)
            backend.pipe = make_pipe(self.tiny_transformer())
            backend._apply_configured_lora()

            self.assertEqual(backend.pipe.get_active_adapters(), ['qwen_workflow_lora'])
            self.assertEqual(backend.metadata['lora']['scale'], 0.7)
            self.assertTrue(backend.metadata['lora']['applied'])
            self.assertEqual(backend.metadata['lora']['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())

            layer = backend.pipe.transformer.transformer_blocks[0].attn.to_q
            sample = torch.randn(2, 32)
            enabled = layer(sample)
            backend.pipe.disable_lora()
            disabled = layer(sample)
            self.assertFalse(torch.allclose(enabled, disabled))
            backend.pipe.enable_lora()

            config.model.lora_path = None
            backend._apply_configured_lora()
            self.assertEqual(backend.pipe.get_list_adapters(), {})
            self.assertFalse(backend.metadata['lora']['applied'])

            incompatible = Path(directory) / 'incompatible.safetensors'
            save_file({
                'transformer.missing_projection.lora_A.weight': torch.ones(2, 4),
                'transformer.missing_projection.lora_B.weight': torch.ones(4, 2),
            }, incompatible)
            config.model.lora_path = str(incompatible)
            with self.assertRaisesRegex(RuntimeError, "LoRA loading failed for 'incompatible.safetensors'"):
                backend._apply_configured_lora()
            self.assertEqual(backend.pipe.get_list_adapters(), {})

    def test_fused_qwen_lora_preserves_gate_up_math_and_rejects_invalid_pairs(self):
        import torch
        from torch.nn import functional as F
        from qwen_runner.pipeline import WorkflowQwenImage21Pipeline

        transformer = self.tiny_transformer()
        mlp = transformer.transformer_blocks[0].img_mlp
        gate, proj = mlp.gate_layer.weight.detach().clone(), mlp.proj.weight.detach().clone()
        a = torch.randn(2, gate.shape[1]) * 0.05
        b = torch.randn(2 * gate.shape[0], 2) * 0.05
        stem = 'diffusion_model.transformer_blocks.0.img_mlp.gate_up'
        state = {stem + '.lora_A.weight': a, stem + '.lora_B.weight': b}
        converted, metadata = WorkflowQwenImage21Pipeline.lora_state_dict(state, return_lora_metadata=True)
        self.assertIsNone(metadata)
        self.assertEqual(len(converted), 4)
        transformer.load_lora_adapter(converted, adapter_name='fused')
        sample = torch.randn(2, gate.shape[1])
        delta_gate, delta_proj = F.linear(F.linear(sample, a), b).chunk(2, dim=-1)
        expected = mlp.out(F.silu(F.linear(sample, gate) + delta_gate) * (F.linear(sample, proj) + delta_proj))
        self.assertTrue(torch.allclose(mlp(sample), expected, atol=1e-6, rtol=1e-5))

        scaled = WorkflowQwenImage21Pipeline.lora_state_dict({
            stem + '.lora_down.weight': a, stem + '.lora_up.weight': b,
            stem + '.alpha': torch.tensor(4.),
        })
        for name, up in zip(('gate_layer', 'proj'), b.chunk(2, dim=0)):
            target = stem.replace('diffusion_model.', 'transformer.').replace('gate_up', name)
            self.assertTrue(torch.allclose(scaled[target + '.lora_B.weight'] @ scaled[target + '.lora_A.weight'],
                                           2 * (up @ a)))

        invalid = [
            {stem + '.lora_A.weight': a},
            {stem + '.lora_B.weight': b},
            {stem + '.lora_A.weight': a, stem + '.lora_B.weight': b[:-1]},
            {stem + '.lora_A.weight': a, stem + '.lora_B.weight': b[:, :1]},
            {**state, stem.replace('gate_up', 'proj') + '.lora_A.weight': a},
        ]
        for index, candidate in enumerate(invalid):
            with self.subTest(case=index), self.assertRaisesRegex(ValueError, 'fused'):
                WorkflowQwenImage21Pipeline.lora_state_dict(candidate)

    def test_metrics_and_failure_logs(self):
        import torch
        from qwen_runner.config import Config
        from qwen_runner.runner import run
        class Backend:
            def __init__(self, config):
                self.torch=torch; self.metadata={'model': {'repo_id': 'synthetic/test'}}
            def load(self): return self
            def generate(self, images, canvas, seed): return [Image.new('RGB', canvas)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source=root/'in.png'; Image.new('RGB',(64,64)).save(source)
            c=Config(); c.generation.images=[str(source)]; c.runtime.output_dir=str(root/'out')
            c.runtime.device='cpu'; c.runtime.dtype='float32'; c.runtime.offload='none'
            c.runtime.warmup_runs=1; c.runtime.repeats=2
            events=[]
            records=run(c, Backend, on_operation=lambda stage, record, index, total:
                        events.append((stage, index, total, record['run_id'])))
            self.assertEqual(len(records),3)
            self.assertEqual([(stage, index, total) for stage, index, total, _ in events if stage == 'completed'],
                             [('completed', 0, 3), ('completed', 1, 3), ('completed', 2, 3)])
            self.assertEqual([stage for stage, _, _, _ in events[:4]],
                             ['preparing', 'generating', 'saving', 'completed'])
            self.assertTrue(records[0]['is_warmup'])
            self.assertTrue(all(r['inference_time_seconds'] >= 0 for r in records))
            self.assertIsNone(records[1]['peak_memory_usage']['gpu_peak_allocated_bytes'])
            self.assertGreater(records[1]['peak_memory_usage']['process_rss_peak_bytes'], 0)
            def broken_progress(*_):
                raise RuntimeError('progress display failed')
            self.assertEqual(len(run(c, Backend, on_operation=broken_progress)), 3)
            class Broken(Backend):
                def generate(self, *a): raise RuntimeError('synthetic failure')
            with self.assertRaisesRegex(RuntimeError, 'synthetic failure'): run(c, Broken)
            logs=[json.loads(p.read_text()) for p in (root/'out').glob('*.json')]
            failures=[r for r in logs if r['status']=='error']
            self.assertEqual(len(failures),1)
            self.assertIsNotNone(failures[0]['inference_time_seconds'])

    def test_explicit_inputs_share_model_references_and_repeat_seed(self):
        import torch
        from qwen_runner.config import Config
        from qwen_runner.runner import run

        class Backend:
            loads = 0
            calls = []

            def __init__(self, config):
                self.config = config
                self.torch = torch
                self.metadata = {'model': {'repo_id': 'synthetic/batch'}}

            def load(self):
                type(self).loads += 1
                return self

            def generate(self, images, canvas, seed):
                type(self).calls.append({
                    'pixels': [image.getpixel((0, 0)) for image in images],
                    'paths': list(self.config.generation.images),
                    'seed': seed,
                })
                return [images[0].copy()]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = []
            for name, color in (
                ('input-b.png', (20, 0, 0)),
                ('input-a.png', (10, 0, 0)),
                ('ref-2.png', (0, 20, 0)),
                ('ref-1.png', (0, 10, 0)),
            ):
                path = root / name
                Image.new('RGB', (64, 64), color).save(path)
                paths.append(path)

            c = Config()
            c.generation.input_images = [str(paths[0]), str(paths[1])]
            c.generation.reference_images = [str(paths[2]), str(paths[3])]
            c.generation.seed = 7
            c.runtime.output_dir = str(root / 'out')
            c.runtime.device = 'cpu'; c.runtime.dtype = 'float32'; c.runtime.offload = 'none'
            c.runtime.repeats = 2; c.runtime.increment_seed = True
            records = run(c, Backend)

            self.assertEqual(Backend.loads, 1)
            self.assertEqual(len(records), 4)
            self.assertEqual(records[1]['summary']['input']['filename'], 'input-a.png')
            self.assertEqual([item['filename'] for item in records[1]['summary']['references']],
                             ['ref-2.png', 'ref-1.png'])
            self.assertEqual(records[1]['summary']['model']['name'], 'synthetic/batch')
            self.assertEqual(json.loads((root / 'out' / f"{records[1]['run_id']}.json").read_text())['summary']['summary_version'], 1)
            self.assertEqual([r['input_index'] for r in records], [0, 1, 0, 1])
            self.assertEqual([r['parameters']['generation']['seed'] for r in records], [7, 7, 8, 8])
            self.assertTrue(all(r['parameters']['generation']['images'] == [] for r in records))
            self.assertEqual([call['seed'] for call in Backend.calls], [7, 7, 8, 8])
            self.assertEqual(
                [call['pixels'] for call in Backend.calls[:2]],
                [[(20, 0, 0), (0, 20, 0), (0, 10, 0)],
                 [(10, 0, 0), (0, 20, 0), (0, 10, 0)]],
            )
            self.assertEqual(Backend.calls[0]['paths'], [str(paths[0]), str(paths[2]), str(paths[3])])
            self.assertEqual(Backend.calls[1]['paths'], [str(paths[1]), str(paths[2]), str(paths[3])])
            self.assertEqual(
                [Path(item['path']).name for item in records[0]['effective_parameters']['additional_reference_images']],
                ['ref-2.png', 'ref-1.png'],
            )
            self.assertTrue(all(len(record['outputs']) == 1 for record in records))

    def test_explicit_multi_input_isolates_decode_failure(self):
        import torch
        from qwen_runner.config import Config
        from qwen_runner.runner import run

        class Backend:
            loads = 0
            calls = 0

            def __init__(self, config):
                self.config = config
                self.torch = torch
                self.metadata = {'model': {'repo_id': 'synthetic/partial'}}

            def load(self):
                type(self).loads += 1
                return self

            def generate(self, images, canvas, seed):
                type(self).calls += 1
                return [images[0].copy()]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            corrupt = root / 'corrupt.png'; corrupt.write_bytes(b'not an image')
            valid = root / 'valid.png'; Image.new('RGB', (64, 64), (1, 2, 3)).save(valid)
            reference = root / 'reference.png'; Image.new('RGB', (64, 64), (4, 5, 6)).save(reference)
            c = Config()
            c.generation.input_images = [str(corrupt), str(valid)]
            c.generation.reference_images = [str(reference)]
            c.runtime.output_dir = str(root / 'out')
            c.runtime.device = 'cpu'; c.runtime.dtype = 'float32'; c.runtime.offload = 'none'

            records = run(c, Backend)
            self.assertEqual(Backend.loads, 1)
            self.assertEqual(Backend.calls, 1)
            self.assertEqual([record['status'] for record in records], ['error', 'success'])
            self.assertEqual(records[0]['input_index'], 0)
            self.assertIn('error', records[0])
            self.assertEqual(records[1]['input_index'], 1)
            self.assertEqual(len(records[1]['outputs']), 1)


if __name__ == '__main__': unittest.main()

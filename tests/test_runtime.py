"""CPU tests with tiny random networks; no pretrained weights or image-quality claims."""
import importlib.util
import json
import tempfile
import types
import unittest
from pathlib import Path
from PIL import Image

RUNTIME = all(importlib.util.find_spec(name) for name in ('torch', 'diffusers', 'gguf', 'psutil', 'accelerate'))


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
            records=run(c, Backend)
            self.assertEqual(len(records),3)
            self.assertTrue(records[0]['is_warmup'])
            self.assertTrue(all(r['inference_time_seconds'] >= 0 for r in records))
            self.assertIsNone(records[1]['peak_memory_usage']['gpu_peak_allocated_bytes'])
            self.assertGreater(records[1]['peak_memory_usage']['process_rss_peak_bytes'], 0)
            class Broken(Backend):
                def generate(self, *a): raise RuntimeError('synthetic failure')
            with self.assertRaisesRegex(RuntimeError, 'synthetic failure'): run(c, Broken)
            logs=[json.loads(p.read_text()) for p in (root/'out').glob('*.json')]
            failures=[r for r in logs if r['status']=='error']
            self.assertEqual(len(failures),1)
            self.assertIsNotNone(failures[0]['inference_time_seconds'])


if __name__ == '__main__': unittest.main()

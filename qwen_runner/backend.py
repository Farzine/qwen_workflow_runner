import hashlib
import json
from pathlib import Path
from .models import ModelStore, parse_model_ref
from .sampling import sigma_schedule
from .system import probe_runtime_capabilities


class QwenBackend:
    def __init__(self, config):
        self.config = config
        self.metadata = {}
        self._loaded_lora_adapter = None
        self._loaded_lora_path = None
        self._loaded_lora_scale = None

    @staticmethod
    def _file_sha256(path):
        digest = hashlib.sha256()
        with open(path, 'rb') as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    def _apply_configured_lora(self):
        """Load one unfused adapter and verify that Diffusers activated it."""
        c = self.config.model
        requested_path = str(Path(c.lora_path).expanduser().resolve()) if c.lora_path else None
        requested_scale = float(c.lora_scale)
        if self._loaded_lora_adapter and self._loaded_lora_path == requested_path:
            if self._loaded_lora_scale != requested_scale:
                self.pipe.set_adapters(self._loaded_lora_adapter, adapter_weights=requested_scale)
                self._loaded_lora_scale = requested_scale
            self.metadata['lora']['scale'] = requested_scale
            return

        if self._loaded_lora_adapter:
            self.pipe.unload_lora_weights()
            self._loaded_lora_adapter = None
            self._loaded_lora_path = None
            self._loaded_lora_scale = None

        if not c.lora_path:
            self.metadata['lora'] = {
                'enabled': False,
                'applied': False,
                'path': None,
                'scale': requested_scale,
            }
            return

        path = Path(requested_path)
        if not path.is_file():
            raise FileNotFoundError(f'LoRA file not found: {path}')
        if path.suffix.lower() != '.safetensors':
            raise ValueError(f'LoRA must be a .safetensors file: {path}')

        adapter_name = 'qwen_workflow_lora'
        try:
            self.pipe.load_lora_weights(
                str(path.parent),
                weight_name=path.name,
                adapter_name=adapter_name,
                local_files_only=True,
                use_safetensors=True,
            )
            self.pipe.set_adapters(adapter_name, adapter_weights=requested_scale)
            active = list(self.pipe.get_active_adapters())
            available = self.pipe.get_list_adapters()
            if adapter_name not in active:
                raise RuntimeError(f'Diffusers loaded the adapter but did not activate {adapter_name!r}')
        except Exception as error:
            try:
                self.pipe.unload_lora_weights()
            except Exception:
                pass
            raise RuntimeError(f"LoRA loading failed for '{path.name}': {error}") from error

        self._loaded_lora_adapter = adapter_name
        self._loaded_lora_path = str(path)
        self._loaded_lora_scale = requested_scale
        self.metadata['lora'] = {
            'enabled': True,
            'applied': True,
            'path': str(path),
            'filename': path.name,
            'sha256': self._file_sha256(path),
            'adapter_name': adapter_name,
            'scale': requested_scale,
            'active_adapters': active,
            'available_adapters': available,
            'fused': False,
        }

    def load(self):
        if getattr(self, 'pipe', None) is not None:
            return self
        import torch
        from diffusers import FlowMatchEulerDiscreteScheduler, QwenImage21Transformer2DModel
        from .pipeline import WorkflowQwenImage21Pipeline
        c, r = self.config.model, self.config.runtime
        self.torch = torch
        capability = probe_runtime_capabilities(
            device=r.device,
            dtype=r.dtype,
            offload=r.offload,
            torch_module=torch,
        )
        if not capability['production_backend']['ready']:
            raise RuntimeError(capability['production_backend']['message'])
        device = torch.device(r.device)
        if device.type == 'cuda':
            torch.cuda.set_device(device)
        dtype = getattr(torch, r.dtype)
        store = ModelStore(c.cache_dir, c.offline)
        source, meta = store.fetch(parse_model_ref(c.source, c.revision, c.filename), quantization=c.gguf_quantization)
        self.metadata['model'] = meta
        overrides = {}
        base = source
        if source.is_file():
            base, base_meta = store.fetch(parse_model_ref(c.base_model, c.base_revision), purpose='companions')
            self.metadata['companion_model'] = base_meta
            if source.suffix.lower() == '.gguf':
                from .gguf_loader import load_gguf_transformer
                transformer, details = load_gguf_transformer(source, base / 'transformer', dtype)
                overrides['transformer'] = transformer
                self.metadata['gguf'] = details
            elif source.suffix.lower() == '.safetensors':
                if 'convrot' in source.name.lower():
                    raise ValueError('Comfy int8_convrot is not a standard BF16 checkpoint. Use official Diffusers weights or the supported GGUF repository; no automatic model substitution is performed.')
                from safetensors.torch import load_file
                from accelerate import init_empty_weights
                state = load_file(str(source))
                if any(not value.is_floating_point() for value in state.values()):
                    raise ValueError('Only floating-point single-file transformers are supported here; use GGUF for quantized storage')
                with init_empty_weights():
                    transformer = QwenImage21Transformer2DModel.from_config(
                        QwenImage21Transformer2DModel.load_config(str(base / 'transformer'), local_files_only=True))
                for name in state: state[name] = state[name].to(dtype=dtype)
                transformer.load_state_dict(state, strict=True, assign=True)
                overrides['transformer'] = transformer
                del state
            else:
                raise ValueError(f'Unsupported checkpoint extension: {source.suffix}')
        index = json.loads((base / 'model_index.json').read_text())
        if index.get('_class_name') != 'QwenImage21Pipeline':
            raise ValueError(f"Expected QwenImage21Pipeline, got {index.get('_class_name')}. Older Qwen Image/Edit/2511 models require a different graph and are intentionally rejected.")
        encoder_root = base
        if c.text_encoder_source:
            from transformers import Qwen3VLForConditionalGeneration, Qwen3VLProcessor
            encoder_root, encoder_meta = store.fetch(parse_model_ref(c.text_encoder_source), purpose='text_encoder')
            overrides['text_encoder'] = Qwen3VLForConditionalGeneration.from_pretrained(
                str(encoder_root / 'text_encoder'), torch_dtype=dtype, local_files_only=True)
            overrides['processor'] = Qwen3VLProcessor.from_pretrained(str(encoder_root / 'processor'), local_files_only=True)
            self.metadata['text_encoder_override'] = encoder_meta
        self.pipe = WorkflowQwenImage21Pipeline.from_pretrained(str(base), torch_dtype=dtype, local_files_only=True, **overrides)
        self._apply_configured_lora()
        # Sigmas already include Comfy's flow shift; do not shift/stretch them again.
        self.pipe.scheduler = FlowMatchEulerDiscreteScheduler(num_train_timesteps=1000, shift=1.0, use_dynamic_shifting=False)
        if r.vae_tiling: self.pipe.vae.enable_tiling()
        if r.offload == 'model': self.pipe.enable_model_cpu_offload(device=str(device))
        elif r.offload == 'sequential': self.pipe.enable_sequential_cpu_offload(device=str(device))
        else: self.pipe.to(device)
        self.metadata.update(
            pipeline=type(self.pipe).__name__,
            text_encoder={"class": type(self.pipe.text_encoder).__name__, "path": str(encoder_root / 'text_encoder')},
            vae={"class": type(self.pipe.vae).__name__, "path": str(base / 'vae')},
            transformer=type(self.pipe.transformer).__name__,
            precision=r.dtype,
            device=str(device),
            offload=r.offload,
            scheduler_config=dict(self.pipe.scheduler.config),
            parity='Workflow logic reproduced in Diffusers; not bitwise parity with Comfy int8_convrot weights or its kernels',
            kv_cache_policy='Lossless prefix cache; auto keeps CUDA reserve then spills to CPU; synchronous CPU transfers, no Comfy prefetch',
        )
        return self

    def prepare_for_config(self, config):
        """Apply request-scoped state without rebuilding compatible weights."""
        self.config = config
        self._apply_configured_lora()
        return self

    def unload(self):
        """Drop pipeline/component references before device cache cleanup."""
        pipe = getattr(self, 'pipe', None)
        if pipe is None:
            return
        try:
            if self._loaded_lora_adapter:
                pipe.unload_lora_weights()
        except Exception:
            pass
        try:
            pipe.maybe_free_model_hooks()
        except Exception:
            pass
        try:
            pipe.remove_all_hooks()
        except Exception:
            pass
        try:
            pipe.to('cpu')
        except Exception:
            pass
        self._loaded_lora_adapter = None
        self._loaded_lora_path = None
        self._loaded_lora_scale = None
        self.pipe = None
        self.metadata['lifecycle_state'] = 'unloaded'

    def generate(self, images, canvas, seed):
        g = self.config.generation
        torch, pipe = self.torch, self.pipe
        sigmas = sigma_schedule(g.steps, g.strength, g.shift, g.scheduler)
        width, height = canvas
        generator = torch.Generator('cpu').manual_seed(seed)
        # Comfy generates CPU float32 noise independently of model precision.
        noise = torch.randn((g.batch_size, 64, height // 16, width // 16), generator=generator, dtype=torch.float32)
        noise *= sigmas[0]  # Empty starting latent; reduced denoise does not blend image1.
        packed = pipe._pack_latents(noise, g.batch_size, 64, height // 16, width // 16)
        with torch.inference_mode():
            return pipe(prompt=g.prompt, negative_prompt=g.negative_prompt,
                        image=images, width=width, height=height,
                        num_inference_steps=g.steps, true_cfg_scale=g.cfg, sigmas=sigmas,
                        num_images_per_prompt=g.batch_size, generator=generator,
                        latents=packed, use_kv_cache=g.kv_cache,
                        kv_cache_device=g.kv_cache_device,
                        kv_cache_reserve_gib=g.kv_cache_reserve_gib).images

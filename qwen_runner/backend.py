import json
from pathlib import Path
from .models import ModelStore, parse_model_ref
from .sampling import sigma_schedule


class QwenBackend:
    def __init__(self, config):
        self.config = config
        self.metadata = {}

    def load(self):
        import torch
        from diffusers import FlowMatchEulerDiscreteScheduler, QwenImage21Transformer2DModel
        from .pipeline import WorkflowQwenImage21Pipeline
        c, r = self.config.model, self.config.runtime
        self.torch = torch
        device = torch.device(r.device)
        if device.type == 'cuda':
            if not torch.cuda.is_available(): raise RuntimeError('CUDA unavailable. Install a CUDA PyTorch wheel, or set CPU + float32 + no offload.')
            torch.cuda.set_device(device)
            if r.dtype == 'bfloat16' and not torch.cuda.is_bf16_supported():
                raise ValueError('This CUDA device does not support BF16. Set runtime.dtype to float32 or float16 explicitly.')
        elif device.type == 'mps' and not torch.backends.mps.is_available():
            raise RuntimeError('MPS unavailable on this machine')
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
            scheduler_config=dict(self.pipe.scheduler.config),
            parity='Workflow logic reproduced in Diffusers; not bitwise parity with Comfy int8_convrot weights or its kernels',
            kv_cache_policy='Lossless prefix cache; auto keeps CUDA reserve then spills to CPU; synchronous CPU transfers, no Comfy prefetch',
        )
        return self

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

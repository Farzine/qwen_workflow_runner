"""Edit CONFIG below, then run: python run.py

Use --dry-run for configuration validation without model downloads.
"""
import argparse
import json
from qwen_runner.config import Config, ModelConfig, GenerationConfig, RuntimeConfig


CONFIG = Config(
    model=ModelConfig(
        source="https://huggingface.co/Qwen/Qwen-Image-2.1",
        # Change only source to use abenzerps/Qwen-Image-2.1-GGUF (Q4_K_M default).
        # filename="qwen-image-2.1-Q8_0.gguf",  # Optional exact variant.
        cache_dir="models",
        offline=False,
    ),
    generation=GenerationConfig(
        images=["inputs/portrait_model_denim.png", "inputs/clothing_light_blue_denim_shirt.png"],
        steps=25,
        cfg=1.0,
        seed=1070478148268574,
        strength=1.0,
        resolution=0,       # Preserve each reference's size, rounded to 32.
        custom_size=False,  # True activates width and height below.
        width=1024,
        height=1024,
        sampler="euler",
        scheduler="simple",
        kv_cache=True,
        # prompt="Your edit instruction using <image1> and <image2>",
        # negative_prompt="",
    ),
    runtime=RuntimeConfig(
        device="cuda:0",
        dtype="bfloat16",
        offload="model",    # none | model | sequential
        vae_tiling=False,
        warmup_runs=0,
        repeats=1,
        output_dir="outputs",
    ),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', help='Override CONFIG.model.source')
    image_group = parser.add_mutually_exclusive_group()
    image_group.add_argument('--images', nargs='+', help='Legacy ordered conditioning paths; first image is the process input')
    image_group.add_argument('--input-images', nargs='+', help='Ordered process inputs; creates one inference record per input')
    parser.add_argument('--reference-images', nargs='*', help='Shared ordered references used with every --input-images item')
    parser.add_argument('--filename', help='Exact GGUF or floating-point transformer filename')
    parser.add_argument('--lora', help='Local Qwen Image LoRA .safetensors file')
    parser.add_argument('--lora-scale', type=float, help='LoRA strength from 0 to 2')
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--dry-run', action='store_true', help='Validate settings without importing torch or downloading models')
    parser.add_argument('--check', action='store_true', help='Check installed runtime capabilities without downloading models')
    args = parser.parse_args()
    if args.model: CONFIG.model.source = args.model
    if args.images: CONFIG.generation.images = args.images
    if args.input_images is not None: CONFIG.generation.input_images = args.input_images
    if args.reference_images is not None:
        if args.input_images is None:
            parser.error('--reference-images requires --input-images')
        CONFIG.generation.reference_images = args.reference_images
    if args.filename: CONFIG.model.filename = args.filename
    if args.lora: CONFIG.model.lora_path = args.lora
    if args.lora_scale is not None: CONFIG.model.lora_scale = args.lora_scale
    if args.offline: CONFIG.model.offline = True
    if args.dry_run:
        CONFIG.validate(check_images=False)
        print(json.dumps(CONFIG.as_dict(), indent=2))
        print('Configuration valid. Input files, model compatibility and hardware were not checked.')
    elif args.check:
        import torch, diffusers, transformers
        from peft import LoraConfig
        required = ['QwenImage21Pipeline', 'QwenImage21Transformer2DModel', 'AutoencoderKLQwenImage21']
        missing = [name for name in required if not hasattr(diffusers, name)]
        if not hasattr(transformers, 'Qwen3VLForConditionalGeneration'): missing.append('Qwen3VLForConditionalGeneration')
        if missing: raise RuntimeError(f'Missing runtime classes: {missing}. Install requirements.txt.')
        from qwen_runner.pipeline import WorkflowQwenImage21Pipeline
        from qwen_runner.runner import environment
        print(json.dumps(environment(torch, CONFIG.runtime.device), indent=2))
        print(f'Runtime classes available, including PEFT {LoraConfig.__name__}. No model inference was performed.')
    else:
        from qwen_runner.runner import run
        run(CONFIG)


if __name__ == '__main__':
    main()

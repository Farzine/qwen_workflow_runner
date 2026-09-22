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
    parser.add_argument('--images', nargs='+', help='Ordered reference image paths')
    parser.add_argument('--filename', help='Exact GGUF or floating-point transformer filename')
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--dry-run', action='store_true', help='Validate settings without importing torch or downloading models')
    parser.add_argument('--check', action='store_true', help='Check installed runtime capabilities without downloading models')
    args = parser.parse_args()
    if args.model: CONFIG.model.source = args.model
    if args.images: CONFIG.generation.images = args.images
    if args.filename: CONFIG.model.filename = args.filename
    if args.offline: CONFIG.model.offline = True
    if args.dry_run:
        CONFIG.validate(check_images=False)
        print(json.dumps(CONFIG.as_dict(), indent=2))
        print('Configuration valid. Input files, model compatibility and hardware were not checked.')
    elif args.check:
        import torch, diffusers, transformers
        required = ['QwenImage21Pipeline', 'QwenImage21Transformer2DModel', 'AutoencoderKLQwenImage21']
        missing = [name for name in required if not hasattr(diffusers, name)]
        if not hasattr(transformers, 'Qwen3VLForConditionalGeneration'): missing.append('Qwen3VLForConditionalGeneration')
        if missing: raise RuntimeError(f'Missing runtime classes: {missing}. Install requirements.txt.')
        from qwen_runner.pipeline import WorkflowQwenImage21Pipeline
        from qwen_runner.runner import environment
        print(json.dumps(environment(torch, CONFIG.runtime.device), indent=2))
        print('Runtime classes available. No model inference was performed.')
    else:
        from qwen_runner.runner import run
        run(CONFIG)


if __name__ == '__main__':
    main()

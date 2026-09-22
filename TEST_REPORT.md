# Validation report

Date: 2026-09-22

## Results

**21 tests passed:** 17 core tests and 4 CPU runtime tests.

Also checked: every Python file parses, and `python run.py --dry-run` validates
and prints the provided workflow defaults without downloading models.

| Area | Verified |
|---|---|
| Workflow extraction | Default prompt, seed, CFG, steps, resolution and custom-size switch match the outer subgraph instance |
| Image preparation | First-reference canvas, independent reference sizes, 32-pixel rounding, RGB conversion and input hashes |
| Model references | All three URL forms supplied in the request; local paths; exact file/revision URLs; malformed paths rejected |
| Cache | Completed-cache reuse makes zero mocked Hub calls; missing shard fails offline; GGUF selects one variant; companion selection excludes transformer weights |
| Sampling | Simple sigma grid and reduced-denoise schedule selection |
| GGUF loading | Temporary Q8 GGUF built from a tiny real Qwen 2.1 transformer; packed linear loading, forward execution, numeric comparison and device transfer |
| Supplied GGUF layout | All 297 names and shapes from its reviewed header match the full Qwen 2.1 architecture instantiated on the meta device |
| Denoising pipeline | Two differently sized reference images; actual tiny random Qwen 2.1 transformer and VAE; two Euler steps; CFG 1 and CFG 0.5; strength 1 and 0.5; output dimensions correct |
| Logging and metrics | Warmup plus measured-run JSON records, process RSS and inference timing, null CPU-only GPU metrics, saved outputs, and a logged synthetic failure |
| Vision preprocessing | Real Qwen vision processor, resize disabled: 64×64 and 32×64 inputs produce the expected 4×4 and 4×2 patch grids |

The denoising test uses **stub prompt embeddings**, not a pretrained language
encoder. The transformer and VAE are small random networks, not downloaded
production weights. These tests establish execution behavior, not useful image
quality or a production benchmark.

## Runtime details

- Python 3.12.14
- PyTorch 2.14.0+cpu; torchvision 0.29.0+cpu
- Transformers 5.17.0; Accelerate 1.15.0; GGUF 0.19.0
- The pinned Diffusers 0.41.0.dev0 runtime's Qwen 2.1 classes were successfully
  imported during the initial check.
- For the final CPU suite, after a slow repeat Git checkout, the reviewed
  transformer/VAE source files from the same pinned commit were loaded with a
  Diffusers 0.40.0 support installation. Their source hashes are recorded in
  `workflow/source_manifest.json`. This is a narrower check than running the
  entire final pinned dependency installation end to end.

## Not verified in this environment

- Full-size pretrained image generation or text-encoder output quality.
- CUDA execution, GPU peak counters, GPU offload or CPU-cache transfers on a
  real CUDA device. Those code paths use PyTorch/Diffusers APIs but require a
  target-hardware test.
- Apple MPS inference.
- Full-size forward execution of the example GGUF checkpoint; its header was
  inspected, and a synthetic GGUF exercised the loader.
- Numerical or perceptual equivalence to ComfyUI, including its int8_convrot
  weights, cache prefetch and attention kernels.

No production inference times, GPU peaks or generated sample results are
claimed or fabricated. The project records those when you run it with the
actual models and images.

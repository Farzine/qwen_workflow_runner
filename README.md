# Qwen Image 2.1 — standalone workflow runner

A Python project built from your supplied ComfyUI image-editing JSON. It runs
locally through PyTorch and Diffusers. **No ComfyUI installation, web server,
API endpoint, or node execution is required.**

Edit `CONFIG` in `run.py`, then run `python run.py`. Outputs and a separate JSON
record for every inference go into `outputs/`.

## What is reproduced

The original graph is included at `workflow/original.json`.

| Workflow setting | Project behavior |
|---|---|
| Two ordered `LoadImage` nodes | Legacy `generation.images`; image 1 is the person/canvas, image 2 the shirt |
| Positive prompt | Original clothing-transfer prompt is the default |
| Negative prompt | Empty by default; inactive when CFG is 1 |
| `TextEncodeQwenImage21`, resolution **0** | Preserve each reference's own dimensions, rounded to multiples of 32; Lanczos resizing when needed |
| `custom_size = false` | Output size follows the **first** reference after rounding |
| `custom_size = true` | Use explicitly configured width and height; reference sizes stay independent |
| Qwen3-VL encoder + reference VAE latents | Dedicated Qwen Image **2.1** pipeline, with all references in one edit |
| Empty latent | Start with noise on an empty canvas; references condition generation |
| KSampler | Euler, simple schedule, 25 steps, CFG 1, denoise/strength 1 |
| Flow model sampling | Fixed shift 0.69 and Comfy's 10,000-point simple sigma selection |
| Seed | 1070478148268574; fixed across repeats unless you enable incrementing |
| Prefix cache | Lossless KV caching; auto, GPU or CPU storage |
| VAE decode and save | One 8-bit PNG for each batch output |
| ImageCompare | Optional saved side-by-side PNG |

**Workflow fidelity is not a claim of pixel-identical output.** Your original
graph loads `qwen_image_2.1_int8_convrot.safetensors`. The default here loads the
official **BF16 Diffusers checkpoint** from the link you supplied; the GGUF
option uses the selected quantized checkpoint. Comfy's `int8_convrot` format is
not loaded or silently converted. Weights, quantization, attention kernels,
floating-point calculations and cache-transfer implementations can change
outputs and timing. See `workflow/PORTING_NOTES.md` for the precise differences.

## 1. Install

Use Python 3.10 or newer, Git, and a PyTorch-supported environment. NVIDIA CUDA
is the intended inference target. CPU is supported for functional testing but
full-size generation will be slow. MPS is configurable but full-model operator
coverage has not been validated here.

```bash
cd qwen_workflow_runner
python -m venv .venv
```

Activate the environment:

```bash
# Linux / macOS
source .venv/bin/activate
```

```powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1
```

Install a matching **PyTorch + torchvision** build for your CUDA driver using
the command generated at <https://pytorch.org/get-started/locally/>. The
checked-in CUDA 12.6 profile is verified with NVIDIA driver 560.28.03 and RTX
A6000 GPUs:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements-cu126.txt
python run.py --check
```

For another CUDA runtime or CPU-only installation, install the appropriate
PyTorch and torchvision wheels first, then install `requirements.txt`. The
generic requirements deliberately do not choose a CUDA build for you.

Diffusers is pinned to a reviewed Git commit containing the dedicated
`QwenImage21Pipeline`, transformer and VAE. An older Qwen Image/Edit pipeline
is not an interchangeable substitute. Every run records installed versions and
the installed Diffusers Git revision.

No model weights are bundled. The transformer, text encoder and VAE together
require substantial disk space and RAM. A GGUF transformer does **not** make
the separate Qwen3-VL text encoder small. Start with CPU offload, a reasonable
reference resolution, and a smaller GGUF if VRAM is limited; actual fit depends
on image sizes, number of references, cache policy and hardware.

## 2. Provide input images

Your JSON contains image filenames, not the image files themselves. Either
copy your own files into `inputs/` and change the generation image fields, or download
the two public template assets referenced in the original JSON:

```bash
python scripts/download_examples.py
```

For new integrations, use separate `input_images` and `reference_images` fields:

```python
config.generation.input_images = ["inputs/person-a.png", "inputs/person-b.png"]
config.generation.reference_images = ["inputs/shirt.png"]
```

Each input creates an independent inference record and output using the ordered
conditioning sequence `[current_input, *reference_images]`. The model loads once
for the expanded batch. A repeat uses the same seed for every input; enabling
`increment_seed` advances the seed between repeats. Up to ten process inputs and
nine shared references are accepted, keeping each model call within its ten-image
conditioning limit.

The legacy `generation.images` field remains supported. Its first image is the
editing canvas/input and later images are references. Reference order corresponds
to `<image1>`, `<image2>`, and so on.

## 3. Run

```bash
python run.py
```

The first run downloads the required model files. Subsequent runs reuse the
completed local cache **without contacting Hugging Face or redownloading**.

Useful overrides:

```bash
python run.py --images inputs/person.png inputs/shirt.png
python run.py --input-images inputs/person-a.png inputs/person-b.png --reference-images inputs/shirt.png
python run.py --model https://huggingface.co/Qwen/Qwen-Image-2.1/tree/main
python run.py --model https://huggingface.co/abenzerps/Qwen-Image-2.1-GGUF
python run.py --model abenzerps/Qwen-Image-2.1-GGUF --filename qwen-image-2.1-Q8_0.gguf
python run.py --offline
python run.py --dry-run
```

`--dry-run` only validates the configuration; it does not validate image paths,
download models, run inference, or fabricate benchmark numbers.

For authenticated repositories, set `HF_TOKEN` in your environment or use your
normal Hugging Face login. Tokens are not read into the run configuration or
written to logs.

## Change parameters directly in Python

All settings are dataclasses in `qwen_runner/config.py`. `run.py` includes an
editable instance; you can also import the runner from your own script:

```python
from qwen_runner.config import Config
from qwen_runner.runner import run

config = Config()
config.model.source = "https://huggingface.co/abenzerps/Qwen-Image-2.1-GGUF"
config.model.gguf_quantization = "Q4_K_M"
config.generation.images = ["inputs/person.png", "inputs/shirt.png"]
config.generation.prompt = (
    "Put the shirt from <image2> on the person in <image1>. "
    "Preserve the person's face, hair, body shape, pose, background and lighting."
)
config.generation.negative_prompt = ""
config.generation.steps = 25
config.generation.cfg = 1.0
config.generation.seed = 42
config.generation.strength = 1.0
config.generation.resolution = 1024  # Set 0 to match the uploaded graph.
config.generation.custom_size = False
config.generation.batch_size = 1
config.generation.kv_cache_device = "auto"
config.runtime.offload = "model"
config.runtime.warmup_runs = 1
config.runtime.repeats = 3
records = run(config)
```

Important parameter semantics:

- **Resolution** controls each reference's approximate area: `resolution²`
  pixels, preserving its aspect ratio. Zero keeps its own dimensions rounded to
  the 32-pixel grid. Width/height take effect only when `custom_size=True`.
- **Strength** maps to the original KSampler's `denoise`. This graph starts
  from an empty latent, not an encoded source image. Lower strength selects the
  last `steps` values from a longer schedule and reduces initial noise. It is
  **not a source-image preservation or blending percentage**.
- **CFG** is actual classifier-free guidance (`true_cfg_scale`), not a
  guidance embedding. Negative conditioning is skipped at CFG 1. CFG below 1
  is supported too.
- **Sampler/scheduler:** Euler with `simple` reproduces the submitted graph.
  Euler with `normal` is also implemented. Other values raise a clear error.
- **KV cache:** `kv_cache=False` recomputes the prefix each step.
  `kv_cache_device="auto"` keeps a configurable CUDA memory reserve, then
  stores additional cache layers on CPU; `"cpu"` and `"gpu"` are explicit.
  CPU cache transfers are synchronous. Storage is lossless, not int8/int4.
- **Reference mode:** default `rgb` matches the connected `LoadImage.IMAGE`
  output. Optional `rgba` preserves alpha for the VAE and composites over white
  for the vision encoder; this is an intentional extension.

## Models and cache

Supported sources:

| Source | Handling |
|---|---|
| `owner/repository` or Hugging Face repo URL | Detect a complete Qwen 2.1 Diffusers pipeline or select a GGUF |
| `/tree/main` URL | Normalize to repository + revision |
| `/blob/revision/file.gguf` or `/resolve/revision/file.gguf` | Select that exact file |
| Local Diffusers folder | Load entirely from that folder |
| Local `.gguf` | Load that transformer and obtain companion components from `base_model` |
| Floating-point `.safetensors` transformer | Strictly match Qwen 2.1 tensor names/shapes; obtain companions from `base_model` |

Only compatible **Qwen Image 2.1** checkpoints reproduce this graph. Older
Qwen-Image, Qwen-Image-Edit and Edit-2511 architectures are rejected rather than
silently using the wrong pipeline. This project is not a universal loader for
arbitrary Hugging Face models, LoRAs or Comfy-specific quantized safetensors.

For the supplied GGUF repository, changing only `source` selects its single
Q4_K_M file. Set `filename` to choose another variant. If multiple files match,
the runner asks for an explicit filename instead of choosing an arbitrary one.
The GGUF loader validates every tensor name and shape and retains packed
quantized linear weights using Diffusers' GGUF kernels. It does **not**
dequantize the entire transformer into BF16. Norms and floating-point weights
remain ordinary floating-point tensors.

GGUF repositories are often transformer-only or bundle Comfy-format companions.
The runner downloads the **Diffusers-format** encoder, processor and VAE from
`model.base_model`, default `Qwen/Qwen-Image-2.1`, plus the transformer config.
It excludes the base model's full transformer weights from this companion
download. `text_encoder_source` can override both the encoder and processor
with another compatible Diffusers-layout repository or local folder.

```text
models/
├── hub/                 # Hugging Face snapshots and deduplicated blobs
└── manifests/           # Completed file selection, sizes and immutable revision
```

An interrupted download never creates a completion manifest. A missing or
truncated cached file invalidates that manifest. Online mode lets the Hub client
reuse its existing blobs and fetch missing files; offline mode fails clearly.
Same-size corruption is not detected by the lightweight size check. Local
folders must contain all required files.

A completed `main` cache stays on its first resolved commit. To test a newer
release, set `model.revision` to its commit hash. Pin `base_revision` as well
when comparing quantizations. Moving the cache to another machine may
invalidate manifests because they contain absolute paths; use a complete local
snapshot path or rebuild the manifests online.

## Benchmark multiple models

Edit `MODELS` in `benchmark.py`, and the shared generation/runtime settings in
`run.py`. Each model runs in a separate process, avoiding overlapping model
allocations:

```bash
python benchmark.py
python scripts/summarize_logs.py outputs > benchmark_summary.csv
```

For comparison, use the same images, prompt, seed, dimensions, steps, cache
settings, hardware and offload mode. Use at least one warmup and multiple
measured repeats. The default reproduces a single cold run, so warmups are zero
unless you configure them. Warmup logs and images are retained but excluded
from the CSV summary. No hidden performance preset changes your parameters.

## Performance measurements and logs

Each requested inference, including warmups, gets a unique JSON file. A
`started` record is written before execution, then updated atomically to
`success`, `error` or `interrupted`. Setup failures get a separate
`*_setup_error.json`. A hard process kill or machine crash can leave `started`
with no completed metrics.

The logs include:

- Model source, repository, selected filename and resolved commit; companion
  model identity and cache hits.
- Actual text encoder, transformer and VAE classes and local component paths.
- Requested and effective parameters, ordered input paths and SHA-256 hashes,
  original/reference/output dimensions, actual seed and complete sigma schedule.
- UTC timestamps, software versions, Diffusers source commit, device, CUDA
  runtime and GPU hardware information when available.
- Inference seconds, setup seconds, memory metrics, saved outputs and hashes,
  warmup status, and tracebacks on failures.

| Metric | Meaning |
|---|---|
| `inference_time_seconds` | Synchronized wall time for prompt encoding, reference VAE encoding, noise creation, denoising, decode and conversion to output images |
| `setup_seconds` | Validation, input file loading/resizing, model resolution/download/load and device setup; shared by all runs in one process |
| `gpu_peak_allocated_bytes` | Reset-per-run PyTorch CUDA allocator peak on the selected device, including resident model allocations |
| `gpu_peak_reserved_bytes` | Peak memory reserved by PyTorch on that device |
| `process_rss_peak_bytes` | Sampled whole-process resident memory during inference, including model memory |
| Baselines and peak increases | Separate the starting footprint from growth during the run |
| MPS sampled allocated peak | Sampled PyTorch MPS allocation; unified memory can overlap RSS |

Image file saving is outside inference timing. CUDA work is synchronized before
and after measurement. CUDA allocator peaks exclude allocations made outside
PyTorch and other processes; they are **not total card VRAM**. RSS is process
memory, not total system RAM, and polling can miss very short spikes. CPU-only
runs use `null` for GPU measurements. Setup/download memory is not included in
the inference peak. JSON stores bytes; the summary uses GiB (`2**30` bytes).

## Project layout

```text
qwen_workflow_runner/
├── run.py                       # Editable configuration and command-line entry
├── benchmark.py                 # Isolated model comparisons
├── requirements.txt
├── requirements-cu126.txt
├── pyproject.toml
├── README.md
├── LICENSE
├── NOTICE
├── qwen_runner/
│   ├── config.py                # Model, generation and runtime configuration
│   ├── models.py                # URL normalization, selection and local cache
│   ├── gguf_loader.py           # Strict packed-GGUF loading
│   ├── images.py                # Workflow sizing and reference image loading
│   ├── sampling.py              # Sigma schedules and denoise behavior
│   ├── kv_cache.py              # Lossless prefix cache placement
│   ├── pipeline.py              # Attributed upstream pipeline with workflow patches
│   ├── backend.py               # Component loading and generation
│   ├── metrics.py               # Synchronized timing and memory sampling
│   └── runner.py                # Repeats, warmups, output saving and JSON logs
├── scripts/
│   ├── download_examples.py
│   └── summarize_logs.py
├── tests/
├── workflow/
│   ├── original.json
│   ├── PORTING_NOTES.md
│   ├── source_manifest.json
│   └── reviewed_gguf_tensor_inventory.json
├── inputs/
├── models/
└── outputs/
```

## Troubleshooting

**Missing QwenImage21 classes:** reinstall `requirements.txt` in the active
environment. Do not substitute `QwenImageEditPlusPipeline`.

**CUDA unavailable:** check that you installed a CUDA PyTorch wheel. For CPU
testing set `device="cpu"`, `dtype="float32"`, `offload="none"`.

**Out of memory or unusable output with large references:** use
`resolution=1024` or lower rather than retaining native multi-megapixel inputs.
`resolution=0` deliberately preserves source dimensions; a 4000x6000 reference
can consume nearly an entire 48 GiB GPU and overwhelm a small output canvas.
Use the GGUF variant and `offload="model"` or `"sequential"`; try CPU KV
storage, disabling the KV cache, or VAE tiling. These change the memory/time
tradeoff and are recorded. The text encoder can still require significant RAM.

**Missing images:** run the example-download script or supply your own images.

**Offline cache missing/incomplete:** populate it once online or specify a
complete local model snapshot. The loader never silently switches models.

**GGUF tensor mismatch:** the file belongs to another architecture or layout.
Use a compatible Qwen 2.1 checkpoint; do not bypass strict validation.

**HF 401/403:** authenticate and obtain access to the repository, if required.
The project does not bypass access restrictions.

## Validation

```bash
python -m unittest discover -s tests -v
```

Core tests do not download weights. Runtime tests use tiny, randomly initialized
networks and temporary GGUF files. They test execution and logging, not image
quality. See `TEST_REPORT.md` for what was actually validated for this delivery.
Full pretrained inference, CUDA peak measurements, offload behavior on a real
GPU and output-quality parity need to be checked on your target hardware.

## Sources and licensing

- [Official Qwen Image 2.1 model](https://huggingface.co/Qwen/Qwen-Image-2.1)
- [Supplied GGUF repository](https://huggingface.co/abenzerps/Qwen-Image-2.1-GGUF)
- [Comfy Qwen nodes](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_qwen.py)
- [Comfy samplers](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/samplers.py)
- [Comfy flow sampling](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/model_sampling.py)
- [Pinned Diffusers source](https://github.com/huggingface/diffusers/tree/fbf49e7f35857f76bc57b177e26f12b03687c668)

The adapted Diffusers pipeline retains its Apache-2.0 attribution; see `NOTICE`
and `LICENSE`. Downloaded model weights and sample assets retain their own
licenses. Model files are not redistributed with this project.

# Qwen Workflow Runner

A local image-editing workspace for **Qwen Image 2.1**, built with Python,
PyTorch, Diffusers, FastAPI, and a self-contained browser UI. Experiment with
prompts, reference images, LoRAs, and runtime settings through eight focused pages.
The same inference core also supports CLI runs and repeatable benchmarks.

This is an experimental application for supported Qwen Image 2.1 checkpoints.
It is not a universal model loader. No ComfyUI installation is required.

![Inference workspace with separate input and reference selections](docs/assets/screenshots/inference.png)

## Contents

- [Features](#features)
- [Installation](#installation)
- [Quickstart](#quickstart)
- [Feature screenshots](#feature-screenshots)
- [Project workflow](#project-workflow)
- [Command-line usage](#command-line-usage)
- [How to modify](#how-to-modify)
- [Testing](#testing)
- [Limitations and troubleshooting](#limitations-and-troubleshooting)
- [Documentation and license](#documentation-and-license)

## Features

- Separate, ordered process inputs and conditioning references, with previews,
  uploads, drag-and-drop, and individual removal.
- Downloaded-model selection, asynchronous Hugging Face downloads, local uploads,
  and confirmed deletion of supported stored models.
- LoRA discovery, upload, selection, strength adjustment, and confirmed deletion.
- GPU inventory and device selection, precision/offload controls, and visible
  resident pipeline state.
- Batch stages, successful/failed/remaining counts, timing, ETA, and live logs.
- Generated previews, input/output comparisons, readable run records, and
  whole-run deletion that preserves shared files.
- Compatible pipeline reuse between web requests and graceful resource cleanup.
- Responsive task pages and accessible, implementation-based parameter help.

## Installation

Use **Python 3.10+** and Git. NVIDIA CUDA is the intended real-inference target.
Model weights are downloaded separately and can require substantial disk space,
RAM, and VRAM. A quantized transformer still needs the text encoder and VAE.

```bash
git clone https://github.com/Farzine/qwen_workflow_runner.git
cd qwen_workflow_runner
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.

For the CUDA 12.6 profile validated on this project's host:

```bash
python -m pip install -r requirements-cu126.txt
python -m pip install -r ui/requirements.txt
python run.py --check
```

For another driver/runtime or CPU, install matching PyTorch and torchvision
using the [official installer](https://pytorch.org/get-started/locally/), then
install `requirements.txt` and `ui/requirements.txt`. The generic requirements do
not select a CUDA build. Keep the pinned Diffusers revision: older Qwen Image/Edit
pipelines are not interchangeable with the dedicated 2.1 implementation.

## Quickstart

Start the production application:

```bash
python ui/app.py --host 127.0.0.1 --port 7878
```

Open **http://localhost:7878**. If the port is busy, the server reports the next
available port. Loopback binding is appropriate for local use; the application
does not provide authentication for public deployment.

1. Open **Models** and download or select a compatible Qwen Image 2.1 model.
   Transformer-only GGUF/SafeTensors entries require compatible companion components.
2. Open **Inference**. Upload or browse your images, select process inputs, and
   optionally select references separately. Each input is processed independently.
3. Enter a prompt. Select an optional LoRA and configure generation settings.
4. Open **System**, choose an available device, and apply its runtime settings.
5. Start inference. Open **Batch** for progress and logs, then inspect comparisons,
   **History**, or **Outputs** when results are ready.

Defaults use `inputs/`, `models/`, `models/loras/`, and `outputs/`. Override directories:

```bash
python ui/app.py --host 127.0.0.1 \
  --inputs-dir /path/to/images \
  --models-dir /path/to/models \
  --loras-dir /path/to/loras \
  --outputs-dir /path/to/results
```

For a GPU-free UI walkthrough:

```bash
python ui/app.py --demo --host 127.0.0.1
```

**Demo mode generates explicitly labeled synthetic previews. It does not run
Qwen or apply a LoRA.** Production errors are reported rather than replaced
with demo images.

## Feature screenshots

The screenshots below come from the running production application using
original geometric toy-robot inputs, a shared color reference, and real Qwen
inference. See [capture details](docs/SCREENSHOTS.md) for settings and validation.

### Dashboard

View server readiness, hardware snapshots, selected resources, resident pipelines,
and recent runs. Batch and download activity reflects the current browser tab.

![Dashboard with runtime and recent inference status](docs/assets/screenshots/dashboard.png)

### Inference

Keep process inputs separate from references; configure the prompt, model, LoRA,
and generation parameters before submitting a job. Accessible help controls explain
parameter behavior and trade-offs.

![Separate inputs and references before submission](docs/assets/screenshots/inference-ready.png)

![Generation settings with steps help open](docs/assets/screenshots/parameter-help.png)

### Batch inference

Follow per-item stages, counts, timing, ETA, and logs while the model works.
Each finished attempt has its own saved record.

![Real batch generation in progress](docs/assets/screenshots/batch-progress.png)

![Completed batch with generated images](docs/assets/screenshots/batch.png)

### History and run details

Inspect saved runs and readable input, model, adapter, generation, hardware, and
output facts. Technical JSON remains available when needed.

![Saved run history](docs/assets/screenshots/history.png)

![Human-readable run details](docs/assets/screenshots/run-details.png)

### Outputs and comparisons

Browse recorded outputs, open the exact selected image, download it, or compare it
with its process input. Deletion removes a whole run and its unshared artifacts.

![Output library](docs/assets/screenshots/outputs.png)

![Original illustration and actual generated result side by side](docs/assets/screenshots/comparison.png)

### Models

Download from Hugging Face, upload local checkpoints, select a compatible model,
or confirm deletion. The selected catalog model is authoritative for inference.

![Model download, upload, and selection controls](docs/assets/screenshots/models.png)

### LoRAs

Manage local SafeTensors adapters and their strength. This capture shows the
supplied adapter selected after an actual LoRA-enabled run.

![LoRA catalog and strength controls](docs/assets/screenshots/loras.png)

### System and smaller screens

Inspect GPU memory, PyTorch/CUDA, selected device, and loaded resources. Applied
settings affect the next job. Task pages also adapt to narrow viewports.

![System configuration and resident resources](docs/assets/screenshots/system.png)

<details>
<summary>View the mobile output browser</summary>

![Output browser at a 390-pixel viewport](docs/assets/screenshots/mobile-outputs.png)

</details>

## Project workflow

![Complete project workflow](docs/assets/workflow.svg)

<details>
<summary>Editable Mermaid diagram</summary>

```mermaid
flowchart TD
    Browser[Browser: eight task pages] <-->|REST and SSE| API[FastAPI: validation and storage APIs]
    API --> Catalog[Selected model catalog]
    API --> Downloads[Background downloads and uploads]
    Hub[Hugging Face] --> Downloads
    Downloads --> Store[Model files and completed manifests]
    Store --> Catalog
    Browser --> Config[Inputs, references, prompt, LoRA and device]
    Config --> API
    API --> Queue[Single-worker job queue]
    Queue --> Resources[Exclusive per-device pipeline manager]
    Catalog --> Resources
    LoRA[Local LoRA files] --> Resources
    System[Device, precision and offload] --> Resources
    Resources -->|Load or reuse| Pipeline[Qwen model, encoder and VAE]
    CLI[CLI and benchmark] --> Runner[Core runner: ordered inputs and repeats]
    Queue --> Runner
    Runner --> Prepare[EXIF, RGB, dimensions and seeded noise]
    Prepare --> Pipeline
    Pipeline --> Generate[Conditioning, denoising and decoding]
    Generate --> Save[PNG outputs, comparisons and JSON records]
    Save --> API
    API -->|Progress and results| Browser
    Resources --> Shutdown[Drain jobs, unload resources and clear GPU caches]
```

</details>

Download the [SVG](docs/assets/workflow.svg) or [PNG](docs/assets/workflow.png) for presentations.
The browser uses no Node service or external CDN. The CLI shares inference logic;
resident reuse is managed by the long-running web server.

## Command-line usage

Supply your own files, or fetch the public workflow examples with
`python scripts/download_examples.py`.

```bash
python run.py --input-images inputs/person.png \
  --reference-images inputs/reference.png
python run.py --input-images inputs/person.png \
  --reference-images inputs/reference.png \
  --lora models/loras/adapter.safetensors --lora-scale 0.8
python run.py --offline
python run.py --dry-run
```

Edit `CONFIG` in `run.py` for the prompt, model, output sizing, and runtime settings.
`--dry-run` validates configuration only; it does not verify files or run inference.
For benchmarks, edit `MODELS` in `benchmark.py`, then run:

```bash
python benchmark.py
python scripts/summarize_logs.py outputs > benchmark_summary.csv
```

See the [detailed usage guide](docs/USAGE.md) for model formats, Python integration,
cache semantics, measurements, and workflow fidelity.

## How to modify

Start with the smallest relevant layer, then validate the affected workflow.

| Customization | Where to work |
| --- | --- |
| Default prompt, model source, generation/runtime parameters | `run.py` and dataclasses in `qwen_runner/config.py` |
| UI layout, labels, navigation | `ui/templates/index.html` |
| Colors, spacing, responsive layout | `ui/static/css/style.css` |
| Browser interactions, state, parameter help | `ui/static/js/app.js` |
| API endpoints, validation, directory policies | `ui/server.py` |
| Job execution, logs, progress and monitoring | `ui/runner_bridge.py` |
| Model compatibility, downloads and storage | `ui/model_catalog.py`, `ui/download_jobs.py`, `qwen_runner/models.py` |
| Pipeline reuse and shutdown | `qwen_runner/resources.py` |
| Preprocessing, model/LoRA loading or denoising | `qwen_runner/images.py`, `qwen_runner/backend.py`, `qwen_runner/pipeline.py` |
| Output records and readable metadata | `qwen_runner/runner.py`, `qwen_runner/record_metadata.py` |

1. Create a branch and change only the layer needed for your customization.
2. For a new parameter, update its dataclass validation, browser collection/help,
   API propagation, and saved metadata together. Keep essential model selection
   authoritative; an advanced field must not silently replace it.
3. Preserve process-input/reference ordering, path validation, active-job locks,
   explicit errors, and accessibility when changing UI or APIs.
4. Run relevant existing tests and check the actual UI. Use demo mode for UI
   iteration, then real inference for changes affecting model behavior.

Adding another model family requires deliberate loader, pipeline, catalog,
validation, and test support; renaming a model option is insufficient.
Static UI changes need no build step. Restart the server after Python changes,
or use `--reload` during local development.

## Testing

Install pytest into your development environment if needed, then run:

```bash
python -m pytest -q tests ui/tests
node ui/tests/test_challenger_m2_node.js
node ui/tests/test_tier5_node_stress.js
```

The tests include CPU/demo logic, API/storage behavior, resource lifecycles, and
frontend regression checks. They do not establish full-model quality or universal
GPU compatibility. Optional real-browser and Hub checks are documented in
[the UI guide](ui/README.md#testing--verification).

[VALIDATION_MATRIX.md](VALIDATION_MATRIX.md) records exact test scope, evidence,
and known gaps. Its historical counts are observations, not a fresh test guarantee.

## Limitations and troubleshooting

- **Supported models:** compatible Qwen Image 2.1 full pipelines or supported
  transformer-only formats with matching companions. Other families and
  Comfy-specific `int8_convrot` checkpoints are rejected.
- **Memory:** native reference resolution (`0`) can exhaust VRAM. Start with
  bounded reference dimensions and model offload; quantization does not eliminate
  encoder memory requirements.
- **Monitoring:** Stop monitoring disconnects the browser stream; inference
  continues. Reconnect requires the same tab/job identity. It is not cancellation.
- **Persistence:** records in the configured default output directory survive
  restart. Custom per-run output roots are discovered only during that server session.
- **Downloads:** cancellation is cooperative between file operations; a file
  already transferring may finish. Unknown totals show indeterminate progress.
- **Security:** designed for trusted local use. Do not expose the unauthenticated
  server directly to the public internet.
- **Errors:** inspect the stage and log details. Missing weights, incompatible
  LoRAs, unavailable GPUs, or invalid inputs are not silently repaired by switching models.

More troubleshooting and measurement details are in [docs/USAGE.md](docs/USAGE.md).

## Documentation and license

- [Web UI, startup options, APIs, and security](ui/README.md)
- [Detailed CLI and model guide](docs/USAGE.md)
- [Workflow porting and implementation differences](workflow/PORTING_NOTES.md)
- [Validation matrix](VALIDATION_MATRIX.md)
- [Persistent development handoff](CONTEXT.md) and [historical context](docs/CONTEXT_HISTORY.md)
- [LinkedIn caption and presentation assets](linkedin-post/README.md)

Code is licensed under [Apache 2.0](LICENSE), with upstream attributions in
[NOTICE](NOTICE). Model weights, adapters, and downloaded sample assets retain
their own licenses. Weights are not distributed with this repository.

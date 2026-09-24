# Qwen Image 2.1 — Web UI Application Server

A high-performance, modern, production-grade Web UI and API application server for the **Qwen Image 2.1** workflow runner. Enables configuring, running, and inspecting multi-image generative editing workflows entirely through the browser with zero external CDN dependencies.

---

## Table of Contents

- [Overview & Architecture](#overview--architecture)
- [Quickstart Guide](#quickstart-guide)
- [Parameter Help](#parameter-help)
- [CLI Reference](#cli-reference)
- [Automatic Port Conflict Fallback](#automatic-port-conflict-fallback)
- [Environment Variables](#environment-variables)
- [REST & SSE API Reference](#rest--sse-api-reference)
- [Project Layout](#project-layout)
- [Testing & Verification](#testing--verification)
- [Security Model](#security-model)

---

## Overview & Architecture

The Web UI integrates seamlessly with `qwen_runner` to provide an intuitive visual studio for generative editing:

- **Input & Reference Workspace**: Scans configured input folders, accepts validated multi-file uploads and drag-and-drop, and keeps 1–10 ordered process inputs separate from up to nine shared conditioning references.
- **Comprehensive Parameter Form**: Controls exposing every parameter across `ModelConfig`, `GenerationConfig`, and `RuntimeConfig` with real-time validation, presets, and implementation-backed help for behavior, ranges, interactions, and resource trade-offs.
- **Model and LoRA Management**: Live asynchronous downloading of Hugging Face repositories, chunked local model uploads, cached model discovery, and a separate validated LoRA catalog with upload, selection, and strength controls.
- **System Configuration**: Live CPU/RAM and GPU inventory, per-GPU total/free/used memory, PyTorch/CUDA versions, runtime readiness, and dynamic device selection for the next production run.
- **Execution & Output Hub**: Non-blocking background execution with real-time SSE streaming logs, step progress bar, output gallery with byte-accurate SHA-256 badges, interactive split-view comparison slider, 2-up side-by-side mode, expandable JSON record viewer with export, and session run history.
- **Zero CDN Dependencies**: Self-contained Vanilla JS and CSS3 design; 100% offline-ready in air-gapped laboratory environments.

```
Browser (Vanilla SPA HTML5 / CSS3 / ES2020)
  ├── Input Browser (folder tree, uploads, process-input tray, reference tray)
  ├── Parameter Form (ModelConfig, GenerationConfig, RuntimeConfig with live validation)
  ├── Model Hub (HF downloader with SSE progress, chunked uploader, cached models)
  ├── System Page (live host/GPU inventory, device, precision, offload, runtime state)
  └── Execution Hub (SSE live logs, output gallery, split comparison slider, JSON viewer)
        │
        ▼ HTTP REST & SSE Streaming
Backend Server (`ui/app.py` / `ui/server.py` via FastAPI & Uvicorn)
  ├── Static Asset & Thumbnail Service (disk-cached 256px/1024px thumbnails)
  ├── Model Store & Upload Processor (chunked reassembly, SHA-256 validation)
  ├── Config Validation Engine (direct integration with Config.validate())
  └── Background Runner Bridge:
        ├── Thread worker queue executing qwen_runner.runner.run()
        ├── Stdout/stderr pipe interception streamed to SSE clients
        └── Synthetic DemoBackend for fast offline mock execution
```

---

## Quickstart Guide

### 1. Prerequisites

Ensure Python 3.10+ and the required packages are installed in your virtual environment:

```bash
# Activate your virtual environment
source .venv/bin/activate

# Install core runner and UI dependencies
pip install -r requirements.txt
pip install -r ui/requirements.txt
```

### 2. Single-Command Startup

Start the server using `ui/app.py`:

```bash
# Option A: From the project root
python ui/app.py

# Option B: From inside the ui/ directory
cd ui
python app.py
```

The server automatically starts on **http://0.0.0.0:7878** (or the next available port if 7878 is busy). Open **http://localhost:7878** in your browser.

### 3. Demo Mode (Offline / GPU-less Testing)

To test the complete workflow without loading model weights into GPU memory, start in demo mode:

```bash
python ui/app.py --demo
```

Demo mode is an explicit synthetic preview. `DemoBackend` derives a labeled image from the first input and writes valid PNG, comparison, and `{run_id}.json` artifacts, but it does not load or run the Qwen model. Normal startup defaults to production inference. If the selected production runtime is unavailable, the run reports a setup error instead of silently substituting demo output.

---

## Parameter Help

Each meaningful generation, runtime, system, model, LoRA, output, and demo control has an information button beside its label. Hover it, focus it from the keyboard, or click/tap it to open the shared help card. Press `Escape`, move focus away, scroll, or interact outside the card to close it.

The text follows the implemented configuration and execution paths. It documents details that generic diffusion guidance often misses here, including:

- denoise strength selects a schedule tail for an empty latent and does not blend input pixels;
- negative conditioning runs only with non-empty negative text and CFG other than exactly `1`;
- native reference resolution (`0`) can retain very large source dimensions and exhaust VRAM;
- KV-cache auto placement uses the configured CUDA reserve before spilling lossless cache layers to CPU;
- repeat seeds are shared across process inputs within a repeat, while optional incrementing occurs between repeats;
- CPU requires float32 with no model offload, and device changes apply to the next job;
- synthetic demo output is input-derived and never applies the selected production model or LoRA.

Validation messages remain visible outside these help cards, so required corrections do not depend on hover or tooltip access.

---

## CLI Reference

`ui/app.py` provides a complete CLI interface via `argparse`:

| Argument | Type | Default | Description | Example |
|---|---|---|---|---|
| `--host` | `str` | `0.0.0.0` | Host IP address to bind to | `--host 127.0.0.1` |
| `--port` | `int` | `7878` | TCP port number to listen on | `--port 8080` |
| `--demo` | `flag` | `False` | Run with synthetic demo backend | `--demo` |
| `--inputs-dir` | `str` | `None` | Path override for input reference images | `--inputs-dir /data/inputs` |
| `--models-dir` | `str` | `None` | Path override for model storage directory | `--models-dir /data/models` |
| `--loras-dir` | `str` | `None` | Path override for discovered and uploaded LoRA adapters | `--loras-dir /data/loras` |
| `--outputs-dir`| `str` | `None` | Path override for output images & records | `--outputs-dir /data/outputs` |
| `--reload` | `flag` | `False` | Enable auto-reload for local development | `--reload` |

### CLI Usage Examples

```bash
# Bind to localhost on port 9000 in demo mode
python ui/app.py --host 127.0.0.1 --port 9000 --demo

# Specify custom dataset and output directories
python ui/app.py --inputs-dir /mnt/lab/farzine/inputs --loras-dir /mnt/lab/farzine/loras --outputs-dir /mnt/lab/farzine/outputs

# Launch in developer mode with live reload
python ui/app.py --reload --port 7878
```

---

## Automatic Port Conflict Fallback

When starting the application, `ui/app.py` probes the requested port via `find_open_port(host, start_port, max_tries=100)`.

If the requested port is already occupied (e.g. by another service or another instance of the Web UI), the server will **not crash**. Instead, it automatically probes subsequent ports, prints an informative console notice, and binds to the first available open port:

```
[INFO] Port 7878 is already in use. Automatically falling back to open port: 7879
[INFO] Starting Qwen Image 2.1 Web UI on http://0.0.0.0:7879 (demo=False)
```

---

## Environment Variables

Directory paths and operational modes can also be configured via environment variables:

| Variable | Default Fallback | Purpose |
|---|---|---|
| `INPUTS_DIR` | `/mnt/lab/farzine/inputs` (or `inputs/`) | Root directory scanned by the input browser |
| `MODELS_DIR` | `models/` | Storage location for cached weights and uploads |
| `LORAS_DIR` | `models/loras/` | Storage location for discovered and uploaded `.safetensors` adapters |
| `OUTPUTS_DIR` | `outputs/` | Target location for output images and JSON records |
| `DEMO_MODE` | `0` (or `False`) | Set to `1` or `true` to force synthetic demo backend |
| `UI_STATE_DIR` | `None` | Optional unified base directory for inputs, models, and outputs |

*Note: CLI flags take precedence over environment variables.*

---

## REST & SSE API Reference

The backend provides a structured REST and Server-Sent Events (SSE) API:

### 1. Inputs & Thumbnails

- **`GET /api/inputs/browse`**
  - Query parameters: `folder` (optional subfolder path)
  - Response:
    ```json
    {
      "folders": ["Men", "Women", "Objects"],
      "images": [
        {
          "name": "men_001.jpg",
          "path": "/mnt/lab/farzine/inputs/Men/men_001.jpg",
          "width": 1024,
          "height": 1024,
          "size": 154230,
          "thumb_url": "/api/inputs/thumbnail?path=...&size=256"
        }
      ]
    }
    ```
- **`GET /api/inputs/thumbnail`**
  - Query parameters: `path` (absolute or relative image path), `size` (optional max dimension, default: 256)
  - Response: Binary JPEG/PNG image with disk caching in `.cache/thumbnails/`.
- **`POST /api/inputs/upload`**
  - Multipart field: one to ten `files` entries per request.
  - Accepts decoded JPEG, PNG, WebP, BMP, and GIF files up to 64 MiB each. The filename extension must match the detected image format.
  - Stores the batch under the configured `inputs/uploads/` directory with sanitized, collision-safe names. Validation is atomic: if one file is invalid, none of that request's files remain stored.
  - Response: `{"success": true, "count": 2, "images": [{"name": "...", "original_name": "...", "path": "...", "width": 1024, "height": 1024, "thumb_url": "..."}]}`.

### 2. Model Catalog & Uploads

- **`GET /api/models`**
  - Lists downloaded models in the configured `models/` storage with stable IDs,
    Qwen Image 2.1 compatibility results, and companion-pipeline paths for
    transformer-only checkpoints. Unsupported or incomplete entries remain
    visible with `compatible: false` and a `compatibility_reason`.
  - Response:
    ```json
    {
      "models": [
        {
          "id": "model_4ff66ef0ec9f18e2d3e2",
          "name": "Qwen-Image-2.1",
          "path": "/path/to/models/Qwen-Image-2.1",
          "type": "diffusers",
          "size": 33130000000,
          "is_cached": true,
          "compatible": true,
          "compatibility_reason": null,
          "companion_path": null
        }
      ]
    }
    ```
  - The web client sends `selected_model_id` at the top level of
    `POST /api/config/validate` and `POST /api/run`. The server resolves it
    against the current catalog and ignores conflicting source/companion
    fields in `model`; stale or incompatible IDs are rejected. Requests that
    omit the ID retain the legacy direct-source API contract.
- **`POST /api/models/download`**
  - Initiates asynchronous background download from Hugging Face Hub.
  - Payload: `{"repo_id": "Qwen/Qwen-Image-2.1", "filename": "...", "revision": "main"}`
  - Response: `{"task_id": "download_uuid", "status": "queued"}`
- **`GET /api/models/download/progress/{task_id}`**
  - Returns a thread-safe JSON snapshot by default: `status`, `downloaded_bytes`,
    `total_bytes`, `completed_files`, `total_files`, `remaining_files`,
    `current_file`, `speed_bytes_per_second`, `eta_seconds`, `percent`, and
    `error`. Unknown totals, percent, speed, and ETA are `null`; failures do
    not report 100%. States are queued, preparing, downloading, verifying,
    cancelling, completed, failed, and cancelled.
  - `?stream=true` or `Accept: text/event-stream` emits the same snapshots as
    progress events and a final complete event for terminal states.
- **`POST /api/models/download/{task_id}/cancel`**
  - Requests cooperative cancellation after the current Hub file operation.
    A terminal job returns HTTP 409. Partial work remains in the Hub cache.
    Cancellation before manifest publication leaves no new manifest; if the
    request races with final publication, a valid cached model may remain.
- **`POST /api/models/download/{task_id}/retry`**
  - Starts a new attempt for a failed or cancelled job, returning a new task ID
    and `retry_of`. Complete cached files are reused. Active/completed jobs
    return HTTP 409.
- **`POST /api/models/upload`**
  - Multipart chunked upload for `.gguf` and `.safetensors` files directly into `models/`.
  - Form fields: `file` (UploadFile), `upload_id` (str), `chunk_index` (int), `total_chunks` (int).

### 3. LoRA Catalog & Upload

- **`GET /api/loras`**
  - Lists `.safetensors` files in the configured LoRA directory, including size, modification time, SafeTensors metadata, tensor count, and validation errors.
  - Invalid files remain visible but cannot be selected in the browser.
- **`POST /api/loras/upload`**
  - Accepts one `.safetensors` multipart file, streams it with a 4 GiB limit, validates its SafeTensors header and LoRA tensor keys, and atomically stores it under a sanitized collision-safe name.
  - A successful upload is refreshed into the catalog and selected automatically.

The selected file path and strength are sent as `model.lora_path` and
`model.lora_scale`. Production inference loads and activates the adapter before
device placement. Synthetic demo mode reports the requested adapter as not
applied because it does not load a model.

### 4. Configuration & Validation

- **`GET /api/system?device=cuda:0&dtype=bfloat16&offload=model`**
  - Reports Python/PyTorch/CUDA versions, CPU and system RAM, CUDA and MPS availability, per-GPU total/free/used and process memory, selected-device readiness, server backend defaults, active/last-run state, and resident pipeline cache slots.
  - The server retains one compatible production pipeline per device. Applying configuration changes the next submitted request; it never moves or mutates a pipeline held by an active job. Model/runtime incompatibility replaces only that device's slot, while compatible requests reuse its weights.

The browser’s **System** tab builds its device list from this response. Selecting
CPU automatically uses `float32` with no offload; selecting MPS disables
offload. CUDA choices retain the selected precision and offload mode and are
sent as `runtime.device`, `runtime.dtype`, and `runtime.offload`. The production
backend validates the combination, calls `torch.cuda.set_device()` for CUDA,
and passes that exact device to pipeline placement or Accelerate offload.

- **`POST /api/config/validate`**
  - Validates full or partial runner configuration against `qwen_runner.config.Config.validate()`.
  - Response (Valid): `{"valid": true, "errors": []}`
  - Response (Invalid): `{"valid": false, "errors": ["Steps must be >= 1", "..."]}`

### 5. Workflow Execution & Streaming

- **`POST /api/run`**
  - Submits a new inference run to the background worker queue.
  - Payload: Complete config object matching `Config` schema + optional `"demo_mode": bool`.
  - New clients should send `generation.input_images` and `generation.reference_images`. Each input is processed independently with the same ordered references while the model remains loaded. Legacy `generation.images` remains supported as one combined sequence whose first item is the input/canvas.
  - Example generation payload: `{"input_images": ["/inputs/a.png", "/inputs/b.png"], "reference_images": ["/inputs/style.png"], "steps": 25}`.
  - Successful multi-input responses expose all non-warmup artifacts in `outputs` and `comparisons`. Per-input failures remain in `records`/`errors`; mixed outcomes use status `partial_success`.
  - `demo_mode` defaults to `false` unless the server was explicitly started with `--demo` or `DEMO_MODE=1`. It must be a JSON boolean. Production requests never fall back to `DemoBackend`.
  - Response:
    ```json
    {
      "run_id": "20260923T050000_abc12345",
      "stream_url": "/api/run/20260923T050000_abc12345/stream"
    }
    ```
- **`GET /api/run/{run_id}/stream`**
  - Real-time Server-Sent Events stream:
    - `event: status`: `{"status": "RUNNING"}`
    - `event: log`: `{"text": "[INFO] Starting step 1/20..."}`
    - `event: progress`: `{"step": 1, "total": 20, "percent": 5}`
    - `event: complete`: `{"status": "success|partial_success|error", "outputs": [...], "comparisons": [...], "records": [...], "errors": [...]}`
    - `event: error`: `{"status": "FAILED", "error": "CUDA out of memory"}`

### 6. Outputs & History

- **`GET /api/runs`**
  - Returns list of all execution records in the current session.
- **`GET /api/runs/{run_id}`**
  - Returns the complete `{run_id}.json` benchmark and execution record.
- **`GET /api/outputs/{filename}`**
  - Serves generated image files and side-by-side comparison images with cache control.

---

## Project Layout

```
ui/
├── app.py                      # Single-command CLI entrypoint & port fallback runner
├── server.py                   # FastAPI backend server with REST & SSE endpoints
├── runner_bridge.py            # Async execution manager, log capture & DemoBackend
├── requirements.txt            # UI-specific Python dependencies
├── README.md                   # This documentation
├── templates/
│   └── index.html              # Modern single-page web app (zero CDN dependencies)
├── static/
│   ├── css/
│   │   └── style.css           # Responsive stylesheet (dark/light theme, split slider)
│   └── js/
│       └── app.js              # SPA client application (controllers, SSE stream consumer)
└── tests/
    ├── test_app.py             # CLI flags, port probing & app startup unit tests
    ├── test_backend.py         # Backend endpoints, concurrency & boundary tests
    ├── test_frontend.py        # Template validation, parameter coverage & asset checks
    ├── test_challenger_m2_node.js # Headless DOM state machine tests
    ├── test_tier5_node_stress.js # Adversarial frontend state tests
    └── e2e/
        ├── runner.py           # Master 4-tier E2E test suite runner
        ├── test_tier1_features.py # Tier 1: core features
        ├── test_tier2_boundaries.py # Tier 2: boundary cases
        ├── test_tier3_pairwise.py # Tier 3: pairwise combinations
        └── test_tier4_scenarios.py # Tier 4: real-world workflows
```

---

## Testing & Verification

Run the full verification suite across all layers of the application:

```bash
# Core configuration, model, scheduler, LoRA, and runtime tests
.venv/bin/python -m pytest -q tests

# Complete API, DOM, accessibility, boundary, stress, and E2E suite.
# Host IPC/loopback access is required by Starlette TestClient here.
timeout 300 .venv/bin/python -m pytest -q ui/tests

# Browser state-machine and adversarial frontend harnesses
node ui/tests/test_challenger_m2_node.js
node ui/tests/test_tier5_node_stress.js
```

The final Phase 8 result is 31 core tests plus 8 parameterized subtests, 417
UI/API/E2E tests, and 33/33 plus 15/15 Node cases. The full-model production
browser run and scenario matrix are recorded in `../VALIDATION_MATRIX.md`.

---

## Security Model

- **Safe Path Confinement**: All input and output file paths are validated against allowed root directories via `is_safe_path()`. Directory traversal attempts (e.g. `../../etc/passwd`) are rejected with HTTP 400.
- **Upload Sanitization**: Chunked upload filenames and IDs are sanitized to prevent shell injections and directory traversal.
- **Zero External CDNs**: All fonts, stylesheets, icons (SVG), and scripts are bundled locally; no external network requests are made by the browser.
- **Process Isolation**: Runner executions occur within managed background workers without blocking the asynchronous ASGI event loop.

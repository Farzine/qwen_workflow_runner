# Project: Qwen Workflow Runner Web UI

## Architecture
The Qwen Workflow Runner Web UI is a high-performance, single-command web application located at `ui/` that wraps `qwen_runner` to provide browser-based execution for the Qwen Image 2.1 image-editing pipeline.

### System Architecture
```
Browser (Vanilla SPA HTML/CSS/JS)
  ├── Primary pages: Dashboard, Inference, Batch, History, Outputs, Models, LoRAs, System
  ├── 1. Input Browser: Folder tree, thumbnail grid, 1-10 drag/click ordered selector
  ├── 2. Parameter Form: ModelConfig, GenerationConfig, RuntimeConfig with live validation and accessible implementation-backed help
  ├── 3. Model & LoRA Managers: authoritative compatible catalog selection, measured HF downloads, validated uploads, confirmed deletion
  ├── 4. System Configuration: live CPU/RAM/GPU inventory and dynamic production-device selection
  ├── 5. Run & Output Hub: Launch button, live SSE log/progress stream, output gallery, comparison, readable run details, optional JSON, run history
  │
  ▼ [HTTP REST & SSE]
Backend Server (`ui/app.py` / `ui/server.py` using FastAPI / Starlette / ASGI)
  ├── Static & Thumbnail Service: Serves SPA, caches resized thumbnails for `/mnt/lab/farzine/inputs/`
  ├── Model Manager: HuggingFace Hub async downloader, chunked file upload to `models/`, cached scanner
  ├── Config Validator: Endpoints to validate Config against `qwen_runner.config.Config.validate()`
  ├── Background Execution Engine:
  │     ├── PipelineManager: one leased compatible production pipeline per device; reuse, adapter switching, explicit shutdown
  │     ├── Task queue & thread worker invoking `qwen_runner.runner.run(config, backend_factory=...)`
  │     ├── Real-time stdout/stderr capture redirected to SSE event stream
  │     ├── Demo mode support: `DemoBackend` for synthetic fast execution with real outputs & JSON records
  │     └── Output manager: Serves PNG outputs, comparisons, and `{run_id}.json` records
```

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Input Directory Scanner | Scans `/mnt/lab/farzine/inputs/`, groups images by subfolder, filters `.DS_Store` | M1, M2 | R1, survey |
| 2 | Separate Input & Reference Ordering | Keeps 1–10 ordered process inputs separate from up to nine shared references; each input produces an independent output | M1, M2 | R1, survey |
| 3 | Image Previews & Thumbnails | Displays responsive thumbnails in selection order before run with fast server caching | M1, M2 | R1, survey |
| 4 | Prompt & Negative Controls | Prompt text with `<image1>`..`<image10>` and negative prompt conditioning | M1, M2 | R2, survey |
| 5 | Steps & Batch Size | Steps slider (1–10000) and batch_size (>=1) with validation hints | M1, M2 | R2, survey |
| 6 | CFG Guidance | True CFG scale (>= 0.0) with hint that CFG=1.0 disables negative prompt | M1, M2 | R2, survey |
| 7 | Seed & Randomize | 64-bit unsigned integer seed with random button and seed increment toggle | M1, M2 | R2, survey |
| 8 | Strength & Schedule Limit | Denoise strength (0, 1] with validation guard `int(steps/strength) <= 10000` | M1, M2 | R2, survey |
| 9 | Resolution & Custom Size | Resolution (0 or multiple of 32 <= 4096) and custom width/height toggles | M1, M2 | R2, survey |
| 10 | Sampler & Scheduler | Sampler strictly 'euler', scheduler choice 'simple' or 'normal' | M1, M2 | R2, survey |
| 11 | Flow Shift Control | Flow model shift factor [-10.0, 10.0] with default 0.69 | M1, M2 | R2, survey |
| 12 | KV Cache Configuration | KV cache toggle, device selection ('auto', 'gpu', 'cpu'), and reserve GiB | M1, M2 | R2, survey |
| 13 | Reference Color Mode | Reference mode selector ('rgb' or 'rgba') | M1, M2 | R2, survey |
| 14 | System & Device Configuration | Dynamic CPU/MPS/CUDA choices, per-GPU memory, software/host inventory, readiness, dtype/offload, and next-run application | M1, M2 | R2, survey |
| 15 | Offload & VAE Tiling | Offload mode ('none', 'model', 'sequential') and VAE tiling toggle | M1, M2 | R2, survey |
| 16 | Repeats, Warmup & Polling | Repeats (>=1), warmup_runs (>=0), memory_poll_seconds (0.001-1.0) | M1, M2 | R2, survey |
| 17 | Output Path & Prefix | Output directory string and filename prefix (strictly filename, no slashes) | M1, M2 | R2, survey |
| 18 | Save Comparison Toggle | Comparison toggle generating `{run_id}_comparison.png` | M1, M2 | R2, survey |
| 19 | Validation Feedback | Displays user-friendly error messages on invalid parameters without crashing server | M1, M2 | R2, survey |
| 20 | HF Model Repo Selector | Input for repo ID / URL with live offline/cached status indicator | M1, M2 | R3, survey |
| 21 | Model Downloader | Asynchronous Hugging Face download with live progress bar / status | M1, M2 | R3, survey |
| 22 | Local File Uploader | Drag-and-drop file upload for `.gguf` and `.safetensors` to `models/` directory | M1, M2 | R3, survey |
| 23 | Cached Models Dropdown | Dropdown listing all cached/discovered models in `models/` for quick reuse | M1, M2 | R3, survey |
| 24 | GGUF Variant Selector | Quantization variant selector / filename field for GGUF repos | M1, M2 | R3, survey |
| 24a | LoRA Adapter Manager | Discover, validate, upload, select, scale, apply, and record one Qwen Image 2.1 adapter | M1, M2 | R3, survey |
| 24b | Parameter Help | Keyboard, hover, and touch-accessible guidance derived from config, scheduling, image sizing, caching, runtime, and model-loader behavior | M2 | R2, ORIGINAL_REQUEST |
| 25 | Background Inference Runner | Non-blocking execution of `qwen_runner.runner.run(config)` | M1, M2 | R4, survey |
| 26 | Live Log & Progress Stream | Server-Sent Events stream of runner logs, status, and step progress | M1, M2 | R4, survey |
| 27 | Output Image Viewer | Displays output images with filename, dimensions, and SHA-256 hash badge | M1, M2 | R4, survey |
| 28 | Side-by-Side Comparison | Side-by-side comparison view between canvas image and generated output | M1, M2 | R4, survey |
| 29 | Run Details Viewer | Versioned readable facts plus expandable JSON and download for `{run_id}.json` | M1, M2 | R4, survey |
| 30 | Run History Viewer | Durable history with input/model context, clickable records, and status badges | M1, M2 | R4, survey |
| 31 | Demo Integrity Backend | Synthetic fast execution backend producing real images and records for demo mode | M1, M3 | ORIGINAL_REQUEST |
| 32 | Single-Command Startup | Single command `python app.py` starts server with auto-port fallback and docs | M3 | App Startup |
| 33 | Task Navigation & Dashboard | Eight responsive destinations; timestamped runtime/resources, local activity, recent records, and status retry | M7 | Improvement request |
| 34 | Saved Output Browser | Record-linked artifacts, exact image selection, lazy previews, comparison/download, and confirmed whole-run deletion | M6, M7 | Improvement request |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Backend API & Runner Integration | Fast backend server (`ui/server.py`), endpoints for inputs scanning, thumbnail caching, model upload/download/caching, parameter validation via `Config.validate()`, background runner execution with SSE log streaming, and explicit synthetic demo mode | none | COMPLETE |
| M2 | Modern Frontend Web UI | Single-page application (`ui/static/`, `ui/templates/index.html`) implementing separate input/reference selection, full parameter and system controls, model/LoRA management, responsive navigation, accessible help, live execution, outputs, comparison, records, and history | M1 contracts | COMPLETE |
| M3 | App Startup, CLI & Packaging | Entrypoint script (`ui/app.py`), configurable port fallback, directory overrides, documentation, and dependency profiles | M1, M2 | COMPLETE |
| M4 | E2E Verification & Adversarial Hardening | Full automated suites plus hardware-gated browser production validation; evidence in `VALIDATION_MATRIX.md` | M1, M2, M3 | COMPLETE |
| M5 | Persistent Resource Lifecycle | One exclusive cached production pipeline per device, compatible reuse, LoRA switching, runtime telemetry, and explicit shutdown cleanup | M1, M4 | COMPLETE |
| M6 | Dynamic Model Authority & Management | Stable model IDs, compatibility inspection, authoritative selection, download progress, and safe model/LoRA/output deletion | M5 | COMPLETE for supported Qwen 2.1 assets; hardware/HTTP/Xet evidence in VALIDATION_MATRIX.md |
| M7 | Records, Batch UX & Task Pages | Versioned human-readable metadata, detailed batch state/ETA, and all eight primary destinations | M6 | COMPLETE; regression/browser evidence in VALIDATION_MATRIX.md |
| M8 | Expanded Validation & Documentation | Integrated navigation/regression, current documentation, and bounded hardware/online follow-up | M6, M7 | COMPLETE for documented scope; Phase 9.8d review complete |

Phase 10.1 is complete: both model upload paths reject existing destinations
and publish complete new files atomically without replacement, protecting files
referenced by active jobs and uploads racing to the same filename. Temporary
asset tests cover conflicts, cleanup, catalog refresh, and frontend errors.
Phase 10.2 is complete: UI stress tests generate their own temporary inputs
and history, sibling/E2E runners drain before cleanup, and pytest isolates
thumbnail writes and guards repository runtime file metadata. The full suite
passed with unchanged runtime snapshots. Phase 10.3 is complete: uploaded models
are selected by matching the final receipt path to a refreshed compatible catalog
ID; failures preserve the prior valid selection. Phase 10.4 is complete: browser
defaults/presets, validation, submission, and singleton history honor the configured
output root while preserving explicit per-run paths. Phase 10.5 is complete:
background completion preserves saved inspection in History/Outputs and displays
the finished job when returning to Inference/Batch; deletion and late-response
guards prevent stale artifacts from reappearing. Phase 10.6 is complete: stopped or
disconnected monitoring keeps the job unverified and submission locked; the shared
result header reconnects the same SSE job without resubmission, preserving saved
inspection and accepting only verified completion. Phase 10.7 is complete:
long-job replay restores the latest full batch snapshot beyond the 5,000-event
history ceiling, before live events or completion, under the existing job lock.
Phase 10.8 is complete: log scrolling is coalesced into native animation frames,
Clear cancels pending scrolling, and phone terminal height is bounded.
Phase 10.9 is complete: [CONTEXT.md](CONTEXT.md) is the concise current handoff;
[CONTEXT_HISTORY.md](docs/CONTEXT_HISTORY.md) preserves the complete prior state
and evidence byte for byte. No further implementation task is queued.
Broader model families,
quantized LoRA, large-download recovery, and portrait-quality benchmarking
remain outside the validated scope.

## Interface Contracts
### Client ↔ Server API Endpoints
- `GET /api/health` and `GET /api/system`:
  - Health plus timestamped host/device/readiness and resident-pipeline/active-job snapshots. Dashboard and System reuse these APIs; Dashboard does not add a polling loop.
- `GET /api/inputs/browse?folder=<subfolder>`:
  - Returns: `{"folders": [...], "images": [{"name": "...", "path": "...", "width": int, "height": int, "thumb_url": "..."}]}`
- `GET /api/inputs/thumbnail?path=<filepath>`:
  - Returns: cached JPEG/PNG thumbnail image (256px max dimension).
- `GET /api/models`:
  - Returns: `{"models": [{"id": "model_...", "name": "...", "path": "...", "type": "diffusers|safetensors|gguf", "is_cached": bool, "compatible": bool, "compatibility_reason": "...|null", "companion_path": "...|null"}]}`
- `POST /api/models/download`:
  - Body: `{"repo_id": "...", "filename": "...", "revision": "..."}`
  - Returns: `{"task_id": "...", "status": "queued"}`; `/api/models/download/progress/{task_id}` returns measured JSON progress or SSE with `?stream=true`. Unknown totals/percent are `null`.
- `POST /api/models/download/{task_id}/cancel` and `/retry`:
  - Cooperative cancellation at file boundaries; retry of failed/cancelled jobs returns a new task ID and reuses valid Hub cache files.
- `POST /api/models/upload`:
  - Form multipart upload: file (`.gguf` or `.safetensors`). Saves directly to `models/`.
  - The browser sends chunks with `chunk_index`, `total_chunks`, and `upload_id`; the server assembles a non-empty file with an allowed extension. Catalog inspection and the inference loader check compatibility separately; upload does not verify a supplied content checksum.
  - Existing destinations return HTTP 409 with rename/delete guidance. Both single and assembled uploads publish atomically using a hard link, so a concurrent upload cannot replace the first complete file. Temporary/assembled parts are removed on publication success or failure.
  - Browser auto-selection uses the final completed receipt's exact path to resolve a refreshed compatible catalog ID. Validation/run payloads use that ID; incompatible files, refresh failures, and upload conflicts preserve the prior valid selection with a visible explanation.
  - Returns: `{"success": true, "filename": "...", "path": "..."}`
- `DELETE /api/models/catalog/{model_id}`:
  - Removes a catalog model after active download/inference checks; unloads an idle resident pipeline and preserves Hub cache files still referenced by other selections or snapshots.
- `GET /api/loras`:
  - Returns valid and invalid `.safetensors` adapters discovered in the configured LoRA directory.
- `POST /api/loras/upload`:
  - Validates and atomically stores one LoRA SafeTensors file, then returns its selectable path and metadata.
- `DELETE /api/loras/{filename}`:
  - Removes one direct local adapter after checking queued/running use and unloading any idle resident pipeline that holds it; returns HTTP 409 for active use.
- `POST /api/config/validate`:
  - Body: JSON config payload; optional top-level `selected_model_id` selects a compatible downloaded checkpoint and overrides any nested source/base fields.
  - Returns: `{"valid": true}` or `{"valid": false, "errors": ["..."]}`
- `POST /api/run`:
  - Body: Complete config JSON payload + `demo_mode: bool`; the web UI sends top-level `selected_model_id`, while legacy direct-source clients may omit it.
  - Returns: `{"run_id": "...", "stream_url": "/api/run/{run_id}/stream"}`
- `GET /api/run/{run_id}/stream`:
  - SSE stream: `event: log`, `event: progress` for legacy step clients, `event: batch` for aggregate counts/stages/timing/per-item status, and `event: complete` with outputs, records, errors, and final batch summary.
- `GET /api/runs`:
  - Returns durable per-attempt records overlaid with current process job state, including readable summaries and output artifact lists. Dashboard, History, and Outputs share this payload.
- `GET /api/runs/{run_id}`:
  - Returns full `{run_id}.json` record.
- `DELETE /api/runs/{run_id}`:
  - Deletes a finished record and unshared output/comparison files after active-job and path-safety checks.
- `GET /api/outputs/{filename}`:
  - Serves output image or comparison image file.

## Code Layout
```
/mnt/lab/farzine/qwen_workflow_runner/
├── qwen_runner/           # Core model, scheduling, caching, inference, metrics, and persistence
│   ├── config.py
│   ├── runner.py
│   ├── backend.py
│   ├── resources.py       # Per-device persistent pipeline ownership and cleanup
│   ├── pipeline.py
│   └── ...
├── models/                # Local model weights directory
├── VALIDATION_MATRIX.md   # Final automated and live-hardware evidence
├── scripts/
│   └── validate_browser_production.js # Hardware-gated browser driver
├── ui/                    # Web Application Directory
│   ├── app.py             # Single-command startup entrypoint (`python app.py`)
│   ├── server.py          # FastAPI/Starlette application & routes
│   ├── runner_bridge.py   # Background execution manager, stdout capture, demo backend
│   ├── static/            # Static assets
│   │   ├── css/style.css  # Polished dark-theme responsive UI styles
│   │   └── js/app.js      # Vanilla ES6 SPA controller (modular components)
│   ├── templates/
│   │   └── index.html     # Semantic single-page HTML
│   ├── tests/             # API, DOM, accessibility, stress, and E2E suites
│   │   ├── test_backend.py
│   │   ├── test_frontend.py
│   │   ├── test_challenger_m2_node.js
│   │   ├── test_tier5_node_stress.js
│   │   └── e2e/           # Four-tier feature/boundary/pairwise/scenario tests
│   ├── README.md          # Startup documentation, dependencies, API docs
│   └── requirements.txt   # UI dependencies (fastapi, uvicorn, python-multipart, etc.)
```

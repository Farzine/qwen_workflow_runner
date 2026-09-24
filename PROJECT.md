# Project: Qwen Workflow Runner Web UI

## Architecture
The Qwen Workflow Runner Web UI is a high-performance, single-command web application located at `ui/` that wraps `qwen_runner` to provide browser-based execution for the Qwen Image 2.1 image-editing pipeline.

### System Architecture
```
Browser (Vanilla SPA HTML/CSS/JS)
  ├── 1. Input Browser: Folder tree, thumbnail grid, 1-10 drag/click ordered selector
  ├── 2. Parameter Form: ModelConfig, GenerationConfig, RuntimeConfig with live client validation
  ├── 3. Model & LoRA Selector: HF repo, local model upload, cached model dropdown, validated LoRA upload/selection
  ├── 4. System Configuration: live CPU/RAM/GPU inventory and dynamic production-device selection
  ├── 5. Run & Output Hub: Launch button, live SSE log/progress stream, output gallery, side-by-side comparison, JSON viewer/download, run history
  │
  ▼ [HTTP REST & SSE]
Backend Server (`ui/app.py` / `ui/server.py` using FastAPI / Starlette / ASGI)
  ├── Static & Thumbnail Service: Serves SPA, caches resized thumbnails for `/mnt/lab/farzine/inputs/`
  ├── Model Manager: HuggingFace Hub async downloader, chunked file upload to `models/`, cached scanner
  ├── Config Validator: Endpoints to validate Config against `qwen_runner.config.Config.validate()`
  ├── Background Execution Engine:
  │     ├── Task queue & thread worker invoking `qwen_runner.runner.run(config, backend_factory=...)`
  │     ├── Real-time stdout/stderr capture redirected to SSE event stream
  │     ├── Demo mode support: `DemoBackend` for synthetic fast execution with real outputs & JSON records
  │     └── Output manager: Serves PNG outputs, comparisons, and `{run_id}.json` records
```

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Input Directory Scanner | Scans `/mnt/lab/farzine/inputs/`, groups images by subfolder, filters `.DS_Store` | M1, M2 | R1, survey |
| 2 | Reference Image Ordering | Enforces 1–10 ordered image selection where slot 1 is canvas; rejects >10 with error | M1, M2 | R1, survey |
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
| 25 | Background Inference Runner | Non-blocking execution of `qwen_runner.runner.run(config)` | M1, M2 | R4, survey |
| 26 | Live Log & Progress Stream | Server-Sent Events stream of runner logs, status, and step progress | M1, M2 | R4, survey |
| 27 | Output Image Viewer | Displays output images with filename, dimensions, and SHA-256 hash badge | M1, M2 | R4, survey |
| 28 | Side-by-Side Comparison | Side-by-side comparison view between canvas image and generated output | M1, M2 | R4, survey |
| 29 | JSON Run Record Viewer | Expandable viewer and download button for `{run_id}.json` | M1, M2 | R4, survey |
| 30 | Run History Viewer | Current session history list with clickable past runs and status badges | M1, M2 | R4, survey |
| 31 | Demo Integrity Backend | Synthetic fast execution backend producing real images and records for demo mode | M1, M3 | ORIGINAL_REQUEST |
| 32 | Single-Command Startup | Single command `python app.py` starts server with auto-port fallback and docs | M3 | App Startup |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Backend API & Runner Integration | Fast backend server (`ui/server.py`, `ui/api.py`), endpoints for inputs scanning, thumbnail caching, model upload/download/caching, parameter validation via `Config.validate()`, background runner execution with SSE log streaming, and explicit synthetic demo mode | none | PLANNED |
| M2 | Modern Frontend Web UI | Single-page application (`ui/static/`, `ui/templates/index.html`) implementing R1 (Input browser, 1-10 selector, previews), R2 (Full parameter controls, range hints, validation error banners), R3 (Model selector, HF download progress, local upload, cached dropdown), R4 (Run controls, live console log stream, output viewer, comparison viewer, JSON inspector, run history) | M1 contracts | PLANNED |
| M3 | App Startup, CLI & Packaging | Entrypoint script (`ui/app.py`), single-command startup (`python app.py` from `ui/`), configurable port (default 7878 with automatic open port detection), comprehensive `ui/README.md`, dependencies specification | M1, M2 | PLANNED |
| M4 | E2E Verification & Adversarial Hardening | Phase 1: Verify 100% pass across all Tiers 1-4 E2E tests in test suite published by E2E Testing Track. Phase 2: Tier 5 adversarial testing & coverage hardening | M1, M2, M3, TEST_READY.md | PLANNED |

## Interface Contracts
### Client ↔ Server API Endpoints
- `GET /api/inputs/browse?folder=<subfolder>`:
  - Returns: `{"folders": [...], "images": [{"name": "...", "path": "...", "width": int, "height": int, "thumb_url": "..."}]}`
- `GET /api/inputs/thumbnail?path=<filepath>`:
  - Returns: cached JPEG/PNG thumbnail image (256px max dimension).
- `GET /api/models`:
  - Returns: `{"models": [{"name": "...", "path": "...", "type": "safetensors|gguf|hub", "is_cached": bool}]}`
- `POST /api/models/download`:
  - Body: `{"repo_id": "...", "filename": "...", "revision": "..."}`
  - Returns: `{"task_id": "..."}` (progress streamed via SSE `/api/models/download/progress/{task_id}`)
- `POST /api/models/upload`:
  - Form multipart upload: file (`.gguf` or `.safetensors`). Saves directly to `models/`.
  - Returns: `{"success": true, "filename": "...", "path": "..."}`
- `GET /api/loras`:
  - Returns valid and invalid `.safetensors` adapters discovered in the configured LoRA directory.
- `POST /api/loras/upload`:
  - Validates and atomically stores one LoRA SafeTensors file, then returns its selectable path and metadata.
- `POST /api/config/validate`:
  - Body: JSON config payload.
  - Returns: `{"valid": true}` or `{"valid": false, "errors": ["..."]}`
- `POST /api/run`:
  - Body: Complete config JSON payload + `demo_mode: bool`.
  - Returns: `{"run_id": "...", "stream_url": "/api/run/{run_id}/stream"}`
- `GET /api/run/{run_id}/stream`:
  - SSE stream: `event: log`, `data: {"text": "..."}`, `event: progress`, `data: {"step": int, "total": int}`, `event: complete`, `data: {...}`
- `GET /api/runs`:
  - Returns list of completed/active run records in current session.
- `GET /api/runs/{run_id}`:
  - Returns full `{run_id}.json` record.
- `GET /api/outputs/{filename}`:
  - Serves output image or comparison image file.

## Code Layout
```
/mnt/lab/farzine/qwen_workflow_runner/
├── qwen_runner/           # Core library (unmodified reference implementation)
│   ├── config.py
│   ├── runner.py
│   ├── backend.py
│   ├── pipeline.py
│   └── ...
├── models/                # Local model weights directory
├── ui/                    # Web Application Directory
│   ├── app.py             # Single-command startup entrypoint (`python app.py`)
│   ├── server.py          # FastAPI/Starlette application & routes
│   ├── runner_bridge.py   # Background execution manager, stdout capture, demo backend
│   ├── static/            # Static assets
│   │   ├── css/style.css  # Polished dark-theme responsive UI styles
│   │   └── js/app.js      # Vanilla ES6 SPA controller (modular components)
│   ├── templates/
│   │   └── index.html     # Semantic single-page HTML
│   ├── tests/             # E2E test suite (owned by E2E Testing Track)
│   │   ├── run_tests.py   # Test runner
│   │   ├── test_tier1.py  # Tier 1: Feature coverage
│   │   ├── test_tier2.py  # Tier 2: Boundary & corner cases
│   │   ├── test_tier3.py  # Tier 3: Pairwise combinations
│   │   └── test_tier4.py  # Tier 4: Real-world application scenarios
│   ├── README.md          # Startup documentation, dependencies, API docs
│   └── requirements.txt   # UI dependencies (fastapi, uvicorn, python-multipart, etc.)
```

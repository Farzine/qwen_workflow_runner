# Original User Request

## 2026-09-22T13:33:33Z

Build a polished, production-ready web application UI for the Qwen Image 2.1 workflow runner
located at `/mnt/lab/farzine/qwen_workflow_runner`. The app must let a user configure and
launch the full image-editing pipeline entirely through the browser — no terminal editing required.

Working directory: `/mnt/lab/farzine/qwen_workflow_runner/ui/`
Integrity mode: demo

---

## Requirements

### R1. Input Image Browser
The UI must scan `/mnt/lab/farzine/inputs/` and display its subfolders and image files in a
browsable panel. The user selects up to 10 ordered reference images (matching the runner's
1–10 image constraint). The selection order matters: image 1 is the editing canvas, image 2+
provide references. Selected images must be previewed before running.

### R2. Full Parameter Customization
The UI must expose all configurable parameters from `qwen_runner/config.py` through
appropriate controls:

- **Generation:** prompt, negative prompt, steps (1–10000), CFG, seed, strength (0–1],
  resolution (0 or multiples of 32 up to 4096), custom_size toggle with width/height fields,
  batch_size, sampler (euler), scheduler (simple/normal), shift, KV cache toggle,
  kv_cache_device (auto/gpu/cpu), kv_cache_reserve_gib, reference_mode (rgb/rgba).
- **Runtime:** device, dtype (bfloat16/float16/float32), offload mode (none/model/sequential),
  vae_tiling, repeats, warmup_runs, increment_seed, output_dir, filename_prefix, save_comparison.
- Parameters must show validation constraints (e.g., range hints) and fail gracefully with
  clear user-facing error messages when invalid values are submitted.

### R3. Model Selection and Download
The UI must provide a model selector with three modes:
1. **HuggingFace repo:** Text field where the user types a repo ID (e.g. `Qwen/Qwen-Image-2.1`)
   or full HF URL. If the model is not in the local cache (`models/`), the UI triggers a download
   with a live progress indicator. Already-cached models are flagged as available offline.
2. **Upload a local file:** File upload control that accepts `.gguf` and `.safetensors` files and
   places them in the local models folder.
3. **Dropdown of cached/discovered models:** Lists already-downloaded models and local files in
   `models/` for quick reuse.
An optional GGUF filename field (for selecting a specific quantization variant) must be available
when a GGUF repo is selected.

### R4. Run Management and Output Viewer
The UI must have a **Run** button that launches `qwen_runner.runner.run(config)` as a background
task, streaming live logs/status to the UI. After each run:
- Output images are displayed in the UI with their filename, dimensions, and SHA-256 hash.
- A side-by-side comparison image (if `save_comparison=True`) is shown.
- The JSON run record is accessible (expandable/downloadable) from the UI.
- Run history for the current session is shown, and the user can click past runs to review outputs.

---

## Acceptance Criteria

### Input Browser
- [ ] Scanning `/mnt/lab/farzine/inputs/` discovers all subfolders and image files within them.
- [ ] User can select 1–10 images; attempting more than 10 is blocked with an error message.
- [ ] Selected images render as thumbnails in selection order before running.

### Parameter Controls
- [ ] Every field in `ModelConfig`, `GenerationConfig`, and `RuntimeConfig` is exposed in the UI.
- [ ] Submitting a configuration that fails `Config.validate()` shows the validation error message
  to the user without crashing the server.
- [ ] Constraints (ranges, allowed values) are visible on the form (e.g., placeholder text or help text).

### Model Management
- [ ] Entering a HuggingFace repo ID and clicking "Download" starts a download; a progress
  indicator updates while the download runs.
- [ ] Uploading a `.gguf` or `.safetensors` file from the browser saves it to the models directory
  and makes it immediately available in the dropdown.
- [ ] The dropdown correctly lists all models already present in `models/`.

### Run and Output
- [ ] Clicking Run starts inference; live status/log output is visible in the UI (not just after
  completion).
- [ ] After a successful run, at least one output image is displayed in the browser.
- [ ] The JSON run record can be viewed or downloaded from the UI.
- [ ] A failed run shows the error message and traceback in the UI without crashing the server.

### App Startup
- [ ] Running a single command from the `ui/` directory starts the web server.
- [ ] The README or a `ui/README.md` documents the startup command and any additional dependencies.

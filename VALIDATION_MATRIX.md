# Validation Matrix

This matrix records Phase 9.8c2 GGUF, Phase 9.8c1 download, and Phase 9.8b regression/hardware evidence and preserves the
historical Phase 8 production validation. Automated checks use temporary files and synthetic or tiny models
where loading the 33 GB pretrained checkpoint would add no useful coverage.
Hardware rows identify the live RTX A6000 checks separately.

## Functional matrix

| Area | Scenario | Result | Evidence |
|---|---|---:|---|
| Input | Empty selection | Pass | Browser state-machine tests block submission and show the actionable 1–10 input error. API/config tests reject an empty production request. |
| Input | One image | Pass | Core, API, SSE, history, and prior full-model production runs; current regression suite. |
| Input | Multiple ordered images | Pass | Phase 8 browser-started full-model batch processed `img_1.jpeg` and `img_10.jpg` independently, in order, with two output records. |
| Input | Invalid/empty/mismatched upload | Pass | API tests cover corrupt bytes, empty files, unsupported formats, extension/content mismatch, traversal-like names, atomic rejection, count, byte, and pixel limits. |
| Input | Upload, preview, reorder, remove | Pass | Python DOM/accessibility tests and the current Node state-machine harness cover role-aware multi-upload, previews, order, removal, clearing, and the ten-input boundary. |
| Reference | No shared reference | Pass | References are optional; validated by config/core/API tests and earlier production inference. |
| Reference | One shared reference | Pass | Phase 8 browser batch applied `img_11.jpg` after each current process input. Both durable records preserve the two-path conditioning sequence. |
| Reference | Multiple ordered references | Pass | Core/API transport tests and earlier bounded two-reference full-model runs preserve order and hashes. |
| Reference | Missing/invalid path | Pass | Config, runner, and API suites return explicit image-loading errors without silently substituting another image. |
| LoRA | No adapter | Pass | Phase 8 full-model browser batch records `enabled: false`, `applied: false`, and completes normally. |
| LoRA | Existing adapter selection | Pass | Catalog/API/DOM/Node tests verify discovery, selection, strength, clear state, and confined paths. |
| LoRA | Uploaded adapter | Pass | Streamed atomic upload tests verify valid SafeTensors storage, catalog refresh, and auto-selection. |
| LoRA | Invalid/incompatible adapter | Pass | Header/key validation rejects invalid files; the tiny-transformer lifecycle test verifies an incompatible target produces an actionable load failure and cleanup. |
| LoRA | Adapter actually changes inference | Pass | A real tiny Qwen Image 2.1 transformer test loads the adapter through Diffusers/PEFT, verifies activation/scale/hash, observes changed output, and verifies unload/replacement. |
| GPU | Detection and inventory | Pass | `/api/system` reports two RTX A6000 GPUs, live memory, CUDA 12.6, PyTorch `2.11.0+cu126`, and readiness. |
| GPU | Manual device selection | Pass | Both `cuda:0` and `cuda:1` completed prior BF16 allocation/production checks; the Phase 8 browser selected `cuda:0`, which both output records identify. |
| GPU | Invalid device/configuration | Pass | System/config tests cover unavailable indices, CPU precision/offload normalization, and unsupported combinations. |
| Inference | Real transformation | Pass | Phase 8 used `WorkflowQwenImage21Pipeline`, BF16, model offload, four steps, 512 reference resolution, and a 256×256 canvas. Normalized source/output comparison changed 97.47% and 98.30% of pixels above a value of 10. Visual inspection confirmed the requested watercolor edit. |
| Output | Save, hash, comparison, record | Pass | Both PNG hashes match their JSON records; both comparison files and JSON records exist and are served by their API endpoints. |
| UI | SSE progress and completion | Pass | The live browser reached 100% and `Completed`; terminal output contains the submitted job ID, SSE connection, model load, both four-step progress sequences, and both success records. |
| UI | Result and history display | Pass | The browser rendered two loaded batch thumbnails, the primary output, working before/after comparison sources, and refreshed history. |
| UI | Loading, error, empty, partial success | Pass | Full UI/API suite and Node stress harness cover busy state, progress, empty states, validation/setup errors, and retention of successful artifacts on partial failure. |
| UI | Desktop, tablet, and phone | Pass | Live Chrome checks at 1440×900, 900×800, and 390×844 cover section navigation, tablet drawer, phone flow, help-card placement, and input/config/result access. |
| UI | Long names and many items | Pass | DOM, CSS, boundary, and stress tests cover ellipsis/title preservation, bounded folder lists, ten inputs, nine references, and 30 history items. |
| Help | All meaningful parameters | Pass | Exactly 41 runtime-generated help controls have valid targets, implementation-derived content, keyboard focus/Escape behavior, click/touch handling, and responsive placement. |

## Phase 8 production browser run

- Aggregate job: `20260924T112147_5b0c9daa4c_run_000`
- Per-input records: `20260924T112147_5b0c9daa4c_run_000` and
  `20260924T112147_5b0c9daa4c_run_001`
- Inputs: `/mnt/lab/farzine/inputs/Child/img_1.jpeg` and
  `/mnt/lab/farzine/inputs/Child/img_10.jpg`
- Shared reference: `/mnt/lab/farzine/inputs/Child/img_11.jpg`
- Runtime: `cuda:0`, BF16, model offload, production backend, cached revision
  `790c92633540aa0cb11d9abf19eb46d861714758`
- Generation: four Euler/simple steps, resolution 512 for conditioning,
  custom 256×256 output, fixed seed, KV cache enabled
- Inference time: 33.97 seconds for the first input and 16.24 seconds for the
  second with one shared model load
- Peak PyTorch allocation: about 18.81 GB per record
- Browser result: `Completed`, 100%, two loaded outputs, one reference,
  comparison view populated, and history refreshed

The reusable hardware-gated driver is
`scripts/validate_browser_production.js`. It deliberately uses browser controls
instead of calling `/api/run` directly.

## Phase 9 management and navigation evidence

| Area | Scenario | Evidence and scope |
| --- | --- | --- |
| Resources | Compatible reuse, switching, concurrency, shutdown | Core/API lease and lifecycle tests; Phase 9.8b repeated two production browser jobs (four outputs) through one load, verified Dashboard/System resident resources and explicit server shutdown cleanup. |
| Model selection | Catalog ID is authoritative | Catalog/API/Node tests reject stale/incompatible entries and advanced-source overrides; full-model hardware checks plus Phase 9.8c2 browser-applied GGUF selection, exact loading, replacement, and reuse on `cuda:0`. |
| Downloads | Known/unknown totals, retry/cancel/error | Fake-adapter regressions plus Phase 9.8c1 real pinned HTTP/Xet transfers, byte callbacks, cancellation, retry, complete-cache hits, source hashes, SSE, and incompatible-fixture catalog discovery. No large-model transfer or interrupted-network recovery is claimed. |
| Deletion | Models, adapters, and finished runs | Temporary-storage API tests cover actual cleanup, shared files, active-job/lease/download conflicts, and path safety; browser tests cover confirmation, state refresh, and whole-run output removal. Production assets were not deleted. |
| Records | Common readable summary | Core/API tests cover durable success/failure/setup records, legacy projection, file metadata, and explicit unavailable values. |
| Batch | Counts, stages, ETA, errors, replay | Core/API callbacks, SSE replay/partial failure/warmups, Node tests, and browser synthetic batches. No automatic inference retry or model-operation cancellation is claimed. |
| Pages | Eight routes at three widths | Phase 9.8a reusable `--navigation-only` driver passed all 24 route/width combinations at 1440, 900, and 390px, preserving selection and showing no horizontal overflow. |
| Navigation | Active job survives page changes | Phase 9.8a two-input CPU demo batch navigated through all eight destinations and completed with two loaded outputs and unchanged prompt/device. Earlier page slices also tested partial/failed batches. |
| Dashboard | Errors and recovery | Browser-only health/system/history 503 responses produced readable failures; restoring real local responses recovered via Refresh. Inventory is a snapshot; activity monitors are local to the tab. |
| Outputs | Every recorded image | Earlier live Chrome tests covered 33 artifacts, exact non-first-image selection, comparison/download/input association, lazy/missing previews, keyboard activation, and confirmed temporary cleanup. |
| Browser checker | Evidence cannot pass with missing/demo records | Phase 9.8a `--collect-existing` rejected an empty injected history and a real synthetic diagnostic batch. Image checks target the nested images inside native thumbnail buttons. Production records are matched through listed output filenames and checked against selected model/device and effective pipeline/device. |

No full pretrained inference was rerun in Phase 9.8a. Its browser batch is
explicitly synthetic, and error/empty responses were injected only in the
diagnostic tab. The production checker now closes its CDP connection on failure.

```bash
# Start a local UI plus Chrome --remote-debugging-port=9234 first.
node scripts/validate_browser_production.js http://127.0.0.1:9234 http://127.0.0.1:7899 --navigation-only

# Hardware-gated: needs three Child images and a compatible downloaded model.
# Choose an available GPU; this submits a real two-input, one-reference job.
node scripts/validate_browser_production.js http://127.0.0.1:9234 http://127.0.0.1:7899 --device=cuda:1 --output-dir=/tmp/qwen-browser-check/outputs

# Inspect a displayed finished production batch without another submission.
node scripts/validate_browser_production.js http://127.0.0.1:9234 http://127.0.0.1:7899 --collect-existing
```

## Phase 9.8b production browser/cache validation

Two complete browser-started batches ran on `cuda:1` using selected downloaded
model `model_4ff66ef0ec9f18e2d3e2` and cached revision `790c926...` after the
final task pages were installed. Both used the Phase 8 ordered Child inputs,
shared reference, BF16/model offload, four steps, 512 conditioning resolution,
and 256×256 output. All files were isolated under
`/tmp/qwen-phase98b.AJEcJM/outputs`; production assets were preserved.

| Batch | Records | Inference seconds | Cache |
| --- | --- | --- | --- |
| First | `20260928T081020_047d344da5_run_000`, `_run_001` | 25.78 / 25.81 | One load; reuse count 0 |
| Compatible second | `20260928T081311_4d102d5929_run_000`, `_run_001` | 25.27 / 25.87 | Same loaded timestamp; one load; reuse count 1 |

- Both browsers reached `Completed`, 100%, two loaded output images, populated
  comparisons, and refreshed history. `--collect-existing` accepted the real
  completed batch without another submission.
- Disk JSON equals API records; PNG SHA-256 matches metadata; served output and
  comparison bytes equal saved files. All four records preserve the selected
  model, requested/effective device, no-LoRA state, and `[current_input, reference]`.
- The fixed-seed repeated outputs have identical hashes across batches. Source
  comparison measured MAE 64.01/60.13 and RMSE 81.09/73.07 (0–255), with
  97.47%/98.30% of pixels changing above 10. Browser screenshot inspection
  confirmed the requested watercolor edit.
- Dashboard/System show the actual resident pipeline, model, device, no loaded
  LoRA, zero active leases, and correct counters. Peak PyTorch allocation is
  about 18.81 GB (17.52 GiB), distinct from total device use.
- Explicit SIGINT completed FastAPI shutdown, disabled new leases, and emptied
  the pipeline slot without error. While the wrapper was still alive it measured
  9,568,256 allocated / 29,360,128 reserved CUDA bytes; the server PID was absent
  from host GPU process listings after exit. Its context was released. Temporary
  Chrome was closed. Snapshot and screenshots are under `/tmp/qwen-phase98b.AJEcJM`.

Initial diagnostic attempts encountered a CUDA context error and a partial
batch after another process consumed about 40 GB on GPU 1. The next compatible
request exposed a real mixed CPU/GPU text-encoder failure: interrupted component
transfer skipped the normal successful-call offload cleanup. The shared backend
now invokes Diffusers' existing `maybe_free_model_hooks()` on inference failure,
retains the original exception, and logs cleanup errors. A regression test and
real tiny CUDA pipeline with injected interrupted transfer verified reset and
subsequent generation. The full-model runs above completed after restarting
with the fix; no recovery from a second naturally occurring OOM is claimed.
The first diagnostic server exited 137 before graceful shutdown; its cause is
unconfirmed. Other host processes were not stopped.

The checker now accepts an explicit output directory and reports current
per-item/terminal errors immediately for failed or partial batches, avoiding
stale validation banners and waiting for a nonexistent second output.

## Final regression commands

```bash
.venv/bin/python -m pytest -q tests
timeout 300 .venv/bin/python -m pytest -q ui/tests
node ui/tests/test_challenger_m2_node.js
node ui/tests/test_tier5_node_stress.js
.venv/bin/python -m compileall -q qwen_runner ui run.py benchmark.py scripts
.venv/bin/python -m pip check
node --check ui/static/js/app.js
node --check scripts/validate_browser_production.js
git diff --check
```

Phase 9.8b results (2026-09-28): 42 core tests plus 8 parameterized subtests,
438 UI/API/E2E tests, and Node harnesses 49/49 and 15/15 passed. `pip check`,
JavaScript syntax, compilation, and diff checks passed. Two known
Starlette/AnyIO deprecation warnings remain in the UI suite.

Historical Phase 8 results were 31 core tests plus 8 subtests, 417 UI tests,
and Node harnesses 33/33 and 15/15.

## Phase 9.8c1 live Hub/API validation

The opt-in `scripts/validate_hub_download.py` exercises actual download workers
and Hub HTTP/Xet functions through the real API with isolated temporary storage.
It checks declared sizes before starting, pins commits, caps total selected
files at 1 MiB, and has a documented 120-second command timeout. No tensors are
loaded. These deliberately incompatible fixtures cannot be selected for Qwen
image inference.

| Transport | Public fixture / pinned revision | File | Bytes |
| --- | --- | --- | ---: |
| HTTP | `hf-internal-testing/tiny-random-GPT2Model` / `d6694b0d8fe17978761c9305dc151780506b192e` | `tokenizer.json` | 31,087 |
| Xet | `hf-internal-testing/tiny-random-gpt2` / `71034c5d8bde858ff824298bdedc65515b97d2b9` | `model.safetensors` | 453,864 |

- Fresh storage performed one actual HTTP call and one actual Xet call; byte
  callbacks matched file sizes, included positive speed and ETA, and stopped
  at 99.9% until successful manifest verification/terminal completion.
- Cancellation used the real cancel endpoint from a real Xet byte callback;
  it returned `cancelled` at 99.9%, with no output path or completed manifest.
  The small file had already materialized by that callback. This proves
  cooperative cancellation before publication, not mid-file interruption.
- Retry received a new task ID and completed using the existing Hub file.
  Subsequent completed-manifest hits had `cache_hit: true`, no speed estimate,
  and no additional HTTP/Xet file-transfer calls.
- Source verification matched Git blob SHA-1 for the text file and Hub LFS
  SHA-256 for SafeTensors. Saved SHA-256 values are `cb95c4e3...` and `8111d5af...`.
- The missing-file request and its retry failed with readable errors and unknown
  percentage; terminal SSE was verified for completed, cancelled, and failed
  jobs. Both completed files appeared in `/api/models` as incompatible entries.
- Final API evidence: `/tmp/qwen-hub-validation-hbikkfmd/evidence.json` and
  `events.jsonl`; first pass: `/tmp/qwen-hub-validation-cax0tm3q`.
- Actual Models page on isolated server 7897 completed a fresh Xet download,
  displayed 443.2 KB / 443.2 KB, 1/1 files, 0 remaining, and 100%. Its catalog
  option was disabled as incompatible. Missing-file failure displayed `Size
  unknown`, readable error, and Retry; captured POST receipts prove retry used
  a new ID. Browser saved bytes match the same Hub hash. Desktop 1440px and
  phone 390px had no horizontal overflow; phone Retry was hit-tested after
  four-second notifications dismissed. Screenshots/evidence are under the first
  evidence root. The first diagnostic browser attempt clicked before startup
  listeners were initialized; correcting its initialization wait fixed the driver.
- Focused existing download regression suite: 5 passed, two known deprecation
  warnings. Full inference/UI regression from Phase 9.8b remains unchanged.

```bash
timeout 120 .venv/bin/python scripts/validate_hub_download.py
```

This bounded check does not establish large-checkpoint throughput, proxy/offline
operation, rate-limit behavior, or recovery from an actual interrupted network
connection. Speed remains reconstructed-file bytes rather than exact wire bytes.

## Phase 9.8c2 selected-ID GGUF browser validation

Two offline browser batches used catalog ID `model_5f31ccf7dbc4c402207d`,
`abenzerps/Qwen-Image-2.1-Uncensored-GGUF` revision
`40319fb15542f0ad22921e0124a191a8a935a60a`, and the cached
`qwen-image-2.1-UC-Q4_0.gguf` file (4,151,573,280 bytes). The full Qwen snapshot
`790c926...` supplied text encoder, processor, VAE, and transformer configuration;
its transformer weights were overridden by the GGUF. Runtime was `cuda:0`,
BF16/model offload, four steps, 512 conditioning resolution, and 256×256 output,
with the same ordered two Child inputs and separate shared reference as above.
No adapter was used and no model download occurred.

| Batch | Records | Inference seconds | Cache |
| --- | --- | --- | --- |
| First GGUF | `20260928T091951_2dc4c72ebe_run_000`, `_run_001` | 20.36 / 18.40 | Replaced prior full pipeline; cumulative load count 2, reuse 0 |
| Compatible GGUF repeat | `20260928T092108_d9a3657614_run_000`, `_run_001` | 19.13 / 19.02 | Same loaded timestamp; load count 2, reuse 1 |

- Strict loading accepted all 297 names/shapes: 68 BF16, 197 Q4_0, and 32 Q4_1
  tensors. Records identify packed storage, actual transformer/pipeline classes,
  selected model/revision, companion paths, and effective GPU.
- Both batches reached Completed/100%, with loaded thumbnails, comparisons,
  and refreshed history. Disk records equal API detail; saved PNG hashes and
  served output/comparison bytes match. Repeated fixed-seed hashes match; GGUF
  output hashes differ from the preceding full-model diagnostic.
- Source comparison measured MAE 65.76/56.82, RMSE 82.81/70.24 (0–255), and
  96.62%/97.79% changed pixels above 10. The Batch screenshot was visually
  inspected and shows the watercolor transformation.
- Dashboard/System show the GGUF source with the correct resident pipeline,
  device, no LoRA, zero active leases, and expected replacement/reuse counters.
  Peak PyTorch allocation remains about 18.81 GB (17.52 GiB); quantizing the
  transformer does not reduce the separate text encoder's peak here.
- SIGINT completed server shutdown and emptied the slot; the wrapper retained
  9,568,256 allocated / 29,360,128 reserved bytes before exit. Server PID 1869266
  and Chrome PID 1869996 exited and disappeared from host GPU listings.
- Existing GGUF runtime tests: 2 passed. Selected-model API tests: 3 passed,
  two known deprecation warnings. JavaScript syntax and diff checks passed.
  No production loader/UI change was needed; prior full regression remains valid.

The first diagnostic changed the dropdown without clicking its existing Use
button and submitted the default full model. The checker rejected the model-ID
mismatch; this is not GGUF evidence. The corrected `--model-id` option clicks
Use and checks every durable record against the requested ID. `--collect-existing`
passed for the completed GGUF batch; a missing-ID request failed before inference.
Evidence, four screenshots per batch, artifacts, and shutdown measurements are
under `/tmp/qwen-gguf-validation-9znq346l`; all generated files were isolated there.
Other host processes and production assets were preserved. This establishes this
checkpoint's compatibility, not arbitrary GGUF/model-family or adapter support.

```bash
# Requires a production UI and Chrome debugger; choose the currently free GPU.
timeout 360 node scripts/validate_browser_production.js http://127.0.0.1:9237 http://127.0.0.1:7896 --device=cuda:0 --model-id=model_5f31ccf7dbc4c402207d --output-dir=/tmp/qwen-gguf-check/outputs
```

## Outstanding bounded validation

- Validate a compatible user adapter against the full pretrained model once an
  asset is available; the tiny-transformer lifecycle test does not prove its
  model-specific visual quality.

## Asset-dependent limitation

No compatible user LoRA is installed in `models/loras/`, so the 33 GB
pretrained checkpoint was not run with an adapter during Phase 8. Adapter
application itself is covered by the real tiny-Qwen transformer test, including
weight activation, output effect, strength, hash metadata, unload, replacement,
and incompatible-target diagnostics. A user-supplied production adapter still
needs model-specific visual quality assessment because a valid SafeTensors
header cannot establish architecture or training compatibility.

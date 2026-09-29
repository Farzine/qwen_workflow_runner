# Validation Matrix

This matrix records Phase 9.8c3 pretrained LoRA, Phase 9.8c2 GGUF, Phase 9.8c1 download, and Phase 9.8b evidence and preserves the
historical Phase 8 production validation. Scoped checks use temporary files and synthetic or tiny models
where loading the 33 GB pretrained checkpoint would add no useful coverage. A legacy
stress-test output-isolation gap discovered in Phase 10.1 is fixed by Phase 10.2 below.
Hardware rows identify the live RTX A6000 checks separately.

Phase 10.1 upload collision safety and Phase 9.8d stabilization/documentation
review are complete (2026-09-28). The model-upload overwrite defect found during
the review is fixed; remaining follow-up and scope limits are recorded below.

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
| LoRA | User adapter on full pretrained model | Pass | Phase 9.8c3 real browser batches verify existing/uploaded adapter application, output effect against controls, hashes/strength/device, cached reuse, and removal restoring exact control hashes. |
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

## Phase 9.8c3 pretrained LoRA validation

The user supplied `models/loras/`, now containing
`bfs_head_v1.1_qwen_2.1.safetensors` (260,096,144 bytes, SHA-256
`d1d748d5601077f3b6d05766f6823510e901970d916afa404a97e85dc92fa88e`).
Its AI-Toolkit 0.13.21 metadata provides a head-swap prompt and 352 tensors.
Preflight identified a real loader gap: fused `img_mlp.gate_up` targets are absent
from Diffusers' split MLP. The shared pipeline now retains upstream key/alpha
conversion, then splits B into gate/up output rows with shared A. The 384
converted tensors match actual full-model targets; the original file is unchanged.
Numerical tests compare the loaded split MLP with the original fused update,
check down/up alpha scaling, and reject missing, odd-row, rank-mismatched, and
colliding fused/split pairs. Existing standard-adapter behavior still passes.

Four actual browser batches used full model ID `model_4ff66ef0ec9f18e2d3e2`,
revision `790c926...`, `cuda:0`, BF16/model offload, four steps, CFG/strength 1,
seed `1070478148268574`, 512 conditioning resolution, and 256×256 output. Each
processed the two Child inputs with separate `img_11.jpg` reference and the
header's `head_swap` prompt. Server, LoRA copies/uploads, outputs, and evidence
were isolated under `/tmp/qwen-lora-validation-hyd258je`; no model was downloaded.

| Batch | Records | Inference seconds | Base cache |
| --- | --- | --- | --- |
| No adapter control | `20260928T095655_a10f4ae333_run_000`, `_run_001` | 27.98 / 27.17 | One load, reuse 0 |
| Existing adapter, scale 1 | `20260928T100137_a67e9b1f27_run_000`, `_run_001` | 30.48 / 26.33 | Same load, reuse 1 |
| Browser-uploaded copy, scale 1 | `20260928T100446_6b0b1d5af5_run_000`, `_run_001` | 28.29 / 28.12 | Same load, reuse 2 |
| Adapter cleared | `20260928T100632_85f21a2bc4_run_000`, `_run_001` | 26.52 / 27.12 | Same load, reuse 3 |

- All eight disk records equal API detail; saved PNG hashes and served
  output/comparison bytes match. Requested/effective model, GPU, prompt, and
  ordered conditioning agree. All batches reached Completed/100%, with loaded
  results/comparisons and refreshed history.
- Existing/uploaded adapters record the correct SHA-256, active
  `qwen_workflow_lora`, strength 1, and unfused application. Uploaded-copy outputs
  match the existing adapter exactly; clearing it restores both control hashes.
- LoRA/control MAE is 42.1049/40.7762 and RMSE 59.5120/66.8530 (0–255);
  94.5847%/83.6044% of pixels changed above 10. The Batch screenshot shows a
  visible head change consistent with the prompt. This small four-step check
  establishes application and effect, not exact identity/background preservation
  or broad portrait-quality performance.
- Real Chrome file-input upload produced collision-safe
  `bfs_head_v1.1_qwen_2.1_9a94a61b5e.safetensors`, retained the original filename,
  matched source size/hash, refreshed the catalog, and selected the uploaded path.
  Desktop 1440px and phone 390px had no horizontal overflow; the phone upload
  screenshot was visually inspected. Dashboard/System snapshots confirm each
  adapter transition with no base reload, zero idle leases, and no error.
- Peak PyTorch GPU allocation was 18,819,107,328 bytes; sampled process RSS
  peaked at 35,158,933,504 bytes. Shutdown SIGINT emptied the slot and disabled
  leases, leaving 9,568,256 allocated / 29,360,128 reserved bytes in the wrapper
  before exit. Server PID 1975034 and Chrome PID 1975299 exited and were absent
  from host GPU listings. Competing processes were preserved.
- Core: 43 passed plus 13 subtests; UI/API/E2E: 438 passed with two known
  deprecation warnings; Node: 49/49 and 15/15. After the final alpha-scaling
  assertion, its focused test passed again with five subtests. Compilation,
  `pip check`, JavaScript syntax, and diff checks passed.

The reusable browser checker now accepts `--lora-path`, `--lora-scale`, and
`--prompt-file`; it verifies requested/selected/applied adapter identity and
strength along with model/device records. Production UI controls are unchanged.
Evidence includes `baseline/existing/uploaded/cleared-browser.json`, resource
snapshots/screenshots, `upload.json`, `artifacts.json`, and `shutdown.json`.

## Phase 9.8d stabilization review

- Resumed with a clean working tree at `5c8d379`, which commits all nine Phase
  9.8c3 paths. Reviewed the shared LoRA override, backend callers, installed
  Diffusers loading/return contract, numerical regression, browser flags, and
  primary-source attribution already recorded in the porting notes.
- Rechecked retained full-model, GGUF, Hub, and LoRA evidence JSON. LoRA
  artifacts retain eight outputs, adapter/control comparisons, one base load
  and three reuses, an empty shutdown slot, and the 352-to-384 tensor preflight.
  These are previous live results, not new GPU or network runs.
- Focused LoRA regression: 2 tests and 5 subtests passed. Full Phase 9.8c3
  regressions remain the latest broad results: 43 core tests/13 subtests, 438
  UI/API/E2E tests, Node 49/49 and 15/15. No production code changed in this slice.
- Corrected upload checksum/process-isolation claims and reconciled milestone,
  supported-scope, and continuation state. Documented the browser validator's
  native `fetch`/`WebSocket` requirement (local Node 22.22.0).
- Retained-artifact hashes/identity/control/shutdown assertions, local Markdown
  links, both JavaScript syntax checks, dependency consistency, and final diff
  whitespace checks passed. Broad suites were not repeated for documentation edits.
- A direct call to each real upload route branch, using in-memory multipart
  files and isolated temporary storage, accepted arbitrary non-empty `.gguf`
  bytes and replaced a pre-existing same-name file. This is an expected
  diagnostic reproduction of a defect, not a passing safety check. Source
  inspection shows no bridge/lease guard on replacement. No user asset changed.

## Phase 10.1 model upload collision safety

Both upload branches now reject existing destinations with HTTP 409 and clear
rename/delete guidance. A shared publication step uses `os.link` on a completely
written temporary file; the destination cannot be replaced even if another
upload wins after the initial check. Logical destination paths are retained so
dangling symlinks count as occupied instead of redirecting a new upload.
Publication/assembly success and failure clean temporary files and relevant
parts. No active resource has to be unloaded because uploads never replace it.
The existing UI preserves selection, stops remaining chunks, displays server
details, and now labels the operation `Upload failed` on failure.

- Six new real API tests cover single/chunk uploads, queued/running/idle source
  preservation, fresh catalog discovery, late collisions, denied publication,
  cleanup, unrelated part preservation, dangling symlinks, 244-character filenames
  with short owned stdlib temporary paths, and two threads
  reaching atomic publication together. Each race has one 200 and one 409;
  stored bytes exactly match the complete winning upload.
- Initial targeted upload tests: 5 passed. After the sixth long-filename test
  and owned temporary path refinement, full UI/API/E2E suite: 444 passed in 24.13
  seconds with the two known deprecation warnings. Node frontend: 50/50; stress:
  15/15. The new Node case exercises actual client/controller code against 409
  response data, verifies unchanged selection, stopped chunks, visible error,
  no catalog refresh on failure, and refresh after successful upload.
- Python compilation, JavaScript syntax, and diff whitespace checks passed.
  Core/GPU inference was not rerun because loading/generation code is unchanged.
  New upload tests and browser fixtures use temporary assets. The broad legacy
  suite also created synthetic demo records in repository `outputs/`; see below.
  A temporary Hub permissions diagnostic was non-failing.
- Real Chrome native file-input uploads on a temporary offline server passed at
  1440px and 390px: visible rename/delete errors, `Upload failed`, 0% after
  conflict, and no horizontal overflow. A new 6,300,000-byte file completed in
  two chunks, refreshed the catalog, cleared the error, and reached 100%.
  Actual response statuses were 409/409/200/200; existing bytes were preserved,
  new bytes matched the source hash, and no temporary/part files remained.
  These deliberately invalid GGUF fixtures were stored and listed, not used for
  inference. Screenshots were visually inspected. Evidence and clean shutdown
  are under `/tmp/qwen-model-upload-browser-18sjbgl2`; server PID 2128398 and
  Chrome PID 2128399 both exited 0. Earlier driver attempts timed out after
  desktop capture or reused a busy port; fresh ports and bounded debugger calls
  fixed the diagnostic. No user model/input/output file was changed.

## Phase 10.2 UI test storage isolation

Completed 2026-09-29 (Asia/Dhaka). The old workflow stress tests submitted demo
jobs to literal `outputs`, used an external input, and searched existing history.
Their SHA check could skip or perform no assertion because durable outputs use
`path`, whereas catalog/listing entries include `filename`.

- Each stress case now uses a generated temporary input, explicit temporary
  output/model paths, an owned runner, and isolated getter/environment/app-state
  history roots. It starts with empty history. Twenty test-owned records exercise
  scaling; the byte/hash test always creates and verifies its own saved output.
- Bounded completion waits replace fixed sleeps. Cleanup drains jobs before
  deleting storage. Shared E2E setup/sibling singleton suites reset and drain
  runners; backend API tests dispatch to their fixture-owned runner. Nested
  E2E clients restore environment/state, and empty history must actually be empty.
- `ui/tests/conftest.py` sends pytest thumbnail writes to temporary storage and
  fails the session if repository runtime file/symlink paths, modes, sizes, or
  mtimes change under outputs/inputs/models/.cache. It excludes external paths,
  directory-only mutations, direct unittest execution, and forced process death.
- Focused workflow tests: 4 passed/6 deselected in 1.54s. Final full UI/API/E2E:
  444 passed in 14.01s, including the session guard, with two known deprecations.
  The first full run passed 444 in 13.99s before adding the guard. Initial fixture
  checks exposed the getter fallback and filename assumption; both were fixed.
- Separate snapshots of 5,268 runtime entries show zero additions, removals, or
  changes. SHA-256 covers outputs/inputs/cache and model files smaller than 1 MiB;
  large model sizes/mtimes match. Evidence: `/tmp/qwen-phase102-runtime-before.json`,
  `after.json`, `report.json` (same prefix), and `/tmp/qwen_phase102_snapshot.py`.
  Earlier synthetic records remain; no user history cleanup was attempted.
- Python compilation and diff whitespace checks passed. Production code is
  unchanged in this slice, so no new browser/GPU/model/network validation was run.
  Earlier Node/core/hardware evidence is retained without claiming fresh reruns.

## Phase 10.3 uploaded model selection

Completed 2026-09-29. The browser retains the final confirmed upload receipt,
matches its exact path to a refreshed compatible catalog entry, and applies the
stable ID through the existing controller. Download/advanced fields cannot
override it. Failed refreshes cannot select stale cached entries; incompatible
or unlisted stored files report that they were uploaded but not selected.

- Node state-machine checks: 51/51; stress checks: 15/15. Coverage includes single
  and chunked uploads, initial empty selection, misleading intermediate paths,
  duplicate filenames at different paths, malformed/unconfirmed receipts,
  catalog failure, incompatibility, and validation/run submission using the ID.
- Running the updated harness against the committed pre-fix JavaScript failed
  the upload selection assertion (`model_111` remained instead of `model_222`).
- UI pytest: 444 passed in 13.78s, including the repository runtime-file guard.
  Only the two known Starlette/AnyIO deprecation warnings remain.
- Native Chrome file-input uploads passed at 1440px and 390px. The real catalog
  and validation API resolved each selected ID to the uploaded path and local
  companion. Visible active name/path, 100% completion, no horizontal overflow,
  incompatible-file preservation, and HTTP 409 preservation were verified.
- Evidence: `/tmp/qwen-model-selection-browser-305mc13c` contains receipts,
  request/resolved configuration, screenshots, logs, and normal shutdown for
  server PID 3372782 and Chrome PID 3372783 (both exit 0). Fixture bytes matched
  storage; upload temporary files were cleaned; no inference was requested.
  These are structural catalog fixtures, not complete inference models. No new
  GPU/model-loading/download or image-quality claim follows from this check.

## Phase 10.4 configured output directory

Completed 2026-09-29. Browser initialization/presets use the escaped server-rendered
native input default. Web validation/submission share the existing directory
resolver for omitted/empty paths; explicit nested, flat, and relative overrides
remain authoritative. The singleton initializes at the configured root, and
history respects CLI/state precedence over a conflicting environment root.
Core CLI defaults and inference loading are unchanged.

- Focused integration: 3 passed for CLI, environment, and default configuration.
  Each exercises actual temporary CPU demo jobs, persisted/served output hashes,
  initial/restarted history, explicit overrides, unsafe/invalid values, and an
  output path containing quotes/ampersand/angle brackets.
- Full UI suite: 447 passed in 14.26s with the runtime-file guard; only the two
  known deprecation warnings remain. Frontend checks: 52/52; stress: 15/15.
  The new default-path check fails against pre-fix JavaScript (51/52).
- Native Chrome at 1440px/390px: configured default, manual override, and cleared
  field produced three completed CPU demo jobs. Presets restored the configured
  path. Requests, saved paths, result display, output serving, and isolated
  history agree; both layouts have no horizontal overflow.
- Browser evidence `/tmp/qwen-output-directory-browser-wc6n_f0v` contains
  `browser.json`, three screenshots, verified `artifacts.json`, logs, and
  `shutdown.json`. The wrapper redirects thumbnails only; actual CLI startup
  constructs the singleton. Server PID 3405975 and Chrome PID 3405976 exited 0.
  The first driver waited for a multi-result strip on a single-result run and
  timed out; the corrected driver passed. Its outer artifact check then used
  the wrong metadata location; corrected offline checks verified all retained
  records/hashes/comparisons without another browser run.
- `runtime-comparison.json`: all 5,268 runtime entries match the retained
  pre-Phase-10.2 baseline; no additions/removals/changes. SHA-256 covers
  outputs/inputs/cache/small model files; large model sizes/mtimes are unchanged.
  This is synthetic workflow/storage validation, not new GPU inference evidence.

## Phase 10.5 saved-result inspection

Completed 2026-09-29. Completion updates status, progress, errors, history, and
system snapshots immediately. The shared viewer defers one completion while
History or Outputs is open, preserving the exact selected image, comparison
position/mode, details, and result tab. Returning to Inference/Batch applies it
once. Failures clear stale live images and show logs. Confirmed deletion evicts
matching deferred artifacts and retains undeleted sibling outputs; late saved
selection or batch-details responses cannot replace newer live/selected results.
A launch receipt arriving after saved selection also preserves its result tab.

- Node frontend: 54/54; stress: 15/15. Two new parameterized regressions cover
  History/Outputs × success/partial/error, exact second image, comparison state,
  details/tab, current-job identity/progress, refreshes, one-time application,
  ordinary completion, deletion, late responses, and delayed launch/navigation.
  Both fail against committed pre-fix JS (52/54); evidence
  `/tmp/qwen-phase105-before-mfgh05al/harness.log`.
- Host full UI suite: 447 passed in 13.76s with the repository runtime-file
  guard; only known Starlette/AnyIO deprecation warnings remain. JS syntax and
  diff whitespace checks passed. Core/model/GPU/download code did not change.
- Real temporary CPU demo/SSE/native Chrome workflow at 1440/900/390px:
  successful Outputs inspection, failed History inspection, partial-success
  Outputs inspection, deferred-result deletion, and ordinary live completion.
  Preview/download/second-image selection, comparison position/mode, saved JSON,
  and active tab were identical before/after completion. Navigation then showed
  the completed job or failure logs; all viewports had no horizontal overflow.
  Native confirmation cancellation preserved a new result; acceptance deleted
  its JSON/PNG and the remaining sibling appeared on return to Batch.
- `/tmp/qwen-inspection-browser-ffhw_zlt`: `browser.json`, five screenshots,
  `artifacts.json`, fresh `runtime-before.json`, logs, and `shutdown.json`.
  Ten retained durable demo records (three errors), eight output PNG hashes,
  unchanged unrelated working-directory fixture, and all 5,268 repository
  runtime file modes/sizes/mtimes verified. Server PID 3471306 and Chrome PID
  3471307 exited 0. Desktop/phone screenshots visually inspected.
- Temporary wrapper uses actual CLI/server/bridge startup, redirects thumbnails,
  and delays DemoBackend generation by three seconds with explicit fixture-only
  failures. No real weights/GPU/download or user-asset deletion was performed.
  First browser run passed success/failure but captured stale JSON before an
  asynchronous saved selection completed. The corrected wait requires loaded
  saved JSON and visible preview; the fresh full run exited 0. Its earlier
  evidence is retained at `/tmp/qwen-inspection-browser-spwdkczb`.

## Phase 10.6 monitor stop and reconnection

Completed 2026-09-29. The root cause was `cancelRun`/SSE error calling
`setRunningState(false)` after closing only the browser stream. No server
cancellation occurred. The existing controller now retains the unresolved job
and batch state, labels stopped/disconnected/connecting monitoring, freezes
last-known timing, and keeps submission locked until parsed terminal completion.
The existing button moved to the shared result header and switches between
**Stop monitoring** and **Reconnect monitor**. Reconnection reuses existing SSE
replay; old-stream callbacks cannot replace a newer stream or deliver completion.
Saved inspection and deferred live-result delivery remain intact.

- Node frontend: 56/56; stress: 15/15. Two parameterized tests exercise native
  control clicks, same-job URLs, locked validation/submission, retained batch
  identity/counts/timing, Dashboard/footer labels, connecting/queued/running,
  stale callbacks, success/partial/error/interrupted replay, saved views,
  constructor failure, malformed completion, and unavailable monitoring.
  Both new tests fail against the preserved pre-10.6 JS (54/56), evidence
  `/tmp/qwen-phase106-before-65vwngdz/harness.log`. The fixture now relies on
  App.init's existing controller binding instead of binding its click twice.
- Host full UI/API/E2E: 447 passed in 13.45s, including the runtime-file guard;
  only existing Starlette/AnyIO deprecation warnings. JS syntax and diff checks
  passed. No backend/model/GPU/download implementation changed.
- Actual temporary CLI/FastAPI/bridge/native Chrome CPU demo at 1440/900/390px:
  stopped monitor reconnects while active; stopped monitor reconnects after
  server success/failure; browser transport-error handling reconnects while
  active. Every reconnect opened the same URL with no additional run POST.
  Run remained disabled until verified completion, and status/footer reflected
  monitoring versus completion. Saved second-image/JSON/tab/comparison state
  survived both successful and failed replay; returning to Batch showed the
  new result or cleared failed images/logs. All widths had no horizontal
  overflow, and hit-testing confirmed the reconnect action was reachable.
- Evidence `/tmp/qwen-monitor-browser-eshj7zcv`: `browser.json`, four screenshots,
  `artifacts.json`, fresh `runtime-before.json`, server/Chrome logs, and
  `shutdown.json`. Nine durable demo records (two errors), eight PNG hashes,
  the unrelated working-directory fixture, and all 5,268 repository runtime
  file/symlink modes/sizes/mtimes verified unchanged. Server PID 3545010 and
  Chrome PID 3545011 exited 0; desktop/phone screenshots visually inspected.
- Temporary wrappers redirect thumbnails and delay DemoBackend by three
  seconds with explicit fixture-only failures. Transport loss was injected by
  closing the native EventSource and dispatching its error event; this verifies
  the browser recovery path, not a physical network outage. Backend SSE, jobs,
  storage, and terminal events were real. No model weights/GPU/download ran.
  First diagnostic driver used nonexistent batch IDs; corrected to existing
  IDs and a fresh full run passed. Earlier diagnostic evidence remains at
  `/tmp/qwen-monitor-browser-3g2tugv5`; its owned processes also exited 0.

## Phase 10.7 latest batch snapshot replay

Completed 2026-09-29. Ordinary events stop entering history at 5,000, which
previously discarded later batch item/progress updates. `RunJob.push_event`
now retains one full snapshot only when a batch event is omitted. It preserves
the published scalar values and copies all existing planned items. Replay
captures it with history/subscription under the job lock and inserts it before
live events or the first completion. Earlier retained event sequences, terminal
retention, API payloads, frontend controllers, and the log ceiling are unchanged.

- Focused host tests: 3 passed/28 deselected plus 15 subtests in 1.49s. Coverage:
  4,999/5,000/5,500-event boundaries, unchanged retained replay, replaced omitted
  snapshots, counts/errors/items/steps/elapsed/ETA, unpublished mutation isolation,
  success/partial/error/interrupted completion order, deterministic producer
  blocking during snapshot/subscription, later live updates/terminal delivery,
  zero leaked subscribers, and actual two-input noisy demo API/output serving.
- New regressions reject an isolated pre-fix bridge: two failed test methods and
  three failed boundary subtests (overall exit 1). Evidence
  `/tmp/qwen-phase107-before-tests.log`; pre-fix source
  `/tmp/qwen-phase107-before-runner_bridge.py`. Working source was not reverted.
- Full host UI/API/E2E: 450 passed plus 15 subtests in 13.91s, with repository
  runtime guard; only existing Starlette/AnyIO deprecations. Node frontend 56/56
  and stress 15/15 passed. Scoped Python compilation and diff checks passed.
- Real temporary CLI/server/bridge/native Chrome CPU demo: stop monitoring,
  emit 5,200 worker logs, finish the first input, enter second generation, then
  reconnect the same SSE URL without another POST. Replay showed completed 1/2,
  failed 0, remaining 1, 50%, current red.png generating, first blue.png completed
  with Details, and measured 4s elapsed/ETA. All three 1440/900/390px layouts
  displayed this snapshot without horizontal overflow. Final completion, saved
  records, native preview, and serving/hashes were verified.
- Evidence `/tmp/qwen-replay-browser-9joh6wt_`: `browser.json`, four screenshots,
  `artifacts.json`, fresh `runtime-before.json`, logs and `shutdown.json`. Three
  durable demo records and four PNG hashes, unchanged unrelated fixture and all
  5,268 runtime file/symlink modes/sizes/mtimes verified. Server PID 3590641 and
  Chrome PID 3590642 exited 0; desktop/phone active snapshots visually inspected.
- Browser success used the native Auto-scroll toggle **off**. Initial on-mode
  attempt `/tmp/qwen-replay-browser-gt1hxt2v` hit a 10s CDP evaluation timeout while
  processing the burst; server/Chrome exited 0. Existing TerminalViewer reads
  scrollHeight and writes scrollTop after each appended line; repeated forced
  layout was the suspected cause at that checkpoint. Phase 10.8 below records
  the shared fix and final native Auto-scroll-on validation. Wrapper generates real demo
  records with fixture-only logs/delays; no real weights/GPU/download ran.
- Fixture corrections: a generated test string initially needed newline escaping;
  pytest replaced sys.stdout, so noisy demo logs now explicitly use the existing
  worker capture hook. Sandbox concurrent-loop test stalled and was stopped;
  the same host-access tests passed. No production workaround was introduced.

## Phase 10.8 log replay responsiveness

Completed 2026-09-29. Both terminal append methods previously read scrollHeight
and wrote scrollTop after every DOM insertion. One pending native animation
frame now handles both methods; text is still appended immediately in order.
Clear cancels pending scrolling and the callback checks the current toggle.
Phone terminal height is bounded at 60vh so it can actually scroll.

- Pre-fix Node regression: 56/57, 5,002 geometry reads during 5,002 appends;
  `/tmp/qwen-phase108-before-tests.log`. Final frontend 57/57, stress 15/15:
  frame-ID-zero coalescing, immediate ordered text, ANSI/stderr/error formatting,
  HTML-like log text safety, actual Copy/Clear handlers, pending toggle changes,
  resumed follow and new-job cleanup. No production source reverted.
- Final host UI/API/E2E: 450 passed plus 15 subtests in 14.22s, runtime-file guard
  passed; only two known Starlette/AnyIO deprecations. JS syntax/diff checks pass.
  Prior core/hardware evidence keeps its original scope; no model/GPU rerun.
- First native on-mode check passed timing, but phone screenshot revealed the
  console grew to fit every line. The stricter real phone check before CSS fails
  `Terminal grew to fit all replay logs instead of scrolling` at
  `/tmp/qwen-autoscroll-phone-before-7u979hr6`; both owned processes exited 0.
- Final real CLI/server/bridge/native Chrome CPU demo: three separate two-input
  jobs, at 1440/900/390px, native stop before 5,200 logs, second generation, same
  URL reconnect with no new POST. Auto-scroll on: 4,995 ordered retained lines,
  4/3/4 geometry reads, 255/255/267ms replay, 16/16/17 layouts (about
  20.4/19.0/25.3ms total layout time). Original 10s CDP deadline retained.
  Current completed 1/2/items/Details/50%/timing restored; terminal scrollHeight
  exceeds clientHeight and positive scrollTop reaches bottom at all widths.
  No horizontal overflow. Native clipboard equals complete visible log text;
  Clear/toggle work; actual completion unlocks and displays saved results.
- Evidence `/tmp/qwen-autoscroll-browser-gzglllpu`: browser.json, six screenshots,
  artifacts.json, fresh runtime-before.json, logs, shutdown.json. Seven durable
  demo records/eight PNG hashes, unrelated fixture and all 5,268 runtime entries
  unchanged. Server PID 3743267/Chrome PID 3743268 exited 0; final desktop/phone
  screenshots visually inspected. Temporary helpers reuse the existing replay
  wrapper/CDP client; fixture-only logs/delays, real SSE/jobs/results, no weights,
  GPU/network, new dependency/renderer, or user storage change.

## Remaining scope and next task

**Phase 10.9 — Persistent handoff maintenance:** archive detailed completed-task,
file and test history without losing evidence or decisions, and keep root
CONTEXT.md concise with current architecture/state/limits/next action. No
production behavior change. Reconnection still requires the same tab/job ID;
missing jobs remain unverified. Tab-reload recovery, omitted ordinary logs and
inference cancellation are unchanged. Live browser log nodes remain unbounded
until Clear/next job/reconnect; native frames can wait in hidden tabs, while text
is still appended immediately. This bounded replay does not benchmark unlimited
log retention.

Model upload publication requires filesystem hard-link support and fails safely
when unavailable; no overwrite fallback is provided. Distinct concurrent upload
IDs were tested; chunk-session identity/retry/disk-quota management is unchanged.
Upload success establishes storage, not model compatibility or checksum verification.

The previous missing-adapter limitation is resolved for this supplied asset.
Arbitrary model families, quantized-transformer LoRA compatibility, production
portrait-quality benchmarking, large-download throughput, and interrupted-network
recovery are not established by these bounded checks. Large unpaginated history,
in-memory batch/download state, whole-run output deletion, and model-dependent
reference adherence remain documented operating limits. Phases 10.1–10.8 are complete within this scope; persistent handoff maintenance
is the next focused task. No new functional scope is implied.

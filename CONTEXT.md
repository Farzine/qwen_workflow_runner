# Repository Context

Last updated: 2026-09-29 (Asia/Dhaka). Current resume source of truth.
Detailed history is in [CONTEXT_HISTORY.md](docs/CONTEXT_HISTORY.md): the complete
1,310-line pre-compaction context, preserved byte for byte from `95e0f22`.
Read this file completely on resume; consult archive sections only as needed.
Historical instructions in the archive do not replace this handoff.

## Project Overview

`qwen_workflow_runner` implements a ComfyUI Qwen Image 2.1 conditioning workflow.
`run.py` provides the CLI; FastAPI plus a vanilla JS SPA provides eight pages:
Dashboard, Inference, Batch, History, Outputs, Models, LoRAs, System.
Production inference is the default. Explicit synthetic demo is input-derived,
labeled, and never substituted silently for a failed production runtime.

Checkout: `/mnt/lab/farzine/qwen_workflow_runner`, remote
`https://github.com/Farzine/qwen_workflow_runner.git`. The originally supplied
`/mnt/lab/farzine/projects/qwen_workflow_runner` was absent during the audit.

## Current Goal

Maintain a correct, responsive inference/management application with persistent
resume state. Phases 0–9 and 10.1–10.9 are complete within the recorded validation
scope. Broader model families, arbitrary adapters and production portrait-quality
benchmarks are not implied by that completion. Operating limits remain below.

## Active Task

Phase 10.9 complete: shorten the root handoff and archive the full prior context.
User commit `95e0f22` contains all nine formerly pending Phase 10.7/10.8 paths;
resume started with a clean working tree. Scoped source review confirms latest
batch replay, native scroll scheduling and mobile height bound match the record.
No production behavior or existing runtime assets changed, and no commit was created.
One concurrent setup-error record appeared outside the documentation commands;
it is preserved and described under Current Problems / Tests Performed.
Current changes: `CONTEXT.md`, `PROJECT.md`, `VALIDATION_MATRIX.md`, new
`docs/CONTEXT_HISTORY.md`. Reconcile these with Git on the next resume.
No further implementation task is queued; stop at this documentation checkpoint.

## Repository Map

| Path | Responsibility |
| --- | --- |
| `run.py`, `benchmark.py` | CLI entry points and repeated benchmark summaries. |
| `qwen_runner/config.py` | Model/generation/runtime dataclasses, validation, serialization. |
| `qwen_runner/runner.py` | Input/repeat expansion, operation callbacks, outputs/comparisons/records/errors. |
| `qwen_runner/images.py`, `sampling.py`, `kv_cache.py` | Ordered EXIF-corrected images/canvas, sigma schedule, lossless conditioning cache. |
| `qwen_runner/backend.py`, `pipeline.py`, `gguf_loader.py` | Device/model/adapter loading, Qwen encoding/denoising/decoding, strict supported GGUF tensors. |
| `qwen_runner/resources.py` | PipelineManager: exclusive per-device leases, compatible reuse/replacement, unload/shutdown. |
| `qwen_runner/models.py`, `record_metadata.py`, `metrics.py`, `system.py` | Hub manifests/provenance, readable summaries, timing/memory, runtime/device probes. |
| `ui/app.py`, `server.py` | Uvicorn CLI/lifecycle, directory configuration, REST/SSE routes and path confinement. |
| `ui/runner_bridge.py` | Single-worker jobs, output capture, batch events/replay, persistent production leases, explicit DemoBackend. |
| `ui/model_catalog.py`, `download_jobs.py`, `model_deletion.py` | Stable compatible IDs, measured download jobs, safe direct/manifest/shared-blob deletion. |
| `ui/templates/index.html`, `static/js/app.js`, `static/css/style.css` | Shared 208-ID DOM, client controllers/state/navigation, responsive task pages/help/viewers. |
| `tests/`, `ui/tests/` | Core/runtime/resource and API/DOM/E2E/Node checks; UI conftest guards runtime file metadata. |
| `scripts/validate_browser_production.js`, `validate_hub_download.py` | Opt-in real browser/hardware and pinned bounded Hub checks. |
| `workflow/original.json`, `PORTING_NOTES.md`, `source_manifest.json`, `reviewed_gguf_tensor_inventory.json` | Source graph, parity decisions, provenance, reviewed tensor inventory. |
| `README.md`, `ui/README.md`, `PROJECT.md`, `VALIDATION_MATRIX.md` | Launch/test instructions, feature/API contracts, roadmap, exact validation scope/evidence. |
| `models/`, `inputs/`, `outputs/`, `.cache/`, `.venv/` | Ignored runtime state: preserve existing assets and environment. |

## Architecture

```mermaid
flowchart LR
    UI[Eight-page vanilla SPA] <-->|REST and SSE| API[FastAPI]
    API --> Catalog[Stable model catalog]
    API --> Downloads[Background download jobs]
    Downloads --> Store[ModelStore and Hub manifests]
    API --> Bridge[Single-worker RunnerBridge]
    Bridge --> Manager[Exclusive per-device PipelineManager]
    Manager --> Backend[QwenBackend and active LoRA]
    Bridge --> Runner[Core runner]
    Runner --> Images[Current input and ordered references]
    Runner -->|Borrow loaded backend| Backend
    Backend --> Store
    Backend --> Pipeline[Qwen pipeline, scheduler, KV cache]
    Pipeline --> Generated[Generated PIL images]
    Generated --> Runner
    Runner --> Disk[PNG, comparisons, durable JSON and readable summary]
    Disk --> API
    API --> UI
```

The original audit used Python AST imports plus Mermaid because specialized
Graphiphy/Graphviz tools were unavailable. Full dependency and sequence diagrams
remain in [archived architecture](docs/CONTEXT_HISTORY.md#architecture).

Request flow: UI role selection/parameters → selected-ID resolution/path validation
→ bridge job/per-device lease → load/reuse model, apply LoRA/device → runner expands
`[current_input, *references]` → EXIF/RGB/resize/canvas preprocessing → seeded CPU
float32 noise, prompt/image encoding, target-only denoising and VAE decoding →
PIL → saved PNG/hash/comparison/JSON → batch/status/log/complete SSE → live viewer
and durable history. Demo uses a separate explicit synthetic backend.

## Decisions and Contracts

- **Model authority:** compatible `selected_model_id` resolves server-side to actual source/companions; advanced/download fields cannot override it. Legacy direct-source API/CLI callers remain supported. Catalog supports Qwen Image 2.1 complete pipelines and supported transformer-only weights with exactly one compatible local companion. Logical snapshot paths preserve GGUF format and manifest identity.
- **Images:** 1–10 ordered independent inputs; 0–9 ordered shared references, at most ten conditioning images per call. Explicit fields take precedence over legacy combined `images`; inactive legacy data serializes as empty. Each input attempt has its own durable record; ordinary item failures continue with partial-success aggregation. Legacy corrupt images retain setup-error behavior.
- **Seeds/output counts:** repeats share one seed across inputs; incrementing advances between repeats. Batch/warmup expansion is preserved; successful warmups cannot hide failure of every requested output. Setup time is in elapsed time; ETA uses measured finished-attempt durations and is unavailable until one finishes. No automatic inference retry that drops LoRA/reference conditioning.
- **LoRA:** user directory `/mnt/lab/farzine/qwen_workflow_runner/models/loras`; original `bfs_head_v1.1_qwen_2.1.safetensors` (260,096,144 bytes) must remain untouched. One local SafeTensors adapter, strength 0–2, active name `qwen_workflow_lora`, unfused application/effective hash/state in records. AI-Toolkit fused gate/up updates split B rows with shared A after normalizing alpha; weights themselves are not rewritten. Demo records not-applied state.
- **Resources:** one compatible resident pipeline per normalized device (`cuda` = `cuda:0`); one executor worker. Lease spans the whole job and excludes resource switching/deletion. Compatibility includes backend/model/revision/file/quantization, companions/text encoder, cache directory, device/dtype/offload/VAE tiling; excludes generation/image parameters and LoRA so compatible weights can be reused. Idle adapter replacement/rescaling uses existing Diffusers APIs.
- **Device/lifecycle:** System Apply affects the next job. CPU normalizes to float32/no offload; MPS to no offload. Generation failure invokes existing offload-hook cleanup and preserves the original error if cleanup fails. Shutdown rejects submissions, drains work, unloads adapters/hooks/components, drops references, collects garbage, synchronizes CUDA and clears allocator/IPC caches; process exit releases the CUDA context.
- **Storage:** omitted/empty web output paths honor configured server defaults (CLI/state before env); explicit nested/flat/relative paths remain authoritative and confined. Default-root history survives restart; session custom roots are registered only in memory. Model upload uses non-replacing atomic hard links for both single/chunked paths; occupied files/symlinks return conflicts. Upload success is storage, not compatibility/checksum proof.
- **Deletion:** confirmed real API actions for catalog models, LoRAs and whole finished runs. Protect queued/running/download/leased resources, unload idle slots, preserve shared Hub blobs/artifacts, evict finished in-memory aliases. Web locks do not cover independent CLI processes.
- **Metadata/UI:** schema-v1 durable records plus `summary_version: 1`; legacy summaries projected on API reads without migration. Actual file facts or explicit unavailable/null values; never invent parameter counts. Shared viewers preserve saved inspection through background completion; pending completion is shown once on returning to Inference/Batch. Selection/deletion counters reject stale responses.
- **Monitoring:** Stop monitoring closes only this tab's SSE. Keep job identity/unverified state and block submission until recognized terminal completion. Manual Reconnect uses the same URL without POST; guard callbacks by stream identity. Capture history/subscription atomically; after 5,000 retained ordinary events replay one immutable latest full batch snapshot before live/complete. Later ordinary logs remain omitted.
- **Logs/help:** immediate ordered text with native once-per-frame auto-scroll, callback toggle check, Clear cancellation, 60vh phone terminal bound. Copy reads complete current text. 41 implementation-backed accessible help controls; negative conditioning is `CFG != 1`; strength selects the schedule tail, not input-pixel blending; `resolution=0` keeps native references.
- **Dashboard:** health/resources are timestamped snapshots refreshed on startup/configuration/completion/request; batch/download activity monitors this tab. No fabricated polling, global queues/download listings or storage totals.

## Dependency / Runtime State

`requirements.txt` and `requirements-cu126.txt` describe the supported stack.
Previously verified: PyTorch `2.11.0+cu126`, torchvision `0.26.0+cu126`, CUDA 12.6,
Triton 3.6.0, setuptools 81.0.0, PEFT 0.21.0, Diffusers `0.41.0.dev0`, Hub 1.32.0.
Host evidence covers two RTX A6000s (~48 GiB each), driver 560.28.03, i9-12900K,
~125.6 GiB RAM. These are retained probe-time facts, not fresh capacity checks.
Old CUDA 13 packages remain in `.venv/runtime-backups/cu130-20260923/site-packages`.
Native Node 22.22.0 supplies diagnostic `fetch`/`WebSocket`; the application needs
no Node service. GPU work needs host device access, and TestClient SSE needs host
IPC/loopback; sandbox hangs were reproduced independently of application code.

## Completed Tasks

| Phase | Completed scope |
| --- | --- |
| 0–2 | Full audit/graphs/reference comparison; same-image root cause; explicit production/demo, runtime diagnostics, CUDA correction, real inference. |
| 3–5 | Ordered multi-input/reference upload/preview/removal/validation; LoRA discovery/upload/application; manual device and System information. |
| 6–8 | Responsive/accessibility/workflow states, 41 help entries, real browser-to-output validation. |
| 9.1–9.3 | Per-device reusable resources/shutdown; authoritative model IDs; truthful Hub progress/cancel/retry. |
| 9.4–9.6 | Protected model/LoRA/run deletion; readable common metadata; aggregate per-item batch stages/counts/timing/ETA. |
| 9.7–9.8d | Eight task pages; integrated routes/errors; full-model/offload recovery, Hub HTTP/Xet, selected GGUF, fused pretrained LoRA and stabilization. |
| 10.1–10.4 | Collision-safe uploads, isolated UI test storage, uploaded-ID selection, configured output defaults/history. |
| 10.5–10.8 | Saved inspection, truthful stop/reconnect, batch replay beyond event cap, responsive default log scrolling. |
| 10.9 | Concise handoff, lossless full-history archive, current Git reconciliation, evidence/link/source/runtime checks. |

Per-task files, failed diagnostics and all original evidence remain in
[archived completed tasks](docs/CONTEXT_HISTORY.md#completed-tasks),
[file history](docs/CONTEXT_HISTORY.md#files-modified) and
[tests](docs/CONTEXT_HISTORY.md#tests-performed).

## Remaining Tasks

No queued implementation task in the completed supported roadmap. Current limits
below are not silently marked fixed. Future work should address an actual reported
failure or an explicitly selected extension; do not invent Phase 10.10 merely to
continue numbering. No files still require modification for Phase 10.9.

## Current Problems

No new functional defect was found in this documentation slice. The original
same-image root cause was silent DemoBackend substitution with an incompatible
CUDA runtime: all 426 pre-fix records were synthetic. Production now always uses
QwenBackend or reports an actionable setup error. Full-model outputs prove the
transformation; persistence/display did not overwrite valid generated results.

During this task, `outputs/20260929T083542_9ec66f4252_setup_error.json` appeared.
It reports expected `FileNotFoundError` validation for the absent default example
`inputs/portrait_model_denim.png`, before backend loading. Its producer was not
identified; none of this task's stdlib/Git documentation commands invokes inference.
Preserve it. This is not evidence of a new model/pipeline defect or a reason to
download examples automatically.

## Important Technical Findings

- AI-Toolkit `img_mlp.gate_up` fused updates do not directly target Diffusers `gate_layer`/`proj`; the shared loader conversion and numerical/full-model tests cover the supplied adapter.
- Failed Accelerate transfers could leave mixed CPU/GPU tensors; existing hook cleanup on generation failure restores reusable placement when possible.
- Upload filename and hashed catalog ID differ. Only a confirmed final receipt path plus a successfully refreshed compatible catalog may change selection.
- Viewer completion, monitor lifecycle and replay retention are distinct: defer viewer delivery, retain unresolved job lock, retain one latest full published batch snapshot after the ordinary event ceiling.
- Per-line geometry reads forced repeated layout; one native frame coalesces both append paths. Phone auto-height required a separate console height bound. Prior on-mode/phone diagnostics failed before these fixes.

## Reference Implementations

`/mnt/lab/farzine/projects/Nunchaku-Generic-Form/klein_generic_infer.py` is a
528-line client for remote Flux.2 Klein, not a local Qwen loader. It reuses uploaded
source IDs, separates references/adapter names, tracks batch success/failure/time/
ETA, polls/downloads results and saves comparisons/metadata. Device/model loading
is remote. Its optional-feature-dropping retries and Flux endpoint/prompt contract
are intentionally not copied. Detailed comparison and the upstream fused-adapter
reference are [archived](docs/CONTEXT_HISTORY.md#reference-implementations).

## Files Modified

This task changes four documentation paths only:

- `CONTEXT.md` — concise current state, contracts, scoped evidence, limits and continuation.
- `docs/CONTEXT_HISTORY.md` — new lossless snapshot with navigation and SHA-256; old checkpoint instructions explicitly historical.
- `PROJECT.md`, `VALIDATION_MATRIX.md` — mark 10.9 complete and link the current handoff/archive; remove the obsolete pending task.

HEAD `95e0f22` committed the previous nine paths: four shared docs, runner bridge,
backend tests, app JS/CSS and Node harness. Their former pending descriptions in
the archive are historical. No production/test/runtime change by this task;
the concurrent added error record is tracked separately below.

## Tests Performed

**This task:** archive body equals both original context and `git show
95e0f22:CONTEXT.md`; original SHA-256 is recorded in its preface. Required resume
sections, local links/anchors and retained evidence references checked. Protected
tracked-file hashes and all 5,268 pre-existing runtime file/symlink modes/sizes/
mtimes unchanged. One concurrent added setup-error record is recorded separately
(5,269 total entries); no removals or changes to existing assets. Only the four
intended tracked/new documentation paths differ. `git diff --check` passed. Check evidence:
`/tmp/qwen-phase109-validation.json`. No suite/model/browser/GPU/download rerun.

**Latest retained results (not newly run):**

| Validation | Result / scope | Evidence root |
| --- | --- | --- |
| UI/API/E2E, Phase 10.8 | 450 passed + 15 replay subtests in 14.22s; runtime metadata guard | [Matrix](VALIDATION_MATRIX.md#phase-108-log-replay-responsiveness) |
| Node, Phase 10.8 | 57/57 frontend, 15/15 stress; pre-fix rejection, Copy/Clear/toggle/order/error safety | [Archive tests](docs/CONTEXT_HISTORY.md#tests-performed) |
| Core, Phase 9.8c3 | 43 tests + 13 subtests; fused/split forward math and adapter lifecycle | `/tmp/qwen-lora-validation-hyd258je` |
| Default auto-scroll, Phase 10.8 | Actual three separate CPU demo UI/SSE jobs at 1440/900/390; 4,995 retained lines, 4/3/4 geometry reads, 255/255/267ms replay; real scrolling/clipboard/results; seven records/eight PNG hashes; unchanged 5,268 entries and owned shutdown | `/tmp/qwen-autoscroll-browser-gzglllpu` |
| Full production, Phase 9.8b | Four real outputs, input/reference/model/device/hash/serving, fixed-seed repeat, one load/reuse; explicit shutdown; tiny transfer recovery | `/tmp/qwen-phase98b.AJEcJM` |
| Selected GGUF, Phase 9.8c2 | Cached Q4_0 transformer/297 exact tensors, four real outputs, model replacement/reuse and shutdown; full companions required | `/tmp/qwen-gguf-validation-9znq346l` |
| Pretrained LoRA, Phase 9.8c3 | Eight real browser outputs: baseline/existing/uploaded/cleared; uploaded matches existing, removal restores baseline, measured effect, one base load, native upload/shutdown | `/tmp/qwen-lora-validation-hyd258je` |
| Hub, Phase 9.8c1 | Pinned 484,951 total bytes; real HTTP/Xet callbacks/hashes, cancel/retry/cache/terminal/catalog; no model loading | `/tmp/qwen-hub-validation-hbikkfmd` |
| Hub browser, Phase 9.8c1 | Real download, readable failure/new-ID retry and reachable phone controls | `/tmp/qwen-hub-validation-cax0tm3q` |

These roots and their principal evidence files exist as of this checkpoint.
`/tmp` evidence/helpers are local and disposable, not tracked or guaranteed to
survive cleanup/restart. The archive/matrix preserve recorded observations if
files disappear; absence does not invalidate history or establish fresh proof.
Read retained JSON/screenshots only as needed; do not load weights to recreate
missing documentation evidence without a relevant validation need.

## Known Issues

- Catalog compatibility is limited to supported Qwen Image 2.1 layouts; structural checks/upload headers cannot prove exact loader shapes. Other model families/ambiguous companions/unsupported quantization are rejected. Tested GGUF is revision `40319fb...` with `790c926...` companions; its ~4.15 GB transformer still had ~18.81 GB full-pipeline peak.
- Supplied pretrained LoRA is proven at tested prompt/settings; quantized-transformer LoRA, unrelated layouts, exact head/background preservation and broad portrait-quality benchmarking are unproven. Multi-reference transport/effect is proven; hairstyle adherence was weak in one controlled sample.
- Native `resolution=0` can retain huge references and exhaust memory/degrade quality. System memory/readiness is a snapshot, not reservation; other host processes can cause OOM. Hook cleanup cannot guarantee recovery from a permanently broken CUDA context. SIGKILL/exit 137 bypasses graceful shutdown.
- Stop monitoring is not inference cancellation. Manual reconnect needs the same tab/job ID; missing jobs/invalid completion remain unverified and locked. Reload/new tabs do not recover active streams, pending viewer results, batch/download state or aggregate events after restart. Durable per-attempt/default-root history remains.
- Ordinary replay logs beyond the first 5,000 events are omitted; latest batch snapshot is retained. Live DOM logs are unbounded until Clear/next job/reconnect, not virtualized or benchmarked indefinitely. Native frames can pause in hidden tabs while text still appends. Historical logs are not independently persisted.
- History/Outputs payloads and DOM are unpaginated; lazy previews bound image requests, not large-library API/DOM costs. Dashboard has snapshots and this-tab monitors, not global job/download queues or storage totals. Custom per-run output roots are not rediscovered after restart.
- Deletion is whole-run/unshared-artifact cleanup, not individual output deletion or orphan browsing. Global active-job guard blocks deletion while inference runs; independent CLI processes are outside locks. Multi-file cleanup is best effort and filesystem failures can leave orphaned images after record removal.
- Upload publication requires hard-link support and never overwrites as fallback. Permission/disk failures may prevent cleanup; abandoned chunk sessions have no automatic expiry. Distinct upload IDs were raced; session identity/retry/quota/checksum management is unchanged.
- Hub cancellation is cooperative at file boundaries/before manifest publication; current file may already be materialized. Byte speed is reconstructed/materialized file speed, not wire throughput. Large-checkpoint/proxy/rate-limit/interrupted-network recovery remains untested. Tiny download fixtures are incompatible and never inference proof.
- Legacy records are projected without migration; inaccessible files give unavailable facts. Parameter counts are not inferred from names; directory model size needs a matching completed manifest. Run Details preview is first-output; Outputs selects every recorded artifact exactly.
- Pytest isolates inputs/history/thumbnails and guards repository runtime file metadata, not large-file content hashes, external directories, directory-only changes, direct unittest or abrupt termination. Earlier synthetic records are preserved. Known Starlette/AnyIO deprecations remain; attempted httpx2 2.13.1 broke TestClient and was removed; existing HTTPX 0.28.1 needs host IPC for SSE tests.

## User Decisions / Required Input

None. Preserve existing functionality/assets; use small independently tested slices;
no unnecessary redesign/dependency/approval flow. User LoRA directory is recorded
above. Explicit output overrides remain authoritative. Full historical decisions
and failures are preserved in the archive; its old blockers are not current input
requests. Any new product/architecture decision must arise from an actual need.

## Next Action

This documentation checkpoint is complete; no next implementation task selected.
On the next `Continue from CONTEXT.md`, read this file and inspect current Git and
relevant changes. Reconcile a user commit of these four paths without repeating
completed work. If a new request, source delta or reproduced defect exists, choose
one bounded task and update this handoff. Otherwise report this ready checkpoint
and the documented limits; do not restart the audit, rerun all hardware checks,
or manufacture another phase. Do not commit, discard or delete assets implicitly.

## Resume Instructions

1. Read root CONTEXT.md completely; use linked archive sections only for relevant detail.
2. Check `git status --short`, recent commits and scoped diffs; actual code outranks stale state.
3. Reconcile HEAD/pending paths above. Preserve unrelated user changes and ignored models/inputs/outputs/cache/environment.
4. Follow Active Task/Next Action; never resume a historical archive instruction as current work.
5. Complete one authorized, independently testable slice; no audit or completed work repetition without a concrete verification reason.
6. Validate affected behavior; use temporary storage for destructive/upload/demo checks, host IPC for SSE, explicit host GPU access for hardware. No fake inference proof.
7. Update this concise file after meaningful tasks and keep detailed new history in documentation when needed; preserve evidence scope and distinguish fresh checks from retained results.
8. End with TASK COMPLETED / VERIFIED / CHANGES / CONTEXT UPDATED / USER INPUT REQUIRED / NEXT TASK; stop at a coherent checkpoint.

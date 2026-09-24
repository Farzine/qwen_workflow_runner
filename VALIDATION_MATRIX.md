# Validation Matrix

This matrix records the final Phase 8 validation state for the production
workflow. Automated checks use temporary files and synthetic or tiny models
where loading the 33 GB pretrained checkpoint would add no useful coverage.
Hardware rows identify the live RTX A6000 checks separately.

## Functional matrix

| Area | Scenario | Result | Evidence |
|---|---|---:|---|
| Input | Empty selection | Pass | Browser state-machine tests block submission and show the actionable 1–10 input error. API/config tests reject an empty production request. |
| Input | One image | Pass | Core, API, SSE, history, and prior full-model production runs; current regression suite. |
| Input | Multiple ordered images | Pass | Phase 8 browser-started full-model batch processed `img_1.jpeg` and `img_10.jpg` independently, in order, with two output records. |
| Input | Invalid/empty/mismatched upload | Pass | API tests cover corrupt bytes, empty files, unsupported formats, extension/content mismatch, traversal-like names, atomic rejection, count, byte, and pixel limits. |
| Input | Upload, preview, reorder, remove | Pass | Python DOM/accessibility tests and the 33-case Node state-machine harness cover role-aware multi-upload, previews, order, removal, clearing, and the ten-input boundary. |
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

Final results: 31 core tests plus 8 parameterized subtests passed, all 417
UI/API/E2E tests passed, and the Node harnesses passed 33/33 and 15/15 cases.

## Asset-dependent limitation

No compatible user LoRA is installed in `models/loras/`, so the 33 GB
pretrained checkpoint was not run with an adapter during Phase 8. Adapter
application itself is covered by the real tiny-Qwen transformer test, including
weight activation, output effect, strength, hash metadata, unload, replacement,
and incompatible-target diagnostics. A user-supplied production adapter still
needs model-specific visual quality assessment because a valid SafeTensors
header cannot establish architecture or training compatibility.

# Test Suite Ready: Qwen Workflow Runner Web UI E2E Testing Track

**Status**: READY  
**Test Suite Location**: `ui/tests/e2e/`  
**Execution Command**: `python ui/tests/e2e/runner.py`  
**Alternative Runner**: `python -m unittest discover -s ui/tests/e2e -p "test_*.py"`  
**Total Test Cases**: 227 (Required minimum: 184)  
**Pass Rate**: 100% (227 passed, 0 failed, 0 errors, 0 skipped)  
**Execution Duration**: ~1.95 seconds  

---

## 4-Tier Test Suite Summary

| Tier | Focus Area | Target Count | Implemented Count | Status |
|---|---|:---:|:---:|:---:|
| **Tier 1** | Primary Feature Coverage (F1–F16) | ≥ 80 | **86** | PASS (100%) |
| **Tier 2** | Boundary Values & Corner Cases | ≥ 80 | **113** | PASS (100%) |
| **Tier 3** | Pairwise Combinations | ≥ 16 | **20** | PASS (100%) |
| **Tier 4** | Real-World Application Scenarios | ≥ 8 | **8** | PASS (100%) |
| **TOTAL** | Complete E2E Regression Suite | ≥ 184 | **227** | **100% PASS** |

---

## Feature Coverage Matrix (F1–F16)

| # | Feature | Tier 1 (Coverage) | Tier 2 (Boundaries) | Tier 3 (Pairwise) | Tier 4 (Workflows) |
|---|---|:---:|:---:|:---:|:---:|
| **F1** | Input Directory Scanner (`/api/inputs/browse`) | 6 tests | 5 tests | ✓ | Scenario 1, 2, 3, 4, 6 |
| **F2** | Reference Image Ordering (1–10 images) | 6 tests | 5 tests | ✓ | Scenario 1, 2, 3, 4, 6 |
| **F3** | Image Previews & Thumbnails (`/api/inputs/thumbnail`) | 5 tests | 5 tests | ✓ | Scenario 1, 2, 3 |
| **F4** | Generation Parameters (prompt, steps, cfg, seed, etc.) | 6 tests | 17 tests | ✓ | Scenario 1, 2, 3, 4, 6, 7 |
| **F5** | Runtime Parameters (device, dtype, offload, prefix, etc.) | 6 tests | 20 tests | ✓ | Scenario 1, 2, 4, 6, 7 |
| **F6** | Validation Endpoints (`/api/config/validate`) | 6 tests | 5 tests | ✓ | Scenario 2, 4, 7 |
| **F7** | Model HF Repo Selector & Download (`/api/models/download`) | 5 tests | 5 tests | ✓ | Scenario 5 |
| **F8** | Model File Upload (`/api/models/upload`) | 5 tests | 5 tests | ✓ | Scenario 3, 5, 8 |
| **F9** | Cached Models Discovery (`/api/models`) | 5 tests | 5 tests | ✓ | Scenario 5, 8 |
| **F10**| GGUF Quantization Variant Selector | 5 tests | 5 tests | ✓ | Scenario 5, 8 |
| **F11**| Background Run Execution & SSE Stream (`/api/run`) | 6 tests | 5 tests | ✓ | Scenario 1, 2, 3, 4, 5, 6, 7, 8 |
| **F12**| Output Images, Dimensions & SHA-256 Badges | 5 tests | 5 tests | ✓ | Scenario 1, 2, 3, 4, 5, 6, 7, 8 |
| **F13**| Side-by-Side Comparison Endpoint (`{run_id}_comparison.png`) | 5 tests | 5 tests | ✓ | Scenario 2, 3, 6 |
| **F14**| JSON Run Record Endpoint (`/api/runs/{run_id}`) | 5 tests | 5 tests | ✓ | Scenario 1, 2, 3, 4, 5, 6, 7, 8 |
| **F15**| Session Run History Tracking (`/api/runs`) | 5 tests | 5 tests | ✓ | Scenario 3, 5, 6 |
| **F16**| Single-Command Startup & Healthcheck (`/api/health`, `/`) | 5 tests | 11 tests | ✓ | Scenario 7 |

---

## Test Suites Inventory

- **`ui/tests/e2e/__init__.py`**: E2E test package declaration.
- **`ui/tests/e2e/common.py`**: Test client provider, lazy import bridge, `DemoBackend` runner factory, and isolated environment fixtures.
- **`ui/tests/e2e/test_tier1_features.py`** (86 tests):
  - Validates full feature inventory F1 through F16 across primary happy-path and typical usage modes.
- **`ui/tests/e2e/test_tier2_boundaries.py`** (113 tests):
  - Rigorous BVA testing for steps boundaries (1, 10000, 0, 10001), denoise strength (0.0001, 1.0, 0.0, 1.05), training schedule truncation ratio (`int(steps/strength) > 10000`), resolution (0, 32, 4096, 500, 4128), custom dimensions, 64-bit uint seeds (0, 2^64-1, -1, 2^64), CFG guidance (0.0, 1.0, 20.0, -0.5, NaN), repeat and warmup bounds, memory poller bounds (0.001 to 1.0), prefix sanitation, device/dtype compatibility matrix, sampler/scheduler restrictions, flow shift bounds (-10.0 to 10.0), and upload validation.
- **`ui/tests/e2e/test_tier3_pairwise.py`** (20 tests):
  - Orthogonal cross-feature combinations validating interactions between custom sizes, resolution toggles, KV cache devices, offloading strategies, repeat comparison generations, scheduler/shift pairs, batch sizes, seed incrementation, VAE tiling, and quantization variants.
- **`ui/tests/e2e/test_tier4_scenarios.py`** (8 tests):
  - End-to-end user workflows simulating realistic browser sessions:
    1. Single-Reference Casual Edit
    2. Multi-Reference Complex Composition (5 images)
    3. Boundary Image Count (10 reference images max)
    4. Custom Resolution & Aspect Ratio Editing
    5. GGUF Quantization Model Switch & Run
    6. Repeats & Seed Incrementation with Comparison
    7. Graceful Validation Recovery & Resubmission
    8. Large File Upload (.gguf/.safetensors) and Immediate Inference Selection
- **`ui/tests/e2e/runner.py`**:
  - Master suite runner aggregating results across all 4 tiers, providing structured execution summaries and exit status.

---

## How to Run

```bash
# Run using the master test runner
python ui/tests/e2e/runner.py

# Or run via Python unittest discovery
python -m unittest discover -s ui/tests/e2e -p "test_*.py"

# Or run specific tiers individually
python -m unittest ui/tests/e2e/test_tier1_features.py
python -m unittest ui/tests/e2e/test_tier2_boundaries.py
python -m unittest ui/tests/e2e/test_tier3_pairwise.py
python -m unittest ui/tests/e2e/test_tier4_scenarios.py
```

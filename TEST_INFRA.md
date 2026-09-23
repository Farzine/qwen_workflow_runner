# E2E Test Infra: Qwen Workflow Runner Web UI

## Test Philosophy
- **Opaque-box & Requirement-driven**: All tests evaluate the web application through its public HTTP REST endpoints, SSE streams, static asset delivery, and CLI entrypoint. Tests do not mock or alter internal modules.
- **Methodology**: 4-tier systematic approach combining Category-Partition, Boundary Value Analysis (BVA), Pairwise Combinatorial Testing, and Real-World Workload Testing.
- **Progressive Testability**: Baseline endpoints (input browsing, validation, model listing) are testable without requiring inference. Inference tests execute seamlessly against the demo backend (`integrity_mode: demo`).

## Feature Inventory
| # | Feature | Source (requirement) | Tier 1 | Tier 2 | Tier 3 |
|---|---------|---------------------|:------:|:------:|:------:|
| 1 | Input Directory Scanner | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ |
| 2 | Reference Image Ordering (1–10) | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ |
| 3 | Image Thumbnail Previews | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ |
| 4 | Generation Config Parameter Controls | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ |
| 5 | Runtime Config Parameter Controls | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ |
| 6 | Configuration Validation & Error Handling | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ |
| 7 | Model HuggingFace Repo Selection & Download | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ |
| 8 | Model File Upload (.gguf/.safetensors) | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ |
| 9 | Cached Models Dropdown & Discovery | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ |
| 10 | GGUF Quantization Variant Selector | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ |
| 11 | Background Run Execution & Live SSE Logging | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ |
| 12 | Output Images, Dimensions & SHA-256 Badges | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ |
| 13 | Side-by-Side Comparison Viewer | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ |
| 14 | JSON Run Record Inspector & Download | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ |
| 15 | Session Run History & Status Tracking | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ |
| 16 | Single-Command Startup & CLI Configuration | ORIGINAL_REQUEST §Acceptance | 5 | 5 | ✓ |

## Test Architecture
- **Location**: `ui/tests/e2e/`
- **Runner**: `python -m unittest ui/tests/e2e/runner.py` or `python ui/tests/e2e/runner.py`
- **Pass/Fail Semantics**: Returns exit code 0 if 100% of tests pass, non-zero otherwise. Produces detailed per-tier and per-feature execution logs.
- **Directory Layout**:
  ```
  ui/tests/e2e/
  ├── __init__.py
  ├── test_tier1_features.py    # Tier 1: Feature coverage (≥5 tests per feature)
  ├── test_tier2_boundaries.py  # Tier 2: Boundary & corner cases (≥5 tests per feature)
  ├── test_tier3_pairwise.py    # Tier 3: Pairwise feature combinations
  ├── test_tier4_scenarios.py   # Tier 4: Real-world application scenarios
  └── runner.py                 # Master test runner publishing results
  ```

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised | Complexity |
|---|----------|--------------------|------------|
| 1 | Single-Reference Casual Edit | F1, F2, F3, F4, F5, F11, F12, F14 | Medium |
| 2 | Multi-Reference Complex Composition (5 images) | F1, F2, F3, F4, F5, F6, F11, F12, F13, F14 | High |
| 3 | Boundary Image Count (10 reference images max) | F1, F2, F3, F4, F8, F11, F12, F13, F14, F15 | High |
| 4 | Custom Resolution & Aspect Ratio Editing | F1, F2, F4, F5, F6, F11, F12, F14 | Medium |
| 5 | GGUF Quantization Model Switch & Run | F7, F8, F9, F10, F11, F12, F14, F15 | High |
| 6 | Repeats & Seed Incrementation with Side-by-Side Comparison | F1, F2, F4, F5, F11, F12, F13, F14, F15 | High |
| 7 | Graceful Validation Recovery & Resubmission | F4, F5, F6, F11, F12, F14 | Medium |
| 8 | Large File Upload (.gguf) and Immediate Inference Selection | F8, F9, F10, F11, F12, F14 | High |

## Coverage Thresholds
- **Tier 1 (Feature Coverage)**: ≥80 test cases (16 features × 5 tests)
- **Tier 2 (Boundary & Corner Cases)**: ≥80 test cases (16 features × 5 tests)
- **Tier 3 (Cross-Feature Combinations)**: ≥16 pairwise tests
- **Tier 4 (Real-World Scenarios)**: ≥8 end-to-end user workflows
- **Total Suite Minimum**: ≥184 test cases

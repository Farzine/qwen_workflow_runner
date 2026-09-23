"""Master E2E Test Runner for Qwen Workflow Runner Web UI.

Executes all 4 tiers of tests:
  - Tier 1: Feature Coverage (F1–F16)
  - Tier 2: Boundary Value Analysis & Corner Cases
  - Tier 3: Pairwise Combinations
  - Tier 4: Real-World Application Workflows

Reports structured per-tier and overall metrics. Exits 0 on 100% pass, 1 on failure.
"""

from pathlib import Path
import sys
import time
import unittest

# Ensure project root is in sys.path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ui.tests.e2e.test_tier1_features import TestTier1Features
from ui.tests.e2e.test_tier2_boundaries import TestTier2Boundaries
from ui.tests.e2e.test_tier3_pairwise import TestTier3Pairwise
from ui.tests.e2e.test_tier4_scenarios import TestTier4Scenarios


def build_full_suite() -> unittest.TestSuite:
    """Build the complete 4-tier E2E test suite."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestTier1Features))
    suite.addTests(loader.loadTestsFromTestCase(TestTier2Boundaries))
    suite.addTests(loader.loadTestsFromTestCase(TestTier3Pairwise))
    suite.addTests(loader.loadTestsFromTestCase(TestTier4Scenarios))
    return suite


def load_tests(loader, tests, pattern):
    """Enable unittest test discovery to load full suite."""
    return build_full_suite()


class TierSummaryResult:
    def __init__(self, tier_name: str):
        self.tier_name = tier_name
        self.total = 0
        self.passed = 0
        self.failed = 0
        self.errors = 0
        self.skipped = 0
        self.duration = 0.0


def run_tier(tier_name: str, test_class) -> tuple[unittest.TestResult, TierSummaryResult]:
    suite = unittest.TestLoader().loadTestsFromTestCase(test_class)
    runner = unittest.TextTestRunner(verbosity=1)
    summary = TierSummaryResult(tier_name)

    start = time.perf_counter()
    result = runner.run(suite)
    summary.duration = time.perf_counter() - start

    summary.total = result.testsRun
    summary.failed = len(result.failures)
    summary.errors = len(result.errors)
    summary.skipped = len(result.skipped)
    summary.passed = summary.total - summary.failed - summary.errors - summary.skipped
    return result, summary


def main():
    print("=" * 80)
    print("      QWEN WORKFLOW RUNNER WEB UI - MASTER E2E TEST SUITE RUNNER")
    print("=" * 80)

    tiers = [
        ("Tier 1: Feature Coverage (F1–F16)", TestTier1Features),
        ("Tier 2: Boundary & Corner Cases", TestTier2Boundaries),
        ("Tier 3: Pairwise Combinations", TestTier3Pairwise),
        ("Tier 4: Real-World Scenarios", TestTier4Scenarios),
    ]

    all_summaries = []
    total_failures = 0
    total_errors = 0

    suite_start = time.perf_counter()
    for name, test_class in tiers:
        print(f"\n---> Running {name}...")
        res, summary = run_tier(name, test_class)
        all_summaries.append(summary)
        total_failures += summary.failed
        total_errors += summary.errors

    suite_duration = time.perf_counter() - suite_start

    print("\n" + "=" * 80)
    print("                      E2E TEST EXECUTION SUMMARY")
    print("=" * 80)
    header = f"{'Tier':<42} | {'Total':>5} | {'Pass':>5} | {'Fail':>5} | {'Err':>5} | {'Duration':>8}"
    print(header)
    print("-" * len(header))

    grand_total = 0
    grand_passed = 0
    grand_failed = 0
    grand_errors = 0

    for s in all_summaries:
        grand_total += s.total
        grand_passed += s.passed
        grand_failed += s.failed
        grand_errors += s.errors
        print(f"{s.tier_name:<42} | {s.total:>5} | {s.passed:>5} | {s.failed:>5} | {s.errors:>5} | {s.duration:>7.2f}s")

    print("-" * len(header))
    print(f"{'GRAND TOTAL':<42} | {grand_total:>5} | {grand_passed:>5} | {grand_failed:>5} | {grand_errors:>5} | {suite_duration:>7.2f}s")
    print("=" * 80)

    if total_failures == 0 and total_errors == 0:
        print("\n🎉 SUCCESS: 100% of E2E tests passed! (0 failures, 0 errors)")
        return 0
    else:
        print(f"\n❌ FAILURE: {total_failures} tests failed, {total_errors} errors encountered.")
        return 1


if __name__ == "__main__":
    sys.exit(main())

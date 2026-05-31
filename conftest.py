"""Root conftest.py — pytest hooks for automatic test failure collection.

Hook: pytest_runtest_makereport
- Captures test failures automatically
- Creates BugRecord and writes to ~/.skillpool/logs/bugs.jsonl
- Enriches with: test name, error type, error message, traceback, timestamp
- Classifies defect_type: TypeError/ValueError -> PARAM_ERROR,
  timeout -> TIMEOUT, assertion -> OUTPUT_INVALID, else -> UNKNOWN
- Severity: P2 for normal failures, P1 for errors (unexpected exceptions), P0 for segfaults

Hook: pytest_sessionfinish
- Prints BugCollector stats at end of test session
"""
from __future__ import annotations

import pytest

from skillpool.monitor.bug_collector import BugCollector, BugSeverity, DefectType


# Module-level collector instance (shared across all test sessions)
_collector: BugCollector | None = None


def _get_collector() -> BugCollector:
    """Get or create the BugCollector instance (lazy init, no file persistence in test mode)."""
    global _collector
    if _collector is None:
        # Use sample_rate=1.0 to capture all, but log_dir=None prevents file writes
        # We only want in-memory collection during tests
        _collector = BugCollector(sample_rate=1.0)
    return _collector


def _classify_error_type(error_type_name: str) -> DefectType:
    """Classify error type string to DefectType.

    Maps pytest error type names to the BugCollector DefectType enum.
    Falls through to BugCollector._classify_exception for known exception types.
    """
    name_lower = error_type_name.lower()
    if name_lower in ("typeerror", "valueerror", "keyerror"):
        return DefectType.PARAM_ERROR
    elif "timeout" in name_lower:
        return DefectType.TIMEOUT
    elif name_lower == "assertionerror":
        return DefectType.OUTPUT_INVALID
    elif name_lower in ("importerror", "modulenotfounderror", "filenotfounderror"):
        return DefectType.DEPENDENCY_MISSING
    elif name_lower in ("permissionerror",):
        return DefectType.PERMISSION_BREACH
    elif name_lower in ("runtimeerror",):
        return DefectType.EXECUTION_FAILURE
    else:
        return DefectType.UNKNOWN


def _severity_from_report(report: pytest.TestReport) -> BugSeverity:
    """Determine severity from the test report.

    P0: segfaults / fatal signals
    P1: errors (unexpected exceptions during call)
    P2: normal assertion failures
    """
    if hasattr(report, "longrepr") and report.longrepr is not None:
        longrepr_str = str(report.longrepr).lower()
        # Segfault or fatal signal
        if any(sig in longrepr_str for sig in ("segfault", "segmentation fault", "signal 11", "sigsegv")):
            return BugSeverity.P0

    # report.outcome is "error" for unexpected exceptions vs "failed" for assertions
    if report.outcome == "error":
        return BugSeverity.P1

    return BugSeverity.P2


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Capture test failures and write to bug collector log.

    This hook runs after each test call phase. When a test fails
    during the 'call' phase, it creates a BugRecord and writes
    it to the JSONL log file.
    """
    outcome = yield
    report = outcome.get_result()

    # Only process failures during the call phase (not setup/teardown)
    if report.when != "call":
        return

    if not report.failed:
        return

    # Extract error information from the report
    error_type = "Unknown"
    error_message = "Test failed (no details available)"
    traceback_str = ""

    if hasattr(report, "longrepr") and report.longrepr is not None:
        longrepr = report.longrepr

        if hasattr(longrepr, "reprcrash") and longrepr.reprcrash is not None:
            crash = longrepr.reprcrash
            error_type = crash.message.split(":")[0].strip() if ":" in crash.message else "Unknown"
            error_message = crash.message.split(":", 1)[1].strip() if ":" in crash.message else crash.message
            traceback_str = str(longrepr)
        else:
            error_type = "Unknown"
            error_message = str(longrepr)
            traceback_str = str(longrepr)

    # Classify defect type from error type name
    defect_type = _classify_error_type(error_type)

    # Determine severity: P0 for segfaults, P1 for errors, P2 for failures
    severity = _severity_from_report(report)

    # Build context with test metadata
    context = {
        "test_name": item.nodeid,
        "error_type": error_type,
    }
    if hasattr(item, "fspath"):
        context["file_path"] = str(item.fspath)
    if hasattr(item, "function") and hasattr(item.function, "__code__"):
        context["line_number"] = item.function.__code__.co_firstlineno

    # Record the bug via the 4-stage pipeline
    collector = _get_collector()
    collector.record(
        severity=severity,
        defect_type=defect_type,
        message=f"[{error_type}] {error_message}",
        context=context,
    )


def pytest_sessionfinish(session, exitstatus):
    """Print BugCollector stats at end of test session."""
    collector = _get_collector()
    stats = collector.get_stats()
    if stats["total"] > 0:
        print(f"\n{'='*60}")
        print("BugCollector Summary")
        print(f"{'='*60}")
        print(f"  Total failures collected: {stats['total']}")
        if stats.get("by_severity"):
            print("  By severity:")
            for sev, count in sorted(stats["by_severity"].items()):
                print(f"    {sev}: {count}")
        if stats.get("by_defect_type"):
            print("  By defect type:")
            for dtype, count in sorted(stats["by_defect_type"].items()):
                print(f"    {dtype}: {count}")
        print(f"{'='*60}")

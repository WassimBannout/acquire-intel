"""Unit tests for change/selector-drift detection (T4.2, ADR-0014, FR-16).

Pure boundaries for `assess_drift` + the runner's status mapping. The end-to-end proof (a real
crawl of the harness `drift` scenario → a `flagged` run) lives in `test_resilience_integration.py`.
"""

from __future__ import annotations

from acquire_intel.acquisition.runner import _run_status
from acquire_intel.analytics.drift import assess_drift

_KW = {"min_entries": 1, "max_unmapped_ratio": 0.5}


def test_no_entries_seen_is_not_drift() -> None:
    # An empty (or blocked) result — nothing to map, judged elsewhere.
    assert assess_drift(0, 0, **_KW) is False


def test_all_entries_mapped_is_not_drift() -> None:
    assert assess_drift(3, 3, **_KW) is False


def test_one_bad_item_on_a_healthy_crawl_is_not_drift() -> None:
    # 1 of 3 unmappable = 33% < 50% — normal skip, not a format change.
    assert assess_drift(3, 2, **_KW) is False


def test_most_entries_unmappable_is_drift() -> None:
    assert assess_drift(3, 0, **_KW) is True  # renamed fields → nothing maps
    assert assess_drift(10, 4, **_KW) is True  # 60% unmappable


def test_min_entries_guards_a_tiny_page() -> None:
    # With a higher floor, a single unmappable entry cannot trip drift.
    assert assess_drift(1, 0, min_entries=2, max_unmapped_ratio=0.5) is False
    assert assess_drift(2, 0, min_entries=2, max_unmapped_ratio=0.5) is True


def test_run_status_flags_a_drifted_run() -> None:
    assert _run_status("finished", 0, 0, drift=True) == "flagged"
    # Drift takes precedence over a volume quarantine (it explains *why* nothing mapped).
    assert _run_status("finished", 0, 1, drift=True) == "flagged"
    # A crash still wins (the crawl didn't finish).
    assert _run_status("closespider_errorcount", 0, 0, drift=True) == "failed"
    # No drift → unchanged behaviour.
    assert _run_status("finished", 0, 0, drift=False) == "success"

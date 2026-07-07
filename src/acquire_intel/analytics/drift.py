"""Change / selector-drift detection (T4.2, ADR-0014, docs/04 §3, FR-16).

A **drifted** crawl is one where a source returned well-formed, item-shaped responses but the
items no longer map to a ``RawProduct`` — the classic symptom of a renamed field or a changed
API/HTML shape. It is distinct from:

* a **ban** (no usable response at all — handled by the ban gate, T3.2), and
* a **legitimately empty** result (no entries seen — not an error), and
* a **volume anomaly** (far fewer items than the source's baseline — quarantined by T3.5; this is
  also how *container*-level HTML drift, where the item container selector itself vanishes and
  nothing is even seen, surfaces).

This module is **pure**: :func:`assess_drift` takes the crawl's cumulative "entries seen vs.
mapped" counts (recorded by :func:`acquire_intel.acquisition.telemetry.record_parse`) and decides
whether the run should be flagged — alert, never crash (FR-16). The runner maps a flagged run to
``status="flagged"`` on the ledger.
"""

from __future__ import annotations


def assess_drift(
    entries_seen: int, entries_mapped: int, *, min_entries: int, max_unmapped_ratio: float
) -> bool:
    """True if a crawl looks like a format change: it saw entries but mapped too few.

    Needs at least ``min_entries`` seen (so a tiny page can't false-positive) and an unmapped
    ratio strictly above ``max_unmapped_ratio``. A crawl that saw nothing (``entries_seen == 0``)
    is *not* drift — that is an empty or blocked result, judged elsewhere.
    """
    if entries_seen < min_entries or entries_seen == 0:
        return False
    unmapped_ratio = (entries_seen - entries_mapped) / entries_seen
    return unmapped_ratio > max_unmapped_ratio

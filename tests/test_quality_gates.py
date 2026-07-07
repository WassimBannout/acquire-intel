"""Unit tests for the pure data-quality gates (T3.5, ADR-0012, docs/04 §3).

The gate functions are pure (no Scrapy, no DB), so every boundary is asserted here directly;
the Scrapy adapters are covered by ``test_quality_pipeline.py``.
"""

from __future__ import annotations

from decimal import Decimal

from scrapy.settings import Settings

from acquire_intel.pipeline.quality import (
    GateThresholds,
    QualityIssue,
    check_continuity,
    check_range,
    check_volume,
)

_T = GateThresholds(
    price_min=Decimal("0"),
    price_max=Decimal("1000"),
    max_jump_ratio=10.0,
    volume_tolerance=0.5,
    volume_min_baseline=5,
)


# --- range -----------------------------------------------------------------------------------


def test_range_accepts_a_plausible_price() -> None:
    assert check_range(Decimal("19.99"), _T) is None


def test_range_accepts_the_boundaries_inclusively() -> None:
    assert check_range(Decimal("0"), _T) is None
    assert check_range(Decimal("1000"), _T) is None


def test_range_rejects_below_min_and_above_max() -> None:
    assert check_range(Decimal("-0.01"), _T) is QualityIssue.OUT_OF_RANGE
    # A classic concatenated-digit scrape error ("1999" glued into "19990000").
    assert check_range(Decimal("19990000"), _T) is QualityIssue.OUT_OF_RANGE


# --- continuity ------------------------------------------------------------------------------


def test_continuity_passes_when_there_is_no_prior() -> None:
    assert check_continuity(Decimal("500"), None, _T) is None


def test_continuity_passes_a_non_positive_prior() -> None:
    # Can't form a ratio against a 0 prior — a first real price is not a "jump".
    assert check_continuity(Decimal("500"), Decimal("0"), _T) is None


def test_continuity_allows_a_change_within_the_ratio() -> None:
    assert check_continuity(Decimal("50"), Decimal("10"), _T) is None  # 5x, under 10x
    assert check_continuity(Decimal("100"), Decimal("10"), _T) is None  # exactly 10x, not > 10


def test_continuity_flags_a_jump_beyond_the_ratio_either_direction() -> None:
    assert check_continuity(Decimal("200"), Decimal("10"), _T) is QualityIssue.DISCONTINUOUS
    assert check_continuity(Decimal("10"), Decimal("200"), _T) is QualityIssue.DISCONTINUOUS


# --- volume ----------------------------------------------------------------------------------


def test_volume_skips_without_a_baseline() -> None:
    assert check_volume(0, None, _T) is None


def test_volume_skips_a_baseline_below_the_minimum() -> None:
    # Baseline 4 < volume_min_baseline 5 — too little history to gate on.
    assert check_volume(1, 4, _T) is None


def test_volume_accepts_a_count_within_tolerance() -> None:
    assert check_volume(10, 10, _T) is None
    assert check_volume(5, 10, _T) is None  # lower bound of ±50%
    assert check_volume(15, 10, _T) is None  # upper bound of ±50%


def test_volume_flags_a_count_outside_tolerance() -> None:
    assert check_volume(4, 10, _T) is QualityIssue.VOLUME_ANOMALY  # too few (partial block/drift)
    assert check_volume(16, 10, _T) is QualityIssue.VOLUME_ANOMALY  # too many
    assert check_volume(0, 10, _T) is QualityIssue.VOLUME_ANOMALY  # total collapse


# --- thresholds from settings ----------------------------------------------------------------


def test_thresholds_from_settings_parses_decimals_and_numbers() -> None:
    settings = Settings(
        {
            "ACQUIRE_QUALITY_PRICE_MIN": "1.50",
            "ACQUIRE_QUALITY_PRICE_MAX": "999999",
            "ACQUIRE_QUALITY_MAX_JUMP_RATIO": 7.5,
            "ACQUIRE_QUALITY_VOLUME_TOLERANCE": 0.25,
            "ACQUIRE_QUALITY_VOLUME_MIN_BASELINE": 8,
        }
    )
    t = GateThresholds.from_settings(settings)
    assert t.price_min == Decimal("1.50")
    assert t.price_max == Decimal("999999")
    assert t.max_jump_ratio == 7.5
    assert t.volume_tolerance == 0.25
    assert t.volume_min_baseline == 8


def test_thresholds_from_settings_uses_defaults_when_absent() -> None:
    t = GateThresholds.from_settings(Settings({}))
    assert t.price_min == Decimal("0")
    assert t.price_max == Decimal("1000000")
    assert t.volume_min_baseline == 5

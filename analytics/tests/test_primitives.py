"""
Sanity tests for analytical primitives. Not exhaustive
"""

from pathlib import Path
import pytest
import pandas as pd

from core.data_loader import load_unified_data
from analytics.primitives import (
    top_n_zones,
    compare_segments,
    trend,
    aggregate,
    multivariable_filter,
    growth_drivers,
)


@pytest.fixture(scope="module")
def df() -> pd.DataFrame:
    return load_unified_data(
        metrics_path=Path("data/metrics.csv"),
        orders_path=Path("data/orders.csv"),
    )


def test_top_n_returns_expected_shape(df):
    out = top_n_zones(df, metric="Lead Penetration", n=5)
    assert len(out["rows"]) == 5
    assert out["rows"][0]["rank"] == 1
    # Values must be sorted correctly (higher_is_better = descending)
    values = [r["value"] for r in out["rows"]]
    assert values == sorted(values, reverse=True)


def test_top_n_direction_aware_for_lower_is_better(df):
    out = top_n_zones(df, metric="Restaurants Markdowns / GMV", n=5)
    values = [r["value"] for r in out["rows"]]
    # lower_is_better means the "top" zones have the LOWEST values
    assert values == sorted(values, reverse=False)


def test_top_n_invalid_metric_raises(df):
    with pytest.raises(ValueError):
        top_n_zones(df, metric="Nonexistent Metric", n=5)


def test_compare_segments_returns_rows(df):
    out = compare_segments(
        df,
        metric="Perfect Orders",
        segment_by="ZONE_TYPE",
        segment_values=["Wealthy", "Non Wealthy"],
        country="MX",
    )
    assert len(out["rows"]) >= 1
    assert "delta_top_two" in out["meta"]


def test_trend_returns_weeks_in_order(df):
    out = trend(df, metric="Lead Penetration", n_weeks=8)
    weeks = [r["week_offset"] for r in out["rows"]]
    # Oldest first, so descending week_offset
    assert weeks == sorted(weeks, reverse=True)


def test_aggregate_by_country(df):
    out = aggregate(df, metric="Lead Penetration", group_by="COUNTRY")
    assert len(out["rows"]) >= 5  # we have 9 countries but some may lack data
    assert all(r["n_zones"] > 0 for r in out["rows"])


def test_multivariable_filter_returns_structure(df):
    out = multivariable_filter(
        df,
        high_metric="Lead Penetration",
        low_metric="Perfect Orders",
    )
    assert "rows" in out
    assert "n_zones_flagged" in out["meta"]


def test_growth_drivers_returns_structure(df):
    out = growth_drivers(df, target_metric="Orders", n_weeks=5, top_n_growing=3)
    assert len(out["rows"]) <= 3
    if out["rows"]:
        assert "candidate_drivers" in out["rows"][0]

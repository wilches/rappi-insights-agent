"""Sanity tests for detectors. Just ensure they run and return reasonable shapes."""

from pathlib import Path
import pytest
import pandas as pd

from core.data_loader import load_unified_data
from analytics.detectors import (
    detect_anomalies,
    detect_deteriorating_trends,
    detect_peer_divergence,
    detect_correlations,
    detect_opportunities,
    run_all_detectors,
)


@pytest.fixture(scope="module")
def df() -> pd.DataFrame:
    return load_unified_data(
        metrics_path=Path("data/metrics.csv"),
        orders_path=Path("data/orders.csv"),
    )


def test_anomalies_runs_and_returns_list(df):
    findings = detect_anomalies(df)
    assert isinstance(findings, list)
    if findings:
        assert "severity" in findings[0]
        assert findings[0]["severity"] >= findings[-1]["severity"]


def test_deteriorating_trends_runs(df):
    findings = detect_deteriorating_trends(df)
    assert isinstance(findings, list)
    for f in findings:
        assert f["category"] == "deteriorating_trend"
        assert f["weeks_consecutive"] >= 3


def test_peer_divergence_runs(df):
    findings = detect_peer_divergence(df)
    assert isinstance(findings, list)
    for f in findings:
        assert "peer_median" in f


def test_correlations_runs(df):
    findings = detect_correlations(df)
    for f in findings:
        assert -1 <= f["pearson_r"] <= 1
        assert abs(f["pearson_r"]) >= 0.5


def test_opportunities_runs(df):
    findings = detect_opportunities(df)
    assert isinstance(findings, list)
    assert len(findings) <= 20


def test_run_all_returns_all_categories(df):
    out = run_all_detectors(df)
    for key in ["anomalies", "deteriorating_trends", "peer_divergence", "correlations", "opportunities"]:
        assert key in out
        assert isinstance(out[key], list)

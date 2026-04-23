"""
Insights engine: rank and select findings for the executive report.

Separation of concerns:
    - detectors.py produces raw findings (possibly hundreds)
    - engine.py ranks them by business relevance and keeps the top K
    - report_generator.py turns the selected findings into narrative + markdown
"""

from __future__ import annotations

import pandas as pd
import logging

from analytics.detectors import run_all_detectors
from core.metric_dictionary import get_metric

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Business priority weights
# ---------------------------------------------------------------------------

# Metrics are not equally important. Gross Profit UE moves money directly;
# a conversion CVR is one step removed. We weight findings by the metric's
# business priority when ranking, so the final report surfaces what matters
# to the SP&A and Operations teams.

METRIC_PRIORITY: dict[str, float] = {
    "Gross Profit UE": 1.5,
    "Perfect Orders": 1.3,
    "Orders": 1.3,
    "Restaurants Markdowns / GMV": 1.2,
    "Lead Penetration": 1.1,
    "Pro Adoption (Last Week Status)": 1.0,
    "Turbo Adoption": 1.0,
    "MLTV Top Verticals Adoption": 1.0,
    "% PRO Users Who Breakeven": 1.0,
    "Non-Pro PTC > OP": 0.9,
    "% Restaurants Sessions With Optimal Assortment": 0.8,
    "Restaurants SS > ATC CVR": 0.8,
    "Restaurants SST > SS CVR": 0.8,
    "Retail SST > SS CVR": 0.8,
}

# Category weights: anomalies and deterioration are more urgent than
# opportunities; correlations are informational.
CATEGORY_PRIORITY: dict[str, float] = {
    "deteriorating_trend": 1.5,
    "anomaly": 1.3,
    "peer_divergence": 1.1,
    "opportunity": 0.9,
    "correlation": 0.8,
}

# How many findings per category to keep in the final report
TOP_K_PER_CATEGORY = {
    "anomalies": 5,
    "deteriorating_trends": 5,
    "peer_divergence": 5,
    "correlations": 3,
    "opportunities": 5,
}


def _business_weighted_severity(finding: dict) -> float:
    """Multiply raw severity by metric and category priority weights."""
    metric = finding.get("metric") or finding.get("metric_a", "")
    category = finding.get("category", "")

    metric_weight = METRIC_PRIORITY.get(metric, 1.0)
    category_weight = CATEGORY_PRIORITY.get(category, 1.0)

    return finding.get("severity", 0.0) * metric_weight * category_weight


def rank_and_select_findings(
    all_findings: dict[str, list[dict]],
    top_k_per_category: dict[str, int] | None = None,
) -> dict[str, list[dict]]:
    """
    Take raw findings from run_all_detectors and produce a curated top-K
    per category, ranked by business-weighted severity.
    """
    if top_k_per_category is None:
        top_k_per_category = TOP_K_PER_CATEGORY

    selected: dict[str, list[dict]] = {}
    for category, findings in all_findings.items():
        # Recompute severity with business weights, keep both
        for f in findings:
            f["business_severity"] = _business_weighted_severity(f)

        ranked = sorted(findings, key=lambda f: f["business_severity"], reverse=True)
        k = top_k_per_category.get(category, 5)
        selected[category] = ranked[:k]

    logger.info(
        "Selected findings per category: "
        + ", ".join(f"{k}={len(v)}" for k, v in selected.items())
    )
    return selected


def generate_insights(df: pd.DataFrame) -> dict[str, list[dict]]:
    """Main entry point: run all detectors, rank, and return top findings."""
    raw = run_all_detectors(df)
    selected = rank_and_select_findings(raw)
    return selected

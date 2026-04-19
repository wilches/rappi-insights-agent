"""
Detectors — proactive analysis functions that surface anomalies, trends,
benchmarks, and correlations without the user asking.

Each detector returns a list of "findings", where a finding is a structured
dict describing something notable about a zone-metric combination. The
insights engine ranks these findings by severity and feeds the top-K to
the LLM for narrative generation.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from core.metric_dictionary import get_metric, METRICS, all_metric_names


# ---------------------------------------------------------------------------
# Tuning parameters (would be configurable in production)
# ---------------------------------------------------------------------------

# A zone must handle at least this many orders in the current week to be
# eligible for detection. Filters out tiny zones whose percentage changes
# are statistical noise rather than signal.
MIN_ORDERS_FOR_DETECTION = 500

# Anomaly: week-over-week change threshold, in absolute terms for ratios.
# A jump of 0.10 (10pp) in Perfect Orders week-over-week is anomalous.
ANOMALY_WOW_THRESHOLD_RATIO = 0.10

# Anomaly: week-over-week percentage change threshold, for count/currency.
ANOMALY_WOW_THRESHOLD_PCT = 0.15

# Deteriorating trend: minimum consecutive weeks of movement in the wrong
# direction to flag a zone.
DETERIORATION_MIN_WEEKS = 3

# Benchmarking: minimum gap (as a fraction of peer median) between a zone
# and its peers to flag divergence.
BENCHMARK_DIVERGENCE_THRESHOLD = 0.20  # 20% worse than peer median


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _zones_with_enough_volume(df: pd.DataFrame, min_orders: int) -> set:
    """Return the (country, city, zone) tuples that have at least `min_orders`
    in the current week. Used to filter out statistically unreliable zones.
    """
    current_orders = df[
        (df["METRIC"] == "Orders") & (df["week_offset"] == 0)
    ]
    eligible = current_orders[current_orders["value"] >= min_orders]
    return set(
        eligible.apply(
            lambda r: (r["COUNTRY"], r["CITY"], r["ZONE"]),
            axis=1,
        )
    )


def _pivot_zone_metric_week(
    df: pd.DataFrame,
    metric: str,
) -> pd.DataFrame:
    """
    Pivot into a (zone) x (week_offset) shape for a single metric.
    Columns are 0..8 (week_offset), index is (COUNTRY, CITY, ZONE).
    """
    sub = df[df["METRIC"] == metric]
    pivot = sub.pivot_table(
        index=["COUNTRY", "CITY", "ZONE"],
        columns="week_offset",
        values="value",
        aggfunc="first",
    )
    return pivot


# ---------------------------------------------------------------------------
# Detector 1: week-over-week anomalies
# ---------------------------------------------------------------------------

def detect_anomalies(
    df: pd.DataFrame,
    threshold_ratio: float = ANOMALY_WOW_THRESHOLD_RATIO,
    threshold_pct: float = ANOMALY_WOW_THRESHOLD_PCT,
    min_orders: int = MIN_ORDERS_FOR_DETECTION,
) -> list[dict]:
    """
    Detect zone-metric pairs with dramatic week-over-week (L0W vs L1W) change.

    Direction-aware: a metric that dropped where it should have risen is
    classified as "deterioration"; dropped where it should have dropped is
    "improvement". The severity is the magnitude of change.
    """
    eligible_zones = _zones_with_enough_volume(df, min_orders)
    findings: list[dict] = []

    for metric_name in all_metric_names():
        if metric_name == "Orders":
            continue  # Orders spikes handled separately in growth detector

        meta = get_metric(metric_name)
        pivot = _pivot_zone_metric_week(df, metric_name)

        # Need both L0W and L1W values
        if 0 not in pivot.columns or 1 not in pivot.columns:
            continue

        pivot = pivot.dropna(subset=[0, 1])

        for (country, city, zone), row in pivot.iterrows():
            if (country, city, zone) not in eligible_zones:
                continue

            v_now = row[0]
            v_prev = row[1]

            # Choose threshold based on unit
            if meta.unit in ("ratio", "percentage"):
                abs_change = v_now - v_prev
                if abs(abs_change) < threshold_ratio:
                    continue
                change_magnitude = abs(abs_change)
                pct_change = (abs_change / v_prev * 100) if v_prev != 0 else None
            else:  # count, currency
                if v_prev == 0:
                    continue
                pct_change = (v_now - v_prev) / v_prev
                if abs(pct_change) < threshold_pct:
                    continue
                change_magnitude = abs(pct_change)
                abs_change = v_now - v_prev
                pct_change = pct_change * 100

            # Classify direction of change relative to metric's goodness
            moved_favorably = (
                (abs_change > 0 and meta.is_higher_better)
                or (abs_change < 0 and not meta.is_higher_better)
            )
            nature = "improvement" if moved_favorably else "deterioration"

            findings.append({
                "category": "anomaly",
                "subtype": nature,
                "country": country,
                "city": city,
                "zone": zone,
                "metric": metric_name,
                "previous_value": float(v_prev),
                "current_value": float(v_now),
                "previous_formatted": meta.format_value(float(v_prev)),
                "current_formatted": meta.format_value(float(v_now)),
                "absolute_change": float(abs_change),
                "pct_change": float(pct_change) if pct_change is not None else None,
                "severity": float(change_magnitude),  # used for ranking
            })

    # Rank by severity, most severe first
    findings.sort(key=lambda f: f["severity"], reverse=True)
    return findings


# ---------------------------------------------------------------------------
# Detector 2: sustained deteriorating trends
# ---------------------------------------------------------------------------

def detect_deteriorating_trends(
    df: pd.DataFrame,
    min_weeks: int = DETERIORATION_MIN_WEEKS,
    min_orders: int = MIN_ORDERS_FOR_DETECTION,
) -> list[dict]:
    """
    Flag zones where a metric has moved in the unfavorable direction for
    `min_weeks` consecutive weeks ending at the current week.

    Direction is determined by the metric dictionary. For Perfect Orders,
    consecutive drops are flagged. For Markdowns, consecutive rises are flagged.
    """
    eligible_zones = _zones_with_enough_volume(df, min_orders)
    findings: list[dict] = []

    for metric_name in all_metric_names():
        if metric_name == "Orders":
            continue

        meta = get_metric(metric_name)
        pivot = _pivot_zone_metric_week(df, metric_name)

        # Need at least min_weeks of contiguous data ending at week 0
        needed_weeks = list(range(min_weeks))  # e.g., [0, 1, 2]
        if not all(w in pivot.columns for w in needed_weeks):
            continue
        pivot = pivot.dropna(subset=needed_weeks)

        for (country, city, zone), row in pivot.iterrows():
            if (country, city, zone) not in eligible_zones:
                continue

            # Walk weeks from oldest-in-window to newest (L{min_weeks-1}W → L0W)
            # and check each step moves in the unfavorable direction.
            values = [row[w] for w in range(min_weeks - 1, -1, -1)]

            diffs = np.diff(values)
            if meta.is_higher_better:
                # Deterioration = each step decreased
                consistent = np.all(diffs < 0)
            else:
                # Deterioration = each step increased
                consistent = np.all(diffs > 0)

            if not consistent:
                continue

            total_change = values[-1] - values[0]
            first_val = values[0]
            pct_change = (total_change / first_val * 100) if first_val != 0 else None

            findings.append({
                "category": "deteriorating_trend",
                "country": country,
                "city": city,
                "zone": zone,
                "metric": metric_name,
                "weeks_consecutive": min_weeks,
                "first_value": float(values[0]),
                "last_value": float(values[-1]),
                "first_formatted": meta.format_value(float(values[0])),
                "last_formatted": meta.format_value(float(values[-1])),
                "total_change": float(total_change),
                "pct_change": float(pct_change) if pct_change is not None else None,
                "severity": float(abs(total_change)),
            })

    findings.sort(key=lambda f: f["severity"], reverse=True)
    return findings


# ---------------------------------------------------------------------------
# Detector 3: peer benchmarking
# ---------------------------------------------------------------------------

def detect_peer_divergence(
    df: pd.DataFrame,
    peer_dimension: str = "ZONE_TYPE",  # or "ZONE_PRIORITIZATION"
    divergence_threshold: float = BENCHMARK_DIVERGENCE_THRESHOLD,
    min_orders: int = MIN_ORDERS_FOR_DETECTION,
) -> list[dict]:
    """
    For each zone, compare its performance against the median of peer zones
    (same country + same `peer_dimension` value) and flag those that
    materially underperform their peer group.

    "Underperform" = worse than peer median by at least `divergence_threshold`
    (relative gap). Direction-aware.
    """
    eligible_zones = _zones_with_enough_volume(df, min_orders)
    findings: list[dict] = []

    current = df[df["week_offset"] == 0]

    for metric_name in all_metric_names():
        if metric_name == "Orders":
            continue

        meta = get_metric(metric_name)
        metric_df = current[current["METRIC"] == metric_name].copy()
        if metric_df.empty:
            continue

        # Compute peer median per (COUNTRY, peer_dimension)
        peer_stats = (
            metric_df.groupby(["COUNTRY", peer_dimension])["value"]
            .median()
            .reset_index()
            .rename(columns={"value": "peer_median"})
        )

        merged = metric_df.merge(
            peer_stats, on=["COUNTRY", peer_dimension], how="left"
        )
        merged = merged.dropna(subset=["peer_median"])

        for _, r in merged.iterrows():
            if (r["COUNTRY"], r["CITY"], r["ZONE"]) not in eligible_zones:
                continue

            v = r["value"]
            peer = r["peer_median"]
            if peer == 0:
                continue

            relative_gap = (v - peer) / abs(peer)

            # Underperformance is "gap in the wrong direction"
            underperforming = (
                (meta.is_higher_better and v < peer)
                or (not meta.is_higher_better and v > peer)
            )
            if not underperforming:
                continue
            if abs(relative_gap) < divergence_threshold:
                continue

            findings.append({
                "category": "peer_divergence",
                "country": r["COUNTRY"],
                "city": r["CITY"],
                "zone": r["ZONE"],
                "peer_group": f"{r['COUNTRY']} / {r[peer_dimension]}",
                "peer_dimension": peer_dimension,
                "metric": metric_name,
                "zone_value": float(v),
                "peer_median": float(peer),
                "zone_formatted": meta.format_value(float(v)),
                "peer_formatted": meta.format_value(float(peer)),
                "relative_gap": float(relative_gap),
                "severity": float(abs(relative_gap)),
            })

    findings.sort(key=lambda f: f["severity"], reverse=True)
    return findings


# ---------------------------------------------------------------------------
# Detector 4: cross-metric correlations
# ---------------------------------------------------------------------------

def detect_correlations(
    df: pd.DataFrame,
    min_abs_correlation: float = 0.5,
) -> list[dict]:
    """
    At the country level, compute Pearson correlations between each pair of
    metrics (across zones within the country, current week) and return
    pairs with |r| above the threshold.

    Example finding: "In MX, zones with high Lead Penetration also tend to
    have high Pro Adoption (r = 0.71)."
    """
    findings: list[dict] = []
    current = df[df["week_offset"] == 0].copy()

    metrics = [m for m in all_metric_names() if m != "Orders"]

    for country in current["COUNTRY"].unique():
        country_df = current[current["COUNTRY"] == country]
        wide = country_df.pivot_table(
            index=["CITY", "ZONE"],
            columns="METRIC",
            values="value",
            aggfunc="first",
        )

        available = [m for m in metrics if m in wide.columns]
        if len(available) < 2:
            continue

        wide = wide[available].dropna()
        if len(wide) < 10:
            continue  # Not enough zones in this country for reliable correlation

        corr = wide.corr(method="pearson")

        seen_pairs = set()
        for m1 in available:
            for m2 in available:
                if m1 >= m2:
                    continue  # symmetric — only take upper triangle
                pair_key = (m1, m2)
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                r = corr.loc[m1, m2]
                if pd.isna(r) or abs(r) < min_abs_correlation:
                    continue

                findings.append({
                    "category": "correlation",
                    "country": country,
                    "metric_a": m1,
                    "metric_b": m2,
                    "pearson_r": float(r),
                    "n_zones": int(len(wide)),
                    "severity": float(abs(r)),
                })

    findings.sort(key=lambda f: f["severity"], reverse=True)
    return findings


# ---------------------------------------------------------------------------
# Detector 5: general opportunities (high-performing zones, proxies for scale)
# ---------------------------------------------------------------------------

def detect_opportunities(
    df: pd.DataFrame,
    min_orders: int = MIN_ORDERS_FOR_DETECTION,
    top_percentile: float = 0.90,
) -> list[dict]:
    """
    Flag zones that are in the top percentile on a favorable metric —
    candidates for expansion, case studies, or best-practice extraction.
    """
    eligible_zones = _zones_with_enough_volume(df, min_orders)
    findings: list[dict] = []

    current = df[df["week_offset"] == 0]

    for metric_name in all_metric_names():
        if metric_name == "Orders":
            continue
        meta = get_metric(metric_name)
        metric_df = current[current["METRIC"] == metric_name].copy()
        if metric_df.empty:
            continue

        if meta.is_higher_better:
            threshold = metric_df["value"].quantile(top_percentile)
            top_zones = metric_df[metric_df["value"] >= threshold]
        else:
            threshold = metric_df["value"].quantile(1 - top_percentile)
            top_zones = metric_df[metric_df["value"] <= threshold]

        for _, r in top_zones.iterrows():
            if (r["COUNTRY"], r["CITY"], r["ZONE"]) not in eligible_zones:
                continue
            findings.append({
                "category": "opportunity",
                "country": r["COUNTRY"],
                "city": r["CITY"],
                "zone": r["ZONE"],
                "metric": metric_name,
                "value": float(r["value"]),
                "value_formatted": meta.format_value(float(r["value"])),
                "percentile": top_percentile,
                "severity": float(abs(r["value"] - threshold) / abs(threshold) if threshold else 0),
            })

    # Only keep the top 20 opportunities — otherwise this floods the report
    findings.sort(key=lambda f: f["severity"], reverse=True)
    return findings[:20]


# ---------------------------------------------------------------------------
# Orchestrator: run everything and return categorized findings
# ---------------------------------------------------------------------------

def run_all_detectors(df: pd.DataFrame) -> dict:
    """
    Run every detector and return the results grouped by category.
    This is the function the insights engine calls.
    """
    return {
        "anomalies": detect_anomalies(df),
        "deteriorating_trends": detect_deteriorating_trends(df),
        "peer_divergence": detect_peer_divergence(df),
        "correlations": detect_correlations(df),
        "opportunities": detect_opportunities(df),
    }

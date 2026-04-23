"""
Analytical primitives for the Rappi operations intelligence system.

These are the core functions that answer every class of business question
identified in the PDF. They are pure Python — no LLM dependency, no side
effects. The chat agent and the insights engine both call them.

Design principles:
    1. Every function takes a unified long-format DataFrame (from data_loader).
    2. Every function consults the metric dictionary for business semantics
       (direction, aggregation, formatting).
    3. Every function returns a structured dict with "rows" (for rendering)
       and "meta" (for LLM context / charts).
    4. Inputs are validated loudly — invalid metric name = immediate error.
"""

from __future__ import annotations

import pandas as pd
from typing import Literal

from core.metric_dictionary import get_metric, all_metric_names, METRICS


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _validate_metric(metric: str) -> None:
    if metric not in METRICS:
        raise ValueError(
            f"Unknown metric '{metric}'. "
            f"Known metrics: {all_metric_names()}"
        )


def _filter_base(
    df: pd.DataFrame,
    metric: str,
    week_offset: int = 0,
    country: str | None = None,
    city: str | None = None,
    zone_type: str | None = None,
    zone_prioritization: str | None = None,
) -> pd.DataFrame:
    """
    Apply the standard set of filters used across primitives.
    Returns the subset of the dataframe matching all given constraints.
    """
    mask = (df["METRIC"] == metric) & (df["week_offset"] == week_offset)
    if country:
        mask &= df["COUNTRY"].str.upper() == country.upper()
    if city:
        mask &= df["CITY"].str.lower() == city.lower()
    if zone_type:
        mask &= df["ZONE_TYPE"].str.lower() == zone_type.lower()
    if zone_prioritization:
        mask &= df["ZONE_PRIORITIZATION"].str.lower() == zone_prioritization.lower()
    return df.loc[mask].copy()


def _weighted_mean_by_orders(
    df: pd.DataFrame,
    metric: str,
    full_df: pd.DataFrame,
    group_by: list[str],
    week_offset: int = 0,
) -> pd.DataFrame:
    """
    Compute a mean of `metric` weighted by the Orders volume in the same
    (zone, week). Required for quality metrics like Perfect Orders where
    small zones should not distort the country-level number.
    """
    # Join orders for the same week onto the metric rows
    orders = full_df[
        (full_df["METRIC"] == "Orders") & (full_df["week_offset"] == week_offset)
    ][["COUNTRY", "CITY", "ZONE", "value"]].rename(columns={"value": "_orders"})

    merged = df.merge(
        orders,
        on=["COUNTRY", "CITY", "ZONE"],
        how="left",
    )
    # Zones with no orders data get weight 0 (effectively excluded from mean)
    merged["_orders"] = merged["_orders"].fillna(0)

    def _wmean(sub: pd.DataFrame) -> float:
        w = sub["_orders"]
        if w.sum() == 0:
            return sub["value"].mean()  # fallback to simple mean
        return (sub["value"] * w).sum() / w.sum()

    result = (
        merged.groupby(group_by, dropna=False)
        .apply(_wmean, include_groups=False)
        .reset_index(name="value")
    )
    return result


# ---------------------------------------------------------------------------
# Primitive 1: top_n_zones
# ---------------------------------------------------------------------------

def top_n_zones(
    df: pd.DataFrame,
    metric: str,
    n: int = 5,
    week_offset: int = 0,
    country: str | None = None,
    ascending: bool | None = None,
    zone_type: str | None = None,
    zone_prioritization: str | None = None,
) -> dict:
    """
    Return the top-N zones by a metric.

    If `ascending` is None, direction is taken from the metric dictionary:
        higher_is_better -> descending (actual "top")
        lower_is_better  -> ascending  (still the "top" — e.g., least markdowns)

    To query "worst zones", pass ascending in the opposite direction, or
    use the keyword "problematic" upstream in the agent.
    """
    _validate_metric(metric)
    meta = get_metric(metric)

    if ascending is None:
        ascending = not meta.is_higher_better

    subset = _filter_base(
        df, metric, week_offset, country, zone_type=zone_type,
        zone_prioritization=zone_prioritization,
    )
    if subset.empty:
        return {
            "rows": [],
            "meta": {
                "metric": metric,
                "week_offset": week_offset,
                "filters": {"country": country, "zone_type": zone_type},
                "note": "No data found for the given filters.",
            },
        }

    ranked = subset.sort_values("value", ascending=ascending).head(n)
    rows = [
        {
            "rank": i + 1,
            "country": row.COUNTRY,
            "city": row.CITY,
            "zone": row.ZONE,
            "value": float(row.value),
            "value_formatted": meta.format_value(float(row.value)),
        }
        for i, row in enumerate(ranked.itertuples())
    ]
    return {
        "rows": rows,
        "meta": {
            "metric": metric,
            "direction": meta.direction,
            "unit": meta.unit,
            "week_offset": week_offset,
            "n": n,
            "total_zones_in_scope": int(len(subset)),
            "filters": {"country": country, "zone_type": zone_type},
        },
    }


# ---------------------------------------------------------------------------
# Primitive 2: compare_segments
# ---------------------------------------------------------------------------

def compare_segments(
    df: pd.DataFrame,
    metric: str,
    segment_by: Literal["ZONE_TYPE", "ZONE_PRIORITIZATION", "COUNTRY"],
    segment_values: list[str] | None = None,
    week_offset: int | None = 0,
    weeks_window: int | None = None,
    country: str | None = None,
) -> dict:
    """
    Compare the average of a metric across two or more segments.

    Either pass `week_offset` (single week, default current) OR `weeks_window`
    (average across the last N weeks). `weeks_window` takes precedence if both
    are given — it's the richer, less-noisy measure.
    """
    _validate_metric(metric)
    meta = get_metric(metric)

    # Build the time-filtered base
    if weeks_window is not None and weeks_window > 1:
        time_mask = df["week_offset"] < weeks_window
        time_label = f"last {weeks_window} weeks (avg)"
    else:
        time_mask = df["week_offset"] == (week_offset or 0)
        time_label = f"L{week_offset or 0}W"

    base_mask = (df["METRIC"] == metric) & time_mask
    if country:
        base_mask &= df["COUNTRY"].str.upper() == country.upper()
    subset = df.loc[base_mask].copy()

    if segment_values is not None:
        subset = subset[subset[segment_by].str.lower().isin(
            [v.lower() for v in segment_values]
        )]

    if subset.empty:
        return {
            "rows": [],
            "meta": {
                "metric": metric,
                "segment_by": segment_by,
                "note": "No data for the given filters.",
            },
        }

    # Aggregate per segment using the metric's declared strategy
    if meta.aggregation == "weighted_mean_by_orders":
        # When averaging across weeks, we weight within each week and mean across.
        if weeks_window is not None and weeks_window > 1:
            per_week = []
            for w in range(weeks_window):
                w_subset = subset[subset["week_offset"] == w]
                if w_subset.empty:
                    continue
                wk_agg = _weighted_mean_by_orders(
                    w_subset, metric, df, group_by=[segment_by], week_offset=w
                )
                per_week.append(wk_agg)
            if per_week:
                agg = pd.concat(per_week).groupby(segment_by, as_index=False)["value"].mean()
            else:
                agg = pd.DataFrame(columns=[segment_by, "value"])
        else:
            agg = _weighted_mean_by_orders(
                subset, metric, df, group_by=[segment_by], week_offset=week_offset or 0,
            )
    elif meta.aggregation == "sum":
        agg = subset.groupby(segment_by)["value"].sum().reset_index()
    else:  # mean
        agg = subset.groupby(segment_by)["value"].mean().reset_index()

    counts = subset.groupby(segment_by).size().reset_index(name="n_zones")
    agg = agg.merge(counts, on=segment_by)

    rows = [
        {
            "segment": str(row[segment_by]),
            "value": float(row["value"]),
            "value_formatted": meta.format_value(float(row["value"])),
            "value_precise": float(row["value"]),  # extra precision for LLM reasoning
            "n_zones": int(row["n_zones"]),
        }
        for _, row in agg.iterrows()
    ]
    rows.sort(key=lambda r: r["value"], reverse=meta.is_higher_better)

    delta = None
    if len(rows) >= 2:
        delta = rows[0]["value"] - rows[1]["value"]

    return {
        "rows": rows,
        "meta": {
            "metric": metric,
            "segment_by": segment_by,
            "aggregation": meta.aggregation,
            "time_scope": time_label,
            "weeks_window": weeks_window,
            "week_offset": week_offset if weeks_window is None else None,
            "country": country,
            "delta_top_two": delta,
        },
    }


# ---------------------------------------------------------------------------
# Primitive 3: trend
# ---------------------------------------------------------------------------

def trend(
    df: pd.DataFrame,
    metric: str,
    zone: str | None = None,
    country: str | None = None,
    n_weeks: int = 8,
) -> dict:
    """
    Time series of a metric over the last `n_weeks`. Scope defaults to all
    zones in the filtered set; pass `zone` for a single zone, or `country`
    for a country-level aggregate.
    """
    _validate_metric(metric)
    meta = get_metric(metric)

    mask = df["METRIC"] == metric
    if zone:
        mask &= df["ZONE"].str.lower() == zone.lower()
    if country:
        mask &= df["COUNTRY"].str.upper() == country.upper()
    mask &= df["week_offset"] < n_weeks

    subset = df.loc[mask].copy()
    if subset.empty:
        return {
            "rows": [],
            "meta": {"metric": metric, "zone": zone, "note": "No data."},
        }

    if zone:
        # Single-zone trend — one value per week
        agg = subset.groupby("week_offset")["value"].mean().reset_index()
    else:
        # Multi-zone — aggregate per week using metric's strategy
        if meta.aggregation == "weighted_mean_by_orders":
            agg = _weighted_mean_by_orders(
                subset, metric, df, group_by=["week_offset"], week_offset=None,
            )  # type: ignore  # aggregator iterates weeks itself
            # Fallback: do it per week
            weekly = []
            for w in sorted(subset["week_offset"].unique()):
                wk_subset = subset[subset["week_offset"] == w]
                val = _weighted_mean_by_orders(
                    wk_subset, metric, df, group_by=[], week_offset=int(w),
                )
                if not val.empty:
                    weekly.append({"week_offset": int(w), "value": float(val["value"].iloc[0])})
            agg = pd.DataFrame(weekly)
        elif meta.aggregation == "sum":
            agg = subset.groupby("week_offset")["value"].sum().reset_index()
        else:
            agg = subset.groupby("week_offset")["value"].mean().reset_index()

    agg = agg.sort_values("week_offset", ascending=False)

    rows = [
        {
            "week_offset": int(r["week_offset"]),
            "week_label": f"L{int(r['week_offset'])}W",
            "value": float(r["value"]),
            "value_formatted": meta.format_value(float(r["value"])),
        }
        for _, r in agg.iterrows()
    ]


    # Simple trend summary: last week vs first week
    summary = None
    if len(rows) >= 2:
        first, last = rows[0]["value"], rows[-1]["value"]
        change = last - first
        pct_change = (change / first * 100) if first != 0 else None
        summary = {
            "first_week_label": rows[0]["week_label"],
            "last_week_label": rows[-1]["week_label"],
            "first_value": first,
            "last_value": last,
            "absolute_change": change,
            "pct_change": pct_change,
        }

    return {
        "rows": rows,
        "meta": {
            "metric": metric,
            "zone": zone,
            "country": country,
            "direction": meta.direction,
            "unit": meta.unit,
            "summary": summary,
        },
    }


# ---------------------------------------------------------------------------
# Primitive 4: aggregate
# ---------------------------------------------------------------------------

def aggregate(
    df: pd.DataFrame,
    metric: str,
    group_by: Literal["COUNTRY", "CITY", "ZONE_TYPE", "ZONE_PRIORITIZATION"],
    week_offset: int = 0,
) -> dict:
    """
    Group-by aggregation. E.g., "average Lead Penetration per country".
    Aggregation strategy comes from the metric dictionary.
    """
    _validate_metric(metric)
    meta = get_metric(metric)

    subset = _filter_base(df, metric, week_offset)
    if subset.empty:
        return {"rows": [], "meta": {"metric": metric, "note": "No data."}}

    if meta.aggregation == "weighted_mean_by_orders":
        agg = _weighted_mean_by_orders(
            subset, metric, df, group_by=[group_by], week_offset=week_offset,
        )
    elif meta.aggregation == "sum":
        agg = subset.groupby(group_by)["value"].sum().reset_index()
    else:
        agg = subset.groupby(group_by)["value"].mean().reset_index()

    counts = subset.groupby(group_by).size().reset_index(name="n_zones")
    agg = agg.merge(counts, on=group_by)
    agg = agg.sort_values("value", ascending=not meta.is_higher_better)

    rows = [
        {
            "group": str(row[group_by]),
            "value": float(row["value"]),
            "value_formatted": meta.format_value(float(row["value"])),
            "n_zones": int(row["n_zones"]),
        }
        for _, row in agg.iterrows()
    ]
    return {
        "rows": rows,
        "meta": {
            "metric": metric,
            "group_by": group_by,
            "aggregation": meta.aggregation,
            "week_offset": week_offset,
        },
    }


# ---------------------------------------------------------------------------
# Primitive 5: multivariable_filter — "high X, low Y" type queries
# ---------------------------------------------------------------------------

def multivariable_filter(
    df: pd.DataFrame,
    high_metric: str,
    low_metric: str,
    week_offset: int = 0,
    top_percentile: float = 0.75,
    bottom_percentile: float = 0.25,
    country: str | None = None,
) -> dict:
    """
    Return zones that are in the top percentile of `high_metric` AND the
    bottom percentile of `low_metric`. Direction-aware: "high" uses the
    metric's definition of good; "low" uses the definition of bad.

    Example: zones with high Lead Penetration but low Perfect Order.
    """
    _validate_metric(high_metric)
    _validate_metric(low_metric)

    high_meta = get_metric(high_metric)
    low_meta = get_metric(low_metric)

    mask = (df["week_offset"] == week_offset)
    if country:
        mask &= df["COUNTRY"].str.upper() == country.upper()

    wide = (
        df[mask]
        .pivot_table(
            index=["COUNTRY", "CITY", "ZONE"],
            columns="METRIC",
            values="value",
            aggfunc="first",
        )
        .reset_index()
    )

    if high_metric not in wide.columns or low_metric not in wide.columns:
        return {"rows": [], "meta": {"note": "One of the metrics has no data."}}

    wide = wide.dropna(subset=[high_metric, low_metric])

    # "High" threshold: what counts as a good score for high_metric
    if high_meta.is_higher_better:
        high_threshold = wide[high_metric].quantile(top_percentile)
        high_mask = wide[high_metric] >= high_threshold
    else:
        high_threshold = wide[high_metric].quantile(1 - top_percentile)
        high_mask = wide[high_metric] <= high_threshold

    # "Low" threshold: what counts as a bad score for low_metric
    if low_meta.is_higher_better:
        low_threshold = wide[low_metric].quantile(bottom_percentile)
        low_mask = wide[low_metric] <= low_threshold
    else:
        low_threshold = wide[low_metric].quantile(1 - bottom_percentile)
        low_mask = wide[low_metric] >= low_threshold

    flagged = wide[high_mask & low_mask].copy()

    rows = [
        {
            "country": r["COUNTRY"],
            "city": r["CITY"],
            "zone": r["ZONE"],
            "high_metric_value": float(r[high_metric]),
            "high_metric_formatted": high_meta.format_value(float(r[high_metric])),
            "low_metric_value": float(r[low_metric]),
            "low_metric_formatted": low_meta.format_value(float(r[low_metric])),
        }
        for _, r in flagged.iterrows()
    ]

    return {
        "rows": rows,
        "meta": {
            "high_metric": high_metric,
            "low_metric": low_metric,
            "week_offset": week_offset,
            "top_percentile": top_percentile,
            "bottom_percentile": bottom_percentile,
            "n_zones_flagged": len(rows),
            "n_zones_considered": int(len(wide)),
        },
    }


# ---------------------------------------------------------------------------
# Primitive 6: growth_drivers — the "inference" query type
# ---------------------------------------------------------------------------

def growth_drivers(
    df: pd.DataFrame,
    target_metric: str = "Orders",
    n_weeks: int = 5,
    top_n_growing: int = 5,
    country: str | None = None,
) -> dict:
    """
    Identify the top-N zones with the largest increase in `target_metric`
    over the last `n_weeks`, and for each one, list the other metrics that
    moved the most in the same period (candidate explanatory drivers).

    This powers questions like "which zones are growing the most in orders
    and what might explain it?"
    """
    _validate_metric(target_metric)

    mask = df["METRIC"] == target_metric
    mask &= df["week_offset"] < n_weeks
    if country:
        mask &= df["COUNTRY"].str.upper() == country.upper()
    sub = df.loc[mask]

    if sub.empty:
        return {"rows": [], "meta": {"note": "No data for the target metric."}}

    # Compute change (L0W - L{n_weeks-1}W) per zone
    first_week = n_weeks - 1
    last_week = 0

    first = sub[sub["week_offset"] == first_week][["COUNTRY", "CITY", "ZONE", "value"]].rename(columns={"value": "first_value"})
    last = sub[sub["week_offset"] == last_week][["COUNTRY", "CITY", "ZONE", "value"]].rename(columns={"value": "last_value"})

    growth = first.merge(last, on=["COUNTRY", "CITY", "ZONE"])
    growth["absolute_change"] = growth["last_value"] - growth["first_value"]
    growth["pct_change"] = (
        (growth["last_value"] - growth["first_value"]) / growth["first_value"].replace(0, pd.NA) * 100
    )

    top_growing = growth.sort_values("absolute_change", ascending=False).head(top_n_growing)

    # For each top-growing zone, find the other metrics that moved the most
    rows = []
    for _, z in top_growing.iterrows():
        zone_all = df[
            (df["ZONE"] == z["ZONE"])
            & (df["CITY"] == z["CITY"])
            & (df["COUNTRY"] == z["COUNTRY"])
            & (df["week_offset"].isin([first_week, last_week]))
            & (df["METRIC"] != target_metric)
        ]
        drivers = (
            zone_all.pivot_table(
                index="METRIC", columns="week_offset", values="value", aggfunc="first"
            )
            .dropna()
        )
        if not drivers.empty and first_week in drivers.columns and last_week in drivers.columns:
            drivers["abs_change"] = drivers[last_week] - drivers[first_week]
            drivers["pct_change"] = (drivers["abs_change"] / drivers[first_week].replace(0, pd.NA)) * 100
            top_drivers = drivers.reindex(
                drivers["pct_change"].abs().sort_values(ascending=False).index
            ).head(3)
            driver_list = [
                {
                    "metric": m,
                    "first_value": float(row[first_week]),
                    "last_value": float(row[last_week]),
                    "pct_change": float(row["pct_change"]) if pd.notna(row["pct_change"]) else None,
                }
                for m, row in top_drivers.iterrows()
            ]
        else:
            driver_list = []

        rows.append({
            "country": z["COUNTRY"],
            "city": z["CITY"],
            "zone": z["ZONE"],
            "first_value": float(z["first_value"]),
            "last_value": float(z["last_value"]),
            "absolute_change": float(z["absolute_change"]),
            "pct_change": float(z["pct_change"]) if pd.notna(z["pct_change"]) else None,
            "candidate_drivers": driver_list,
        })

    return {
        "rows": rows,
        "meta": {
            "target_metric": target_metric,
            "n_weeks": n_weeks,
            "compared_weeks": f"L{first_week}W vs L{last_week}W",
            "country": country,
        },
    }

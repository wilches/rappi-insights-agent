""""
Data loader for Rappi metrics

Responsabilities:
1. Load both CSVs (metrics + orders)
2. Normalize the "wide" weekly format (L8W_VALUE ... LOW VALUE) into long format.
3. Merge orders into the same unified schema as metrics
4. Return one clean, validated DataFrame that the rest of the system queries.

"""

from pathlib import Path
import pandas as pd
import logging

logger = logging.getLogger(__name__)

# The 9 week columns in the raw CSV, ordered from oldest to newest.
# L8W = 8 weeks ago, L0W = current week.
WEEK_COLUMNS_WIDE = [f"L{i}W_ROLL" for i in range(8, -1, -1)]

# Indetifying colymns that stay as dimensions after melting.
# Identifying columns that stay as dimensions after melting.
DIMENSION_COLS_METRICS = [
    "COUNTRY", "CITY", "ZONE", "ZONE_TYPE", "ZONE_PRIORITIZATION", "METRIC"
]

def _melt_wide_to_long(df: pd.DataFrame, id_cols: list, value_cols:list) -> pd.DataFrame:
    """
    Turn the wide weekly layout into long format.

    Input:  COUNTRY | ... | METRIC | L8W_VALUE | L7W_VALUE | ... | L0W_VALUE
    Output: COUNTRY | ... | METRIC | week_offset | value
    """

    long_df = df.melt(
        id_vars=id_cols,
        value_vars=value_cols,
        var_name="week_column",
        value_name="value"
    )
    # Extract the integer week offset from "L5W_VALUE" -> 5
    long_df["week_offset"] = (
        long_df["week_column"].str.extract(r"L(\d+)W").astype(int)
    )
    long_df = long_df.drop(columns=["week_column"])
    return long_df

def load_metrics(metrics_path: Path) -> pd.DataFrame:
    """Load the operational metrics CSV and normalize to long format"""
    df = pd.read_csv(metrics_path)

    # Validate expected columns exist before trusting the file
    missing = set(DIMENSION_COLS_METRICS + WEEK_COLUMNS_WIDE) - set(df.columns)
    if missing:
        raise ValueError(
            f"Metrics CSV is missing expected columns: {sorted(missing)}. "
            f"Got columns: {sorted(df.columns)}"
        )

    long_df = _melt_wide_to_long(
        df,
        id_cols=DIMENSION_COLS_METRICS,
        value_cols=WEEK_COLUMNS_WIDE,
    )
    return long_df

def load_orders(orders_path: Path) -> pd.DataFrame:
    """
    Load the orders CSV and normalize to the same schema as metrics.

    The orders file uses L8W ... L0W (no _VALUE suffix) and its METRIC is always "Orders".
    We normalize it to the same schema so both live in one unified DataFrame.
    """
    df = pd.read_csv(orders_path)
    # The orders file may not have ZONE_TYPE/ZONE_PRIORITIZATION — add blanks if missing.
    for col in ("ZONE_TYPE", "ZONE_PRIORITIZATION"):
        if col not in df.columns:
            df[col] = pd.NA

    if "METRIC" not in df.columns:
        df["METRIC"] = "Orders"

    # Handle naming convention: "L8W"
    orders_week_cols_plain = [f"L{i}W" for i in range(8, -1, -1)]

    if all(c in df.columns for c in orders_week_cols_plain):
        value_cols = orders_week_cols_plain
    else:
        raise ValueError(
            f"Orders CSV doesn't have expected week columns. "
            f"Got: {sorted(df.columns)}"
        )

    long_df = _melt_wide_to_long(
        df,
        id_cols=DIMENSION_COLS_METRICS,
        value_cols=value_cols
    )
    return long_df

def load_unified_data(metrics_path: Path, orders_path: Path) -> pd.DataFrame:
    """
    Main entry point. Returns a single long-format DataFrame containing
    both operational metrics and order volumes.

    Schema:
        COUNTRY               str  (e.g., "MX", "CO")
        CITY                  str
        ZONE                  str
        ZONE_TYPE             str  ("Wealthy" / "Non Wealthy" / NA for orders)
        ZONE_PRIORITIZATION   str  ("High Priority" / "Prioritized" / "Not Prioritized")
        METRIC                str  (metric name, e.g., "Lead Penetration", "Orders")
        week_offset           int  (0-8, where 0 = current week)
        value                 float
    """

    metrics_path = Path(metrics_path)
    orders_path = Path(orders_path)

    if not metrics_path.exists():
        raise FileNotFoundError(f"Metrics CSV not found: {metrics_path}")
    if not orders_path.exists():
        raise FileNotFoundError(f"Orders CSV not found: {orders_path}")

    metrics_long = load_metrics(metrics_path)
    orders_long = load_orders(orders_path)

    unified = pd.concat([metrics_long, orders_long], ignore_index=True)

    # Normalize text columns: strip whitespace, consisten casing for joinig
    for col in DIMENSION_COLS_METRICS:
        if col in unified.columns:
            unified[col] = unified[col].astype(str).str.strip()

    # Drop rows where value is null — nothing to analyze there
    n_before = len(unified)
    unified = unified.dropna(subset=["value"])
    n_after = len(unified)
    if n_before != n_after:
        logger.info(f"Dropped {n_before - n_after} rows with null values")

    # Final validation: every row should have non-empty dimensions
    for col in ["COUNTRY", "CITY", "ZONE", "METRIC"]:
        nulls = unified[col].isna().sum() + (unified[col] == "nan").sum()
        if nulls > 0:
            logger.warning(f"{nulls} rows have missing/invalid {col}")

    logger.info(
        f"Loaded {len(unified):,} rows: "
        f"{unified['COUNTRY'].nunique()} countries, "
        f"{unified['ZONE'].nunique()} zones, "
        f"{unified['METRIC'].nunique()} metrics, "
        f"{unified['week_offset'].nunique()} weeks"
    )
    # -------- Data quality validation --------
    # Drop rows where values violate the metric's declared semantic range.
    # This catches issues like Lead Penetration ratios > 1.0 (mathematically
    # impossible) that would otherwise corrupt downstream analysis.
    from core.metric_dictionary import METRICS

    rows_dropped_by_validation = 0
    validation_issues = []

    for metric_name, metric_def in METRICS.items():
        if metric_def.min_value is None and metric_def.max_value is None:
            continue

        mask = unified["METRIC"] == metric_name
        metric_rows = unified[mask]

        invalid_mask = pd.Series(False, index=metric_rows.index)

        if metric_def.min_value is not None:
            invalid_mask |= metric_rows["value"] < metric_def.min_value
        if metric_def.max_value is not None:
            invalid_mask |= metric_rows["value"] > metric_def.max_value

        n_invalid = invalid_mask.sum()
        if n_invalid > 0:
            # Record summary for logging
            invalid_values = metric_rows.loc[invalid_mask, "value"]
            affected_countries = (
                metric_rows.loc[invalid_mask, "COUNTRY"].unique().tolist()
            )
            validation_issues.append({
                "metric": metric_name,
                "rows_dropped": int(n_invalid),
                "value_range_expected": (metric_def.min_value, metric_def.max_value),
                "value_range_observed": (
                    float(invalid_values.min()),
                    float(invalid_values.max()),
                ),
                "affected_countries": affected_countries,
            })
            rows_dropped_by_validation += int(n_invalid)

            # Drop the invalid rows from the main frame
            unified = unified.drop(index=metric_rows[invalid_mask].index)

    if validation_issues:
        logger.warning(
            f"Data quality validation dropped {rows_dropped_by_validation} rows "
            f"across {len(validation_issues)} metrics with out-of-range values."
        )
        for issue in validation_issues:
            logger.warning(
                f"  - {issue['metric']}: {issue['rows_dropped']} rows dropped; "
                f"expected in {issue['value_range_expected']}, "
                f"observed up to {issue['value_range_observed'][1]:.1f} "
                f"in countries {issue['affected_countries']}"
            )

    unified = unified.reset_index(drop=True)
    return unified

if __name__ == "__main__":
    # Manual smoke test — run `python -m core.data_loader` from project root
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


    df = load_unified_data(
        metrics_path=Path("data/metrics.csv"),
        orders_path=Path("data/orders.csv"),
    )

    print("\n=== Unified DataFrame head ===")
    print(df.head(10))
    print(f"\nShape: {df.shape}")
    print(f"\nUnique metrics: {sorted(df['METRIC'].unique())}")
    print(f"\nUnique countries: {sorted(df['COUNTRY'].unique())}")
    print(f"\nWeek offsets present: {sorted(df['week_offset'].unique())}")
    print(f"\nValue stats:\n{df['value'].describe()}")

"""
End-to-end smoke test: can we answer the first PDF query with just data + dictionary?

Query: "¿Cuáles son las 5 zonas con mayor % Lead Penetration esta semana?"

If this prints a clean, correctly formatted top-5, the foundation is solid
and tomorrow's analytical primitives are just generalizations of this pattern.
"""

from pathlib import Path
from core.data_loader import load_unified_data
from core.metric_dictionary import get_metric


def main():
    # 1. Load unified data
    df = load_unified_data(
        metrics_path=Path("data/metrics.csv"),
        orders_path=Path("data/orders.csv"),
    )

    # 2. Look up the metric semantics (direction, unit, formatter)
    metric_name = "Lead Penetration"
    metric = get_metric(metric_name)

    # 3. Filter: current week (week_offset=0) + target metric
    current_week = df[
        (df["week_offset"] == 0) & (df["METRIC"] == metric_name)
    ]

    # 4. Sort by value. Direction from the dictionary determines ascending/descending.
    ascending = not metric.is_higher_better
    top_5 = current_week.sort_values("value", ascending=ascending).head(5)

    # 5. Render using the dictionary's formatter
    print(f"\nTop 5 zones by {metric_name} — current week")
    print(f"Direction: {metric.direction}  |  Unit: {metric.unit}")
    print("-" * 70)
    for i, row in enumerate(top_5.itertuples(), start=1):
        formatted_value = metric.format_value(row.value)
        print(
            f"  {i}. {row.COUNTRY} / {row.CITY} / {row.ZONE:<30} "
            f"{formatted_value:>8}"
        )
    print()

    # 6. Sanity: do we have enough data to trust this?
    print(f"Total zones measured this week: {len(current_week)}")
    print(f"Metric description: {metric.description[:100]}...")


if __name__ == "__main__":
    main()

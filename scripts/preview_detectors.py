"""
Quick preview of what our detectors find in the real data.
Run from project root:  python -m scripts.preview_detectors
"""

from pathlib import Path
from core.data_loader import load_unified_data
from analytics.detectors import run_all_detectors


def main():
    df = load_unified_data(
        metrics_path=Path("data/metrics.csv"),
        orders_path=Path("data/orders.csv"),
    )

    findings = run_all_detectors(df)

    print("\n=== Findings summary ===")
    for category, items in findings.items():
        print(f"  {category}: {len(items)} findings")

    print("\n=== Top 3 anomalies ===")
    for f in findings["anomalies"][:3]:
        print(
            f"  [{f['subtype']}] {f['country']} / {f['zone']:<30} "
            f"{f['metric']}: {f['previous_formatted']} -> {f['current_formatted']}"
        )

    print("\n=== Top 3 deteriorating trends ===")
    for f in findings["deteriorating_trends"][:3]:
        print(
            f"  {f['country']} / {f['zone']:<30} "
            f"{f['metric']}: {f['first_formatted']} -> {f['last_formatted']} "
            f"over {f['weeks_consecutive']} weeks"
        )

    print("\n=== Top 3 peer divergences ===")
    for f in findings["peer_divergence"][:3]:
        print(
            f"  {f['country']} / {f['zone']:<30} {f['metric']}: "
            f"zone={f['zone_formatted']}, peer median={f['peer_formatted']}, "
            f"gap={f['relative_gap']:.1%}"
        )

    print("\n=== Top 3 correlations ===")
    for f in findings["correlations"][:3]:
        print(
            f"  [{f['country']}] {f['metric_a']} <-> {f['metric_b']}: "
            f"r={f['pearson_r']:+.2f} (n={f['n_zones']} zones)"
        )

    print("\n=== Top 3 opportunities ===")
    for f in findings["opportunities"][:3]:
        print(
            f"  {f['country']} / {f['zone']:<30} "
            f"{f['metric']}: {f['value_formatted']}"
        )

    print()


if __name__ == "__main__":
    main()

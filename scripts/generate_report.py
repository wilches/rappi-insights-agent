"""
End-to-end insights report generation.
Run: python -m scripts.generate_report

Runs detectors, ranks findings, asks the LLM for narrative, saves markdown.
"""

from pathlib import Path
import logging

from core.data_loader import load_unified_data
from insights.engine import generate_insights
from insights.report_generator import generate_markdown_report, save_report


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    print("\n=== Loading data ===")
    df = load_unified_data(
        metrics_path=Path("data/metrics.csv"),
        orders_path=Path("data/orders.csv"),
    )

    print("\n=== Running detectors and ranking findings ===")
    selected = generate_insights(df)

    total = sum(len(v) for v in selected.values())
    print(f"Selected {total} findings across {len(selected)} categories.")
    for category, findings in selected.items():
        print(f"  {category}: {len(findings)}")

    print("\n=== Generating narrative report (calls LLM once) ===")
    report_md = generate_markdown_report(selected)

    path = save_report(report_md)
    print(f"\n✓ Report saved to: {path}")
    print(f"\n--- Preview (first 1500 chars) ---\n")
    print(report_md[:1500])
    print("\n...(truncated)")


if __name__ == "__main__":
    main()

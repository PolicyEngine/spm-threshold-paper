"""Build the in-kind benefit tables from the receipts in data/inkind.

Writes paper/tables/inkind_growth.md, inkind_amounts.md and inkind_levels.md
under --output-root. Every value comes from ``inkind_inputs.inkind_figures``,
which recomputes it from the receipts' thresholds and band means.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from inkind_inputs import TENURES, YEARS, inkind_figures, load_inkind

REPO = Path(__file__).resolve().parents[1]
SERIES_LABELS = {
    "package": "Replication",
    "fcsuti": "Replication, FCSUti index",
    "fcsuti_bls_definition": "Written definitions, FCSUti index",
}
AMOUNT_LABELS = {
    "imputed_total": "All imputed benefits",
    "rental_assistance_per_renter": "Rental assistance per renter",
    "school_lunch": "School lunch",
}


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines) + "\n"


def dollars(value: float) -> str:
    return f"${value:,.0f}"


def dollar_change(value: float) -> str:
    return f"{'+' if value >= 0 else '-'}${abs(value):,.0f}"


def growth_tables(figures: dict) -> str:
    headers = ["Series", "With mortgage", "Without mortgage", "Renter"]
    rows = [
        ["CPI-U", *([f"{figures['cpi_u_growth']:.2f}%"] * 3)],
        ["BLS FCSUti price index", *([f"{figures['fcsuti_price_growth']:.2f}%"] * 3)],
        ["BLS thresholds", *(f"{figures['bls'][t]['growth']:.2f}%" for t in TENURES)],
    ]
    for run, label in SERIES_LABELS.items():
        growth = figures["runs"][run]["growth"]
        rows.append([label, *(f"{growth[t]['growth_without_stage']:.2f}%" for t in TENURES)])
        rows.append(
            [
                "With imputed benefits",
                *(
                    f"{growth[t]['growth_with_stage']:.2f}% ({growth[t]['stage_change_sd']:.2f})"
                    for t in TENURES
                ),
            ]
        )
    return markdown_table(headers, rows)


def amount_table(figures: dict) -> str:
    headers = ["Benefit", "Series", "2022", "2025", "Change"]
    rows = []
    for name, label in AMOUNT_LABELS.items():
        for index, (series, series_label) in enumerate(
            (("bls", "BLS"), ("package", "Replication"), ("fcsuti", "Replication, FCSUti index"))
        ):
            start, end, rise = figures["amounts"][series][name]
            rows.append(
                [label if index == 0 else "", series_label, dollars(start), dollars(end), dollar_change(rise)]
            )
    return markdown_table(headers, rows)


def level_table(figures: dict) -> str:
    headers = ["Target year", "With mortgage", "Without mortgage", "Renter"]
    summaries = figures["runs"]["package"]["gaps"]["with_in_kind"]
    written = figures["runs"]["package_bls_definition"]["gaps"]["with_in_kind"]
    rows = [
        [year, *(f"{summaries[year][t]:+.2f}% / {written[year][t]:+.2f}%" for t in TENURES)]
        for year in YEARS
    ]
    return markdown_table(headers, rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=REPO)
    args = parser.parse_args()
    output = args.output_root / "paper" / "tables"
    output.mkdir(parents=True, exist_ok=True)
    figures = inkind_figures(load_inkind(REPO / "data" / "inkind", REPO / "data" / "current"))
    (output / "inkind_growth.md").write_text(growth_tables(figures))
    (output / "inkind_amounts.md").write_text(amount_table(figures))
    (output / "inkind_levels.md").write_text(level_table(figures))


if __name__ == "__main__":
    main()

"""Render the separately identified current research artifacts, using stdlib only."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import mean

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data" / "current"
TENURES = ("owner_with_mortgage", "owner_without_mortgage", "renter")


def close(actual: float, expected: float, label: str) -> None:
    if not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-10):
        raise ValueError(f"Inconsistent current artifact: {label}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=REPO)
    args = parser.parse_args()
    output = args.output_root / "paper" / "tables"
    output.mkdir(parents=True, exist_ok=True)
    release = json.loads((DATA / "spm-release.json").read_text())
    ce = json.loads((DATA / "ce_replication_2019_2025.json").read_text())
    if ce["classification"] != "current_retrospective_research":
        raise ValueError("Current CE input must be explicitly retrospective research")

    def write(name: str, headers: list[str], rows: list[list[str]]) -> None:
        lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
        lines.extend("| " + " | ".join(row) + " |" for row in rows)
        (output / name).write_text("\n".join(lines) + "\n")

    current = release["years"]["2025"]
    write(
        "current_release.md",
        ["Tenure", "Published 2025 base", "Housing share (2024)"],
        [
            [
                label,
                f"${current['thresholds'][tenure]:,.2f}",
                f"{current['housing_shares'][tenure]:.3f}",
            ]
            for tenure, label in zip(
                TENURES, ("Owner with mortgage", "Owner without mortgage", "Renter")
            )
        ],
    )

    replication_rows = []
    sensitivity_rows = []
    for year in range(2019, 2026):
        record = ce["results"][str(year)]
        baseline = record["variants"]["exclude_unresolved"]
        differences = []
        for tenure in TENURES:
            official = release["years"][str(year)]["thresholds"][tenure]
            close(official, record["published"][tenure], f"published {year} {tenure}")
            deviation = 100 * (baseline["thresholds"][tenure] / official - 1)
            close(
                deviation,
                record["replication_deviation_percent"][tenure],
                f"replication {year} {tenure}",
            )
            differences.append(f"{deviation:+.2f}%")
        replication_rows.append([str(year), *differences])
        changes = []
        for variant in (
            "legacy_youth_recode_sensitivity",
            "include_5_6_as_renter_sensitivity",
            "code3_no_mortgage_sensitivity",
        ):
            values = []
            for tenure in TENURES:
                change = 100 * (
                    record["variants"][variant]["thresholds"][tenure]
                    / baseline["thresholds"][tenure]
                    - 1
                )
                close(
                    change,
                    record["sensitivity_change_percent_from_exclusion"][variant][
                        tenure
                    ],
                    f"sensitivity {year} {tenure} {variant}",
                )
                values.append(abs(change))
            changes.append(f"{max(values):.4f}%")
        sample = baseline["sample"]
        unresolved = sample["unresolved_youth"]
        share = 100 * unresolved["weight_sum"] / sample["with_children"]["weight_sum"]
        sensitivity_rows.append(
            [str(year), str(unresolved["rows"]), f"{share:.4f}%", *changes[:2]]
        )
        if changes[2] != "0.0000%" or sample["tenure_3"]["rows"] != 0:
            raise ValueError(
                "Update the code-3 sensitivity discussion for nonzero observations"
            )
    write(
        "current_replication.md",
        ["Target year", "With mortgage", "Without mortgage", "Renter"],
        replication_rows,
    )
    write(
        "current_sensitivity.md",
        [
            "Year",
            "Youth rows",
            "Youth weight share",
            "Youth recode",
            "Include tenures 5/6",
        ],
        sensitivity_rows,
    )

    evaluation = ce["projection_evaluation"]
    if (
        evaluation["classification"]
        != "retrospective_current_method_not_a_frozen_commitment"
    ):
        raise ValueError("Current projection classification changed")
    errors = {}
    for row in evaluation["rows"]:
        year, rule = row["target_year"], row["rule"]
        if (year, rule) in errors:
            raise ValueError("Duplicate current projection row")
        values = []
        for tenure in TENURES:
            deviation = 100 * (
                row["projection"]["thresholds"][tenure]
                / release["years"][str(year)]["thresholds"][tenure]
                - 1
            )
            close(
                deviation,
                row["errors_percent"][tenure],
                f"projection {year} {rule} {tenure}",
            )
            values.append(abs(deviation))
        errors[year, rule] = mean(values)
        close(
            errors[year, rule],
            row["mean_absolute_error_percent"],
            f"projection mean {year} {rule}",
        )
    rules = ("cpi_u", "fcsuti_cpi", "replication_ratio", "blend")
    expected = {(year, rule) for year in range(2020, 2026) for rule in rules}
    if set(errors) != expected:
        raise ValueError("Current projection coverage must be six years by four rules")
    rows = [
        [str(year), *(f"{errors[year, rule]:.2f}%" for rule in rules)]
        for year in range(2020, 2026)
    ]
    means = []
    for rule in rules:
        value = mean(errors[year, rule] for year in range(2020, 2026))
        close(value, evaluation["summary_2020_2025"][rule], f"six-year mean {rule}")
        means.append(f"{value:.2f}%")
    rows.append(["Mean", *means])
    write(
        "current_projection.md",
        [
            "Target year",
            "CPI-U",
            "Composite prices",
            "Replication ratio",
            "50/50 blend",
        ],
        rows,
    )


if __name__ == "__main__":
    main()

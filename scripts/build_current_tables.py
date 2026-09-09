"""Render the separately identified current research artifacts, using stdlib only."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import mean

from rolling_inputs import load_rolling_forecast

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data" / "current"
TENURES = ("owner_with_mortgage", "owner_without_mortgage", "renter")
PROJECTION_YEARS = (2025, 2026, 2030, 2035)
SCENARIO_LABELS = {"ce_trend": "CE trend", "zero_real": "Zero real"}


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines) + "\n"


def rolling_tables(rolling: dict) -> dict[str, str]:
    """Render canonical results and diagnostics without rerunning the estimator."""
    scenarios = rolling["scenarios"]
    years = scenarios[rolling["default_scenario"]]["years"]
    anchor_year = rolling["national_anchor_year"]
    current = years[str(anchor_year)]
    if (
        current["national_status"] != "published"
        or current["housing_share_status"] != "published_anchor"
    ):
        raise ValueError("Current national bases and housing shares must be published")
    tables = {
        "current_release.md": markdown_table(
            [
                "Tenure",
                f"Published {anchor_year} base",
                f"Published {anchor_year} housing share",
            ],
            [
                [
                    label,
                    f"${current['thresholds'][tenure]:,.2f}",
                    f"{current['housing_shares'][tenure]:.6f}",
                ]
                for tenure, label in zip(
                    TENURES, ("Owner with mortgage", "Owner without mortgage", "Renter")
                )
            ],
        )
    }
    projection_rows = []
    for year in PROJECTION_YEARS:
        for scenario in ("ce_trend", "zero_real"):
            record = scenarios[scenario]["years"][str(year)]
            if year == anchor_year and (
                record["thresholds"] != current["thresholds"]
                or record["housing_shares"] != current["housing_shares"]
                or record["national_status"] != "published"
            ):
                raise ValueError("Scenarios must share the published national anchor")
            projection_rows.append(
                [
                    str(year),
                    SCENARIO_LABELS[scenario],
                    record["national_status"].capitalize(),
                    *(f"${record['thresholds'][tenure]:,.2f}" for tenure in TENURES),
                ]
            )
    tables["rolling_projection.md"] = markdown_table(
        ["Year", "Scenario", "National status", "With mortgage", "Without mortgage", "Renter"],
        projection_rows,
    )

    acs = rolling["validation"]["acs"]
    if acs["status"] != "complete" or acs["unvalidated"]:
        raise ValueError("ACS retrospective validation must be complete")
    assumptions = rolling["assumptions"]["acs"]
    stabilization = assumptions["relative_index_stabilization"]
    ordered_years = sorted(map(int, years))
    last_year = ordered_years[-1]
    first_constant = next(
        year
        for year in ordered_years[:-1]
        if all(
            years[str(later)]["rent_indices"] == years[str(year)]["rent_indices"]
            for later in ordered_years
            if later > year
        )
    )
    first_all_projected = next(
        year
        for year in ordered_years
        if years[str(year)]["acs_window"]["observed_years"] == 0
    )
    if (
        first_constant != stabilization["first_constant_index_year"]
        or first_constant + 1 != stabilization["first_unchanged_transition_year"]
        or first_all_projected != stabilization["first_all_projected_window_year"]
        or last_year != stabilization["through_year"]
        or assumptions["donor_year"] != stabilization["latest_observed_donor_year"]
    ):
        raise ValueError("ACS stabilization metadata must match canonical output")
    latest = years[str(last_year)]
    diagnostics = latest["median_diagnostics"]
    if set(diagnostics) != set(latest["rent_indices"]):
        raise ValueError("Support diagnostics must cover every modeled area")
    for diagnostic in diagnostics.values():
        if not (
            diagnostic["unique_records"]
            == diagnostic["unique_original_donor_count"]
            == diagnostic["donor_support"]["unique_records"]
        ):
            raise ValueError("Projected donor copies must not inflate support counts")

    def span(field: str, decimals: int = 0) -> str:
        values = [record[field] for record in diagnostics.values()]
        return f"{min(values):,.{decimals}f}–{max(values):,.{decimals}f}"

    area_count = len(diagnostics)
    thin_count = sum(record["thin_support"] for record in diagnostics.values())
    local_warnings = sum(
        record["median_topcode_warning"] for record in diagnostics.values()
    )
    index_warnings = sum(
        record["rent_index_topcode_warning"] for record in diagnostics.values()
    )
    validation_rows = [
        [
            "ACS retrospective comparison",
            f"{acs['origin_spm_year']}→{acs['target_spm_year']}; {acs['area_count']} areas",
        ],
        [
            "MAPE (model / carry-forward)",
            f"{acs['mean_absolute_percentage_error']:.4f}% / "
            f"{acs['baseline_mean_absolute_percentage_error']:.4f}%",
        ],
        ["Future donor cohort", str(assumptions["donor_year"])],
        [
            f"ACS window ({last_year})",
            f"{latest['acs_window']['start']}–{latest['acs_window']['end']} "
            f"({latest['acs_window']['projected_years']} projected)",
        ],
        ["Constant relative indices", f"{first_constant}–{last_year}"],
        ["First all-projected window", str(first_all_projected)],
        [f"Unique original donors ({last_year})", span("unique_original_donor_count")],
        [f"Allocation-expected donors ({last_year})", span("expected_whole_record_count", 2)],
        [f"Donor-collapsed Kish ({last_year})", span("kish_effective_count", 2)],
        [f"Thin-support areas ({last_year})", f"{thin_count} / {area_count}"],
        [f"Topcoding warnings ({last_year})", f"{local_warnings} local / {index_warnings} index"],
    ]
    note = (
        "Notes: MAPE uses equal-area retrospective errors with current source vintages; "
        "it does not validate the later vintage bridge. "
        f"Support and warnings cover {area_count} modeled areas in {last_year}. "
        "Repeated donors are not independent observations; Kish is not survey-design "
        "effective sample size. These diagnostics are not confidence intervals. "
        "Local warnings concern the target median; index warnings include local or "
        "national medians in target, anchor or overlap ratios, not known bias. "
        "Under uniform growth/deflation, constant relative indices can coexist with "
        "changing housing shares and geographic factors; floating-point noise is "
        "not substantive movement."
    )
    tables["rolling_validation.md"] = (
        markdown_table(["Diagnostic", "Value"], validation_rows) + "\n" + note + "\n"
    )
    return tables


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
    rolling = load_rolling_forecast(DATA)
    if ce["classification"] != "current_retrospective_research":
        raise ValueError("Current CE input must be explicitly retrospective research")

    def write(name: str, headers: list[str], rows: list[list[str]]) -> None:
        (output / name).write_text(markdown_table(headers, rows))

    for name, content in rolling_tables(rolling).items():
        (output / name).write_text(content)

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

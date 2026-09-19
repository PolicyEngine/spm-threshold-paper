"""Validate six saved diagnostic cells and summarize the controlled comparison.

This script reads JSON summaries only. It neither imports PolicyEngine nor
loads a population. The registered forecast and grade are outside its scope.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path

SOURCES = {
    "before": ("238321d3b9ff44d2b6f3cbe378040be263221d47", "2.6.8"),
    "after": ("44001a4c24ae5d1bce9179e2bb285b41cae6a272", "2.6.9"),
}
DATASET_SHA256 = "6496cc4393d4d3c6574f76eca231de5898c803b9067645591fd5c4d3e65aee84"
# Keep the registered artifact identity explicit, independent of run metadata.
FORECAST_SHA256 = "3d86d5c4c0423480e6b69b75d222ffa4a7a2639e4094df5ba2504af01be17173"
ANCHOR_FACTORS = {
    "OWNER_WITH_MORTGAGE": 39230.994457 * (32649 / 31812) / 41322.707394,
    "OWNER_WITHOUT_MORTGAGE": 32878.594848 * (32649 / 31812) / 34325.99772,
    "RENTER": 39219.893902 * (32649 / 31812) / 41700.555713,
}
RESIDUAL_LABEL = "Change with national threshold bases held constant in real terms"
SPECS = ((2024, "baseline"), (2025, "baseline"), (2025, "anchored_2024_cpi"))
PACKAGES = {
    "policyengine",
    "policyengine-us",
    "policyengine-core",
    "spm-calculator",
    "microdf-python",
    "numpy",
    "pandas",
}
GROUPS = (
    "all",
    "under_4",
    "under_6",
    "under_18",
    "age_6_17",
    "age_18_64",
    "age_65_74",
    "age_75_plus",
    "age_65_plus",
)
TOLERANCE = 1e-8


def require(condition, message):
    if not condition:
        raise ValueError(message)


def finite_number(value, label):
    require(
        isinstance(value, (float, int))
        and not isinstance(value, bool)
        and math.isfinite(value),
        f"{label} must be finite numeric data",
    )
    return value


def reject_nonfinite(value, label="JSON"):
    if isinstance(value, float):
        require(math.isfinite(value), f"{label} contains nonfinite data")
    elif isinstance(value, dict):
        for key, child in value.items():
            reject_nonfinite(child, f"{label}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_nonfinite(child, f"{label}[{index}]")


def valid_hash(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
    )


def close(left, right):
    return math.isclose(left, right, rel_tol=1e-12, abs_tol=TOLERANCE)


def _validate_cell(cell):
    reject_nonfinite(cell)
    require(cell["format"] == "spm/uprating-validation-cell/v1", "Unknown cell format")
    spec = (cell["year"], cell["variant"])
    require(spec in SPECS, f"Unexpected cell year/variant: {spec}")
    if cell["variant"] == "anchored_2024_cpi":
        require(cell["anchor_factors"] == ANCHOR_FACTORS, "Incorrect anchor factors")
    else:
        require(cell["anchor_factors"] is None, "Baseline declares anchor factors")
    provenance = cell["provenance"]
    source = provenance["country_source_sha_declared"]
    arms = [name for name, (sha, _) in SOURCES.items() if sha == source]
    require(len(arms) == 1, f"Unexpected country source SHA: {source}")
    arm = arms[0]
    versions = provenance["package_versions"]
    require(set(versions) == PACKAGES, "Missing or unexpected package-version fields")
    require(
        all(isinstance(value, str) and value for value in versions.values()),
        "Missing package version",
    )
    require(
        versions["policyengine-us"] == SOURCES[arm][1],
        f"Wrong country version for {arm}",
    )
    require(
        provenance["expected_model_version"] == SOURCES[arm][1],
        f"Wrong expected country version for {arm}",
    )
    require(
        provenance["dataset_sha256"] == DATASET_SHA256
        and provenance["expected_dataset_sha256"] == DATASET_SHA256,
        "Wrong dataset SHA256",
    )
    require(valid_hash(provenance["runner_sha256"]), "Missing/invalid runner SHA256")
    require(
        valid_hash(provenance["country_init_sha256"]),
        "Missing/invalid country init SHA256",
    )
    require(
        provenance["development_country_model"] is True
        and provenance["bundle_certified"] is False,
        "Cells must declare uncertified model-development mode",
    )
    require(
        isinstance(provenance["caller_seed"], int)
        and not isinstance(provenance["caller_seed"], bool),
        "Missing/invalid caller seed",
    )
    for field in (
        "country_import_path",
        "python",
        "platform",
        "interface",
        "seed_note",
    ):
        require(
            isinstance(provenance[field], str) and bool(provenance[field]),
            f"Missing {field}",
        )
    require("pythonhashseed" in provenance, "Missing pythonhashseed")
    config = provenance["spm_config"]
    require(
        config["forecast_content_sha256"] == FORECAST_SHA256
        and config["scenario"] == "ce_trend",
        "Wrong SPM forecast/scenario",
    )
    require(
        isinstance(provenance["spm_provenance"], dict)
        and bool(provenance["spm_provenance"]),
        "Missing SPM provenance",
    )
    require(
        set(cell["groups"]) == set(GROUPS) and set(cell["spm_pct"]) == set(GROUPS),
        "Missing or unexpected age groups",
    )
    for group in GROUPS:
        values = cell["groups"][group]
        people = finite_number(values["people"], f"{group}.people")
        poor = finite_number(values["poor_people"], f"{group}.poor_people")
        rate = finite_number(values["spm_pct"], f"{group}.spm_pct")
        require(
            people > 0 and 0 <= poor <= people and 0 <= rate <= 100,
            f"Invalid counts/rate for {group}",
        )
        require(close(100 * poor / people, rate), f"Rate/count mismatch for {group}")
        require(
            close(finite_number(cell["spm_pct"][group], f"spm_pct.{group}"), rate),
            f"Duplicate rate mismatch for {group}",
        )
        for field in (
            "spm_unit_resources_usd",
            "spm_unit_threshold_usd",
            "resource_threshold_ratio",
        ):
            require(
                set(values[field]) == {"mean", "p25", "median", "p75"},
                f"Missing distribution for {group}.{field}",
            )
            for key, number in values[field].items():
                finite_number(number, f"{group}.{field}.{key}")
            if field == "spm_unit_threshold_usd":
                require(
                    all(number > 0 for number in values[field].values()),
                    f"Nonpositive threshold summary for {group}",
                )
        bands = values["resource_ratio_band_pct"]
        require(
            set(bands)
            == {
                "below_0_75",
                "0_75_to_below_1",
                "1_to_below_1_25",
                "1_25_to_below_1_5",
                "1_5_or_more",
            },
            f"Missing ratio bands for {group}",
        )
        require(
            all(
                0 <= finite_number(number, f"{group}.band") <= 100
                for number in bands.values()
            )
            and close(sum(bands.values()), 100),
            f"Invalid ratio bands for {group}",
        )
        require(
            close(bands["below_0_75"] + bands["0_75_to_below_1"], rate),
            f"Poverty/ratio band mismatch for {group}",
        )
        for key, number in values["component_person_mapped_mean_usd"].items():
            finite_number(number, f"{group}.component.{key}")
    return arm, spec


def validate_cell(cell):
    try:
        return _validate_cell(cell)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"Missing or malformed cell data: {exc}") from exc


def compare_distributions(left, right, field):
    deltas = {key: right[field][key] - left[field][key] for key in left[field]}
    return {
        "match": all(close(left[field][key], right[field][key]) for key in deltas),
        "after_minus_before": deltas,
    }


def summarize(cells):
    """Validate input dictionaries and return scalar arithmetic only."""
    indexed = {}
    common = None
    component_keys = None
    for cell in cells:
        arm, spec = validate_cell(cell)
        key = (arm, *spec)
        require(key not in indexed, f"Duplicate cell: {key}")
        indexed[key] = cell
        provenance = cell["provenance"]
        comparison = {
            key: provenance[key]
            for key in (
                "dataset_sha256",
                "runner_sha256",
                "caller_seed",
                "pythonhashseed",
                "spm_config",
                "python",
                "platform",
                "interface",
                "seed_note",
            )
        }
        comparison["non_country_package_versions"] = {
            name: version
            for name, version in provenance["package_versions"].items()
            if name != "policyengine-us"
        }
        if common is None:
            common = comparison
        else:
            for field in common:
                require(
                    comparison[field] == common[field],
                    f"Inconsistent provenance: {field}",
                )
        for group in GROUPS:
            keys = set(cell["groups"][group]["component_person_mapped_mean_usd"])
            if component_keys is None:
                component_keys = keys
            require(keys == component_keys, "Inconsistent component fields")
    expected = {(arm, *spec) for arm in SOURCES for spec in SPECS}
    require(
        set(indexed) == expected, f"Missing cells: {sorted(expected - set(indexed))}"
    )
    for year in (2024, 2025):
        same_year = [
            cell for (_, cell_year, _), cell in indexed.items() if cell_year == year
        ]
        for group in GROUPS:
            population = same_year[0]["groups"][group]["people"]
            require(
                all(
                    close(cell["groups"][group]["people"], population)
                    for cell in same_year
                ),
                f"Same-year populations differ: {year} {group}",
            )
    rows, base_checks, anchor_checks = {}, {}, {}
    for group in GROUPS:
        rows[group] = {}
        for arm in SOURCES:
            b24 = indexed[(arm, 2024, "baseline")]["groups"][group]
            b25 = indexed[(arm, 2025, "baseline")]["groups"][group]
            a25 = indexed[(arm, 2025, "anchored_2024_cpi")]["groups"][group]
            for statistic, baseline in b25["spm_unit_threshold_usd"].items():
                anchored_threshold = a25["spm_unit_threshold_usd"][statistic]
                lower = baseline * min(ANCHOR_FACTORS.values())
                upper = baseline * max(ANCHOR_FACTORS.values())
                tolerance = max(TOLERANCE, abs(baseline) * 1e-6)
                require(
                    lower - tolerance <= anchored_threshold <= upper + tolerance,
                    f"Anchored threshold outside tenure-scaling bounds: {arm} {group} {statistic}",
                )
            r24, r25, anchored = b24["spm_pct"], b25["spm_pct"], a25["spm_pct"]
            rows[group][arm] = {
                "rate_2024_pct": r24,
                "rate_2025_pct": r25,
                "rate_2025_anchored_pct": anchored,
                "change_pp": r25 - r24,
                "threshold_contribution_pp": r25 - anchored,
                "constant_real_national_base_change_pp": anchored - r24,
            }
            anchor_checks.setdefault(arm, {})[group] = compare_distributions(
                b25, a25, "spm_unit_resources_usd"
            )
        rows[group]["after_minus_before"] = {
            key: rows[group]["after"][key] - rows[group]["before"][key]
            for key in rows[group]["before"]
        }
        before = indexed[("before", 2024, "baseline")]["groups"][group]
        after = indexed[("after", 2024, "baseline")]["groups"][group]
        base_checks[group] = {
            "rates_match": close(before["spm_pct"], after["spm_pct"]),
            "rate_difference_pp": after["spm_pct"] - before["spm_pct"],
            "resources": compare_distributions(before, after, "spm_unit_resources_usd"),
            "thresholds": compare_distributions(
                before, after, "spm_unit_threshold_usd"
            ),
        }
    return {
        "format": "spm/controlled-uprating-comparison/v1",
        "scope": "Retrospective joint effect of #9526 and #9527 on the fixed population; no forecast amendment or claim of forecasting skill.",
        "residual_label": RESIDUAL_LABEL,
        "residual_note": "The cross-year remainder includes resources, geography, composition and weighting; it is not an isolated causal resource effect.",
        "sources": {
            arm: {"sha": sha, "package_version": version}
            for arm, (sha, version) in SOURCES.items()
        },
        "matched_provenance": common,
        "groups": rows,
        "checks": {
            "same_year_populations_match": True,
            "anchor_threshold_mean_and_quantile_bounds_pass": True,
            "anchor_bound_relative_tolerance": 1e-6,
            "comparison_tolerance": {"absolute": TOLERANCE, "relative": 1e-12},
            "base_year_2024": base_checks,
            "baseline_to_anchored_2025_resource_summaries": anchor_checks,
            "resource_check_note": "Equality of recorded summaries does not prove person-by-person resource equality; anchor-check differences are anchored minus baseline.",
        },
        "bundle_certified": False,
    }


def markdown(result):
    lines = [
        "Controlled SPM uprating comparison (rates in percent; changes in percentage points).",
        "",
        "| Age group | Source | 2024 rate | 2025 rate | Change | Threshold contribution | Remainder* |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for group, row in result["groups"].items():
        for arm in SOURCES:
            item = row[arm]
            lines.append(
                f"| {group} | {arm} | {item['rate_2024_pct']:.3f} | {item['rate_2025_pct']:.3f} | {item['change_pp']:+.3f} | {item['threshold_contribution_pp']:+.3f} | {item['constant_real_national_base_change_pp']:+.3f} |"
            )
    lines.extend(
        [
            "",
            f"*{RESIDUAL_LABEL}. Includes resources, geography, composition and weighting.",
            "",
            "| Age group | After − before: annual change | Threshold contribution | Remainder* |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for group, row in result["groups"].items():
        item = row["after_minus_before"]
        lines.append(
            f"| {group} | {item['change_pp']:+.3f} | {item['threshold_contribution_pp']:+.3f} | {item['constant_real_national_base_change_pp']:+.3f} |"
        )
    base = result["checks"]["base_year_2024"]
    anchors = result["checks"]["baseline_to_anchored_2025_resource_summaries"]
    rates_match = all(value["rates_match"] for value in base.values())
    resources_match = all(value["resources"]["match"] for value in base.values())
    anchors_match = all(
        value["match"] for groups in anchors.values() for value in groups.values()
    )
    lines.extend(
        [
            "",
            f"2024 checks: rates match = {rates_match}; resource summaries match = {resources_match}.",
            f"2025 baseline/anchored resource summaries match = {anchors_match}. Summary equality does not establish person-by-person equality.",
            "",
            "Retrospective development comparison of the two uprating fixes jointly; no amendment to the registered forecast or grade. These results are not a certified release.",
            "",
        ]
    )
    return "\n".join(lines)


def load_cells(results_dir):
    cells, receipts = [], []
    for path in sorted(Path(results_dir).glob("*.json")):
        try:
            raw = path.read_bytes()
            value = json.loads(raw)
        except (OSError, ValueError) as exc:
            raise ValueError(f"Cannot read JSON result {path}: {exc}") from exc
        if (
            isinstance(value, dict)
            and value.get("format") == "spm/uprating-validation-cell/v1"
        ):
            cells.append(value)
            receipts.append(
                {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest()}
            )
    return cells, receipts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        help="JSON output; a same-stem Markdown file is also written",
    )
    args = parser.parse_args(argv)
    output = args.output or args.results_dir / "controlled-comparison.json"
    require(output.suffix == ".json", "--output must end in .json")
    md_path = output.with_suffix(".md")
    require(
        not output.exists() and not md_path.exists(),
        "Refusing to overwrite an existing summary",
    )
    cells, receipts = load_cells(args.results_dir)
    result = summarize(cells)
    result["input_files"] = receipts
    result["summarizer_sha256"] = hashlib.sha256(
        Path(__file__).read_bytes()
    ).hexdigest()
    serialized = json.dumps(result, indent=2, allow_nan=False) + "\n"
    table = markdown(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as handle:
        handle.write(serialized)
    with md_path.open("x") as handle:
        handle.write(table)
    print(
        json.dumps({"json": str(output.resolve()), "markdown": str(md_path.resolve())})
    )


if __name__ == "__main__":
    main()

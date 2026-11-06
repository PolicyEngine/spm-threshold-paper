"""Validated inputs and derived figures for the in-kind benefit section.

``data/inkind/`` holds two receipts from PolicyEngine/spm-calculator, their
provenance record and a checksum manifest:

- ``ce_inkind_replication_2019_2025.json`` replicates 2019-2025 thresholds
  with and without the calculator's in-kind benefit stage, under the
  replication's composite CPI and under BLS's FCSUti index.
- ``ce_inkind_bls_components_2019_2025.json`` recovers BLS's in-band
  component means from its published threshold shares and compares them with
  the replication's, under the CE summary definitions and under the shelter
  and food definitions in Garner and Munoz (2021).

``load_inkind`` checks the bytes, the provenance, and the receipts' agreement
with each other and with the out-of-pocket replication in ``data/current``.
``inkind_figures`` recomputes every growth rate, gap, share and dollar change
the in-kind tables and prose report from the receipts' thresholds and band
means, and checks each against the value the receipt records. Both raise
``ValueError`` on any inconsistency. The module uses the standard library
only.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from statistics import mean, stdev

TENURES = ("owner_with_mortgage", "owner_without_mortgage", "renter")
YEARS = tuple(str(year) for year in range(2019, 2026))
REPLICATION = "ce_inkind_replication_2019_2025.json"
COMPONENTS = "ce_inkind_bls_components_2019_2025.json"
PROVENANCE = "provenance.json"
INKIND_FILES = (COMPONENTS, REPLICATION, PROVENANCE)
CLASSIFICATION = "current_retrospective_research"
# Run name -> (deflator, BLS's written shelter and food definitions applied).
RUNS = {
    "package": ("package", False),
    "fcsuti": ("fcsuti", False),
    "package_bls_definition": ("package", True),
    "fcsuti_bls_definition": ("fcsuti", True),
}
AMOUNTS = ("imputed_total", "rental_assistance_per_renter", "school_lunch")
# BLS's threshold for tenure h is s * (C + SU_h + 0.2 F), with F = C + sum_h
# P_h SU_h. School lunch, WIC and broadband enter the shared term C; LIHEAP
# and rental assistance enter SU_h. ``_imputed_terms`` checks this split
# against the component receipt's own imputed-term dollars.
ANCHOR_SHARE = 0.82
SHARED_IMPUTED = ("nslp", "wic", "broadband")
SHELTER_UTILITY_IMPUTED = ("liheap", "rental_assistance")
# The paper states this bound for BLS's share identities, in dollars.
BLS_IDENTITY_TOLERANCE_DOLLARS = 1e-5


def _require(condition: bool, label: str) -> None:
    if not condition:
        raise ValueError(f"inconsistent in-kind artifact: {label}")


def _close(actual: float, expected: float, label: str) -> None:
    # The component receipt rebuilds BLS's thresholds from its share identities,
    # which reproduce the published values within $0.00001, so its growth rates
    # and shares differ from ones computed on the published values by about
    # 1e-8 percentage points. Dollar amounts must agree to 1e-9 relative;
    # percentages and points, which the tables print to 0.01, to 1e-6.
    _require(
        math.isfinite(actual)
        and math.isfinite(expected)
        and math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-6),
        f"{label} ({actual!r} != {expected!r})",
    )


def _growth(start: float, end: float) -> float:
    return 100 * (end / start - 1)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_inkind(data_dir: Path, current_dir: Path) -> dict:
    """Check ``data/inkind`` and return its parsed receipts."""
    manifest: dict[str, str] = {}
    lines = (data_dir / "SHA256SUMS").read_text().splitlines()
    for number, line in enumerate(lines, 1):
        fields = line.split()
        _require(
            len(fields) == 2 and re.fullmatch(r"[0-9a-f]{64}", fields[0]) is not None,
            f"malformed manifest line {number}",
        )
        digest, name = fields
        _require(name not in manifest, f"duplicate manifest entry {name}")
        manifest[name] = digest
    expected = {f"data/inkind/{name}" for name in INKIND_FILES}
    present = {f"data/inkind/{path.name}" for path in data_dir.glob("*.json")}
    _require(
        set(manifest) == expected == present,
        f"manifest coverage: listed {sorted(manifest)}, present {sorted(present)}",
    )
    for name, digest in manifest.items():
        _require(_sha256(data_dir / Path(name).name) == digest, f"hash of {name}")

    replication = json.loads((data_dir / REPLICATION).read_text())
    components = json.loads((data_dir / COMPONENTS).read_text())
    provenance = json.loads((data_dir / PROVENANCE).read_text())
    current_bytes = (current_dir / "ce_replication_2019_2025.json").read_bytes()
    current = json.loads(current_bytes)

    _require(
        provenance["classification"]
        == replication["classification"]
        == components["classification"]
        == CLASSIFICATION,
        "receipts must be retrospective research",
    )
    _require(
        provenance["covered_by_original_timestamp"] is False
        and provenance["frozen_commitments_modified"] is False,
        "in-kind inputs stay outside the frozen forecast commitment",
    )
    _require(
        set(provenance["artifacts"]) == expected - {f"data/inkind/{PROVENANCE}"},
        "provenance covers exactly the two receipts",
    )
    for name, receipt in ((REPLICATION, replication), (COMPONENTS, components)):
        record = provenance["artifacts"][f"data/inkind/{name}"]
        _require(record["sha256"] == manifest[f"data/inkind/{name}"], f"provenance hash {name}")
        _require(record["code_sha256"] == receipt["code_sha256"], f"code fingerprints {name}")
        _require(record["generated_at_git_head"] == receipt["git_head"], f"git head {name}")
        _require(re.fullmatch(r"[0-9a-f]{40}", record["calculator_commit"]) is not None, f"commit {name}")
    _require(
        components["inputs"]["replication_receipt"]["sha256"]
        == manifest[f"data/inkind/{REPLICATION}"],
        "component receipt derives from the recorded replication receipt",
    )
    archived = replication["archived_receipt_check"]
    _require(
        archived["sha256"] == hashlib.sha256(current_bytes).hexdigest()
        and archived["out_of_pocket_thresholds_identical"] is True
        and archived["zero_in_kind_thresholds_identical"] is True,
        "out-of-pocket run reproduces data/current's replication artifact",
    )
    for run, (deflator, written) in RUNS.items():
        entry = components["runs"][run]
        _require(
            entry["deflator"] == deflator and entry["bls_written_definitions"] is written,
            f"run settings {run}",
        )

    implicates = replication["in_kind_methodology"]["implicates"]
    for year in YEARS:
        checks = components["bls"]["years"][year]["checks"]
        _require(
            abs(checks["fcsuti_error_dollars"]) < BLS_IDENTITY_TOLERANCE_DOLLARS
            and all(
                abs(error) < BLS_IDENTITY_TOLERANCE_DOLLARS
                for error in checks["threshold_error_dollars"].values()
            ),
            f"BLS's shares reproduce its thresholds and FCSUti within "
            f"${BLS_IDENTITY_TOLERANCE_DOLLARS:.5f} in {year}",
        )
    for year in YEARS:
        record = replication["results"][year]
        baseline = current["results"][year]["variants"]["exclude_unresolved"]
        published = components["bls"]["years"][year]["published_thresholds"]
        _require(len(record["with_in_kind_by_implicate"]) == implicates, f"implicates {year}")
        for tenure in TENURES:
            label = f"{year} {tenure}"
            _require(
                record["without_in_kind"][tenure] == baseline["thresholds"][tenure],
                f"out-of-pocket threshold {label}",
            )
            _close(record["published"][tenure], current["results"][year]["published"][tenure], f"published {label}")
            _close(published[tenure], record["published"][tenure], f"BLS receipt published {label}")
            _close(
                mean(draw[tenure] for draw in record["with_in_kind_by_implicate"]),
                record["with_in_kind"][tenure],
                f"implicate mean {label}",
            )
            _close(
                _growth(record["without_in_kind"][tenure], record["with_in_kind"][tenure]),
                record["in_kind_lift_percent"][tenure],
                f"in-kind lift {label}",
            )
            package = components["runs"]["package"]["years"][year]
            _close(package["with_in_kind"]["thresholds"][tenure], record["with_in_kind"][tenure], f"package run with {label}")
            _close(package["without_in_kind"]["thresholds"][tenure], record["without_in_kind"][tenure], f"package run without {label}")
            fcsuti = components["runs"]["fcsuti"]["years"][year]
            _close(fcsuti["with_in_kind"]["gap_percent"][tenure], record["fcsuti_deflated"]["gap_percent_with"][tenure], f"FCSUti run with {label}")
            _close(fcsuti["without_in_kind"]["gap_percent"][tenure], record["fcsuti_deflated"]["gap_percent_without"][tenure], f"FCSUti run without {label}")
            for run in RUNS:
                entry = components["runs"][run]["years"][year]
                for stage in ("with_in_kind", "without_in_kind"):
                    _close(
                        _growth(published[tenure], entry[stage]["thresholds"][tenure]),
                        entry[stage]["gap_percent"][tenure],
                        f"{run} {stage} gap {label}",
                    )
    return {"replication": replication, "components": components, "provenance": provenance}


def _imputed_terms(band: dict, components: tuple[str, ...]) -> dict[str, float]:
    """Dollars the named imputed components add to each tenure's threshold."""
    mix, pooled = band["tenure_mix"], band["pooled"]
    shared = sum(pooled[name] for name in SHARED_IMPUTED if name in components)

    def shelter_utility(tenure: str) -> float:
        return sum(
            band["by_tenure"][tenure][name]
            for name in SHELTER_UTILITY_IMPUTED
            if name in components
        )

    pooled_total = shared + sum(mix[tenure] * shelter_utility(tenure) for tenure in TENURES)
    return {
        tenure: ANCHOR_SHARE * (shared + shelter_utility(tenure) + 0.2 * pooled_total)
        for tenure in TENURES
    }


def _amount(block: dict, label: str) -> tuple[float, float, float]:
    _close(block["2025"] - block["2022"], block["rise"], f"rise {label}")
    return block["2022"], block["2025"], block["rise"]


def inkind_figures(inputs: dict) -> dict:
    """Recompute the figures the in-kind tables and prose report."""
    replication, components = inputs["replication"], inputs["components"]
    span = replication["decompositions"]["2022-2025"]
    cpi_ratio = components["inputs"]["cpi"]["cpi_u_ratio_2022_2025"]
    price = span["bls_price_factor"]
    levels = replication["bls_fcsuti_index"]["levels_2013_100"]
    _close(levels["2025"] / levels["2022"], price, "FCSUti index ratio 2022-2025")
    bls_years = components["bls"]["years"]
    bls_span = components["bls"]["growth_2022_2025"]

    figures: dict = {
        "cpi_u_growth": 100 * (cpi_ratio - 1),
        "fcsuti_price_growth": 100 * (price - 1),
        "bls": {},
        "runs": {},
        "amounts": {"bls": {}},
    }

    def share_beyond_cpi(c22: float, c25: float, t22: float, t25: float) -> float:
        return 100 * (c25 - cpi_ratio * c22) / (t25 - cpi_ratio * t22)

    for tenure in TENURES:
        t22 = bls_years["2022"]["published_thresholds"][tenure]
        t25 = bls_years["2025"]["published_thresholds"][tenure]
        growth = _growth(t22, t25)
        row = bls_span["by_tenure"][tenure]
        c22, c25 = row["imputed_term_dollars"]["2022"], row["imputed_term_dollars"]["2025"]
        for year, recorded in (("2022", c22), ("2025", c25)):
            rebuilt = _imputed_terms(bls_years[year]["band"], SHARED_IMPUTED + SHELTER_UTILITY_IMPUTED)
            _close(rebuilt[tenure], recorded, f"BLS imputed terms {year} {tenure}")
        _close(growth, span["published_growth_percent"][tenure], f"BLS growth {tenure}")
        _close(growth, row["growth"], f"BLS receipt growth {tenure}")
        without = _growth(t22 - c22, t25 - c25)
        _close(without, row["growth_without_imputed_terms"], f"BLS growth without imputed terms {tenure}")
        _close(growth - without, row["band_fixed_effect_points"], f"BLS imputed points {tenure}")
        share = share_beyond_cpi(c22, c25, t22, t25)
        _close(share, row["imputed_share_of_growth_beyond_cpi_u_percent"], f"BLS imputed share {tenure}")
        figures["bls"][tenure] = {
            "growth": growth,
            "growth_deflated_by_fcsuti": _growth(price, 1 + growth / 100),
            "growth_without_imputed_terms": without,
            "imputed_points": growth - without,
            "imputed_share_beyond_cpi_u": share,
        }

    for run in RUNS:
        entry = components["runs"][run]
        years = entry["years"]
        out = {}
        for tenure in TENURES:
            row = entry["growth_2022_2025"]["by_tenure"][tenure]
            label = f"{run} {tenure}"
            with22 = years["2022"]["with_in_kind"]["thresholds"][tenure]
            with25 = years["2025"]["with_in_kind"]["thresholds"][tenure]
            without = _growth(
                years["2022"]["without_in_kind"]["thresholds"][tenure],
                years["2025"]["without_in_kind"]["thresholds"][tenure],
            )
            with_stage = _growth(with22, with25)
            _close(with_stage, row["growth_with_stage"], f"growth with stage {label}")
            _close(without, row["growth_without_stage"], f"growth without stage {label}")
            _close(with_stage - without, row["stage_change_points"], f"stage change {label}")
            draws = [
                _growth(first[tenure], last[tenure]) - without
                for first, last in zip(
                    years["2022"]["with_in_kind"]["thresholds_by_implicate"],
                    years["2025"]["with_in_kind"]["thresholds_by_implicate"],
                    strict=True,
                )
            ]
            for index, (draw, recorded) in enumerate(zip(draws, row["stage_change_by_implicate"], strict=True)):
                _close(draw, recorded, f"stage change implicate {index} {label}")
            _close(stdev(draws), row["stage_change_between_implicate_sd"], f"stage change SD {label}")
            c22, c25 = row["imputed_term_dollars"]["2022"], row["imputed_term_dollars"]["2025"]
            share = share_beyond_cpi(c22, c25, with22, with25)
            _close(share, row["imputed_share_of_growth_beyond_cpi_u_percent"], f"imputed share {label}")
            without_terms = _growth(with22 - c22, with25 - c25)
            _close(without_terms, row["growth_without_imputed_terms"], f"growth without imputed terms {label}")
            bls_row = figures["bls"][tenure]
            _close(with_stage - bls_row["growth"], row["growth_less_bls_points"], f"growth less BLS {label}")
            _close(
                without_terms - bls_row["growth_without_imputed_terms"],
                row["growth_without_imputed_terms_less_bls_points"],
                f"growth without imputed terms less BLS {label}",
            )
            out[tenure] = {
                "growth_without_stage": without,
                "growth_with_stage": with_stage,
                "stage_change": with_stage - without,
                "stage_change_sd": stdev(draws),
                "imputed_share_beyond_cpi_u": share,
                "less_bls": with_stage - bls_row["growth"],
                "less_bls_without_imputed_terms": without_terms - bls_row["growth_without_imputed_terms"],
            }
        gaps = {
            stage: {year: dict(years[year][stage]["gap_percent"]) for year in YEARS}
            for stage in ("with_in_kind", "without_in_kind")
        }
        cells = {stage: [gaps[stage][y][t] for y in YEARS for t in TENURES] for stage in gaps}
        figures["runs"][run] = {
            "growth": out,
            "gaps": gaps,
            "mean_absolute_gap": {stage: mean(abs(v) for v in values) for stage, values in cells.items()},
            "gap_range": {stage: (min(values), max(values)) for stage, values in cells.items()},
            "cells_above_bls_with_stage": sum(v > 0 for v in cells["with_in_kind"]),
            "shelter_excess_range": (
                min(years[y]["shelter_excess_dollars"][t] for y in YEARS for t in TENURES),
                max(years[y]["shelter_excess_dollars"][t] for y in YEARS for t in TENURES),
            ),
        }
        figures["amounts"][run] = {
            name: _amount(entry["growth_2022_2025"][name], f"{run} {name}") for name in AMOUNTS
        }
        figures["amounts"][run]["imputed_total_rise_by_implicate"] = list(
            entry["growth_2022_2025"]["imputed_total"]["rise_by_implicate"]
        )

    for name in AMOUNTS:
        figures["amounts"]["bls"][name] = _amount(bls_span[name], f"BLS {name}")
    for year in ("2022", "2025"):
        _close(bls_years[year]["imputed_total"], bls_span["imputed_total"][year], f"BLS imputed total {year}")
        _close(
            bls_years[year]["band"]["by_tenure"]["renter"]["rental_assistance"],
            bls_span["rental_assistance_per_renter"][year],
            f"BLS rental assistance per renter {year}",
        )

    figures["deflator_points"] = {
        tenure: figures["runs"]["fcsuti"]["growth"][tenure]["growth_without_stage"]
        - figures["runs"]["package"]["growth"][tenure]["growth_without_stage"]
        for tenure in TENURES
    }
    figures["rental_assistance_per_renter_growth"] = {
        series: _growth(*figures["amounts"][series]["rental_assistance_per_renter"][:2])
        for series in ("bls", "package", "fcsuti")
    }
    lifts = [replication["results"][y]["in_kind_lift_percent"][t] for y in YEARS for t in TENURES]
    figures["in_kind_lift_range"] = (min(lifts), max(lifts))
    internet = [bls_years[y]["band"]["pooled"]["internet"] for y in YEARS]
    figures["bls_internet_range"] = (min(internet), max(internet))
    rises = [
        rise
        for run in ("package", "fcsuti")
        for rise in figures["amounts"][run]["imputed_total_rise_by_implicate"]
    ]
    figures["imputed_total_rise_implicate_range"] = (min(rises), max(rises))

    # Which components drive the gap between BLS's rise in imputed benefits
    # and the replication's: band means over all units, 2022 to 2025.
    pooled_rise = {}
    for series, bands in (
        ("bls", {year: bls_years[year]["band"] for year in ("2022", "2025")}),
        *(
            (run, {year: components["runs"][run]["years"][year]["with_in_kind"]["band"] for year in ("2022", "2025")})
            for run in ("package", "fcsuti")
        ),
    ):
        rises = {
            name: bands["2025"]["pooled"][name] - bands["2022"]["pooled"][name]
            for name in SHARED_IMPUTED + SHELTER_UTILITY_IMPUTED
        }
        _close(sum(rises.values()), figures["amounts"][series]["imputed_total"][2], f"pooled rises sum {series}")
        pooled_rise[series] = rises
    figures["pooled_rise"] = pooled_rise

    # 2024 to 2025: BLS's split and the replication's growth.
    recent = replication["decompositions"]["2024-2025"]
    results = replication["results"]
    bls_recent = {}
    for tenure in TENURES:
        t24 = bls_years["2024"]["published_thresholds"][tenure]
        t25 = bls_years["2025"]["published_thresholds"][tenure]
        growth = _growth(t24, t25)
        _close(growth, recent["published_growth_percent"][tenure], f"BLS growth 2024-2025 {tenure}")
        _close(
            _growth(results["2024"]["published"][tenure], results["2025"]["published"][tenure]),
            growth,
            f"published growth 2024-2025 {tenure}",
        )
        for stage, key in (("without_in_kind", "growth_percent_without"), ("with_in_kind", "growth_percent_with")):
            _close(
                _growth(results["2024"][stage][tenure], results["2025"][stage][tenure]),
                recent[key][tenure],
                f"replication growth 2024-2025 {stage} {tenure}",
            )
        everything = SHARED_IMPUTED + SHELTER_UTILITY_IMPUTED
        all24 = _imputed_terms(bls_years["2024"]["band"], everything)[tenure]
        all25 = _imputed_terms(bls_years["2025"]["band"], everything)[tenure]
        _close(all25, bls_span["by_tenure"][tenure]["imputed_term_dollars"]["2025"], f"BLS imputed terms 2025 {tenure}")
        rent24 = _imputed_terms(bls_years["2024"]["band"], ("rental_assistance",))[tenure]
        rent25 = _imputed_terms(bls_years["2025"]["band"], ("rental_assistance",))[tenure]
        without = _growth(t24 - all24, t25 - all25)
        bls_recent[tenure] = {
            "growth": growth,
            "growth_without_imputed_terms": without,
            "imputed_points": growth - without,
            "rental_assistance_points": growth - _growth(t24 - rent24, t25 - rent25),
            "replication_without_stage": recent["growth_percent_without"][tenure],
            "replication_with_stage": recent["growth_percent_with"][tenure],
        }
    figures["bls_2024_2025"] = bls_recent
    figures["bls_rental_assistance_per_renter_2024_2025"] = (
        bls_years["2024"]["band"]["by_tenure"]["renter"]["rental_assistance"],
        bls_years["2025"]["band"]["by_tenure"]["renter"]["rental_assistance"],
    )
    return figures

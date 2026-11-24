"""Validated inputs and derived figures for the in-kind benefit section.

``data/inkind/`` holds three receipts from PolicyEngine/spm-calculator, their
provenance record and a checksum manifest:

- ``ce_inkind_replication_2019_2025.json`` replicates 2019-2025 thresholds
  in three stages, under the replication's composite CPI and under BLS's
  FCSUti index: ``without_home_internet``, the out-of-pocket replication in
  ``data/current``; ``without_in_kind``, which adds home internet from the
  CE's MTBI file; and ``with_in_kind``, which adds the calculator's in-kind
  benefit stage to that run. Its schema 2 introduced the first key; before
  it, ``without_in_kind`` named the run without home internet.
- ``ce_inkind_bls_components_2019_2025.json`` recovers BLS's in-band
  component means from its published threshold shares and compares them with
  the replication's, under the CE summary definitions and under the shelter,
  utilities and food restrictions in Garner and Munoz (2021). It records
  each threshold's imputed terms in two accountings of the 0.2 F term BLS
  publishes as its Other share: ``other_spread`` gives each component its
  part of that term, and ``other_separate`` keeps it apart, as BLS's shares
  workbook does. Its schema 3 adds the three stages and, under each
  accounting, our home internet term beside BLS's.
- ``ce_replicate_uncertainty_2019_2025.json`` reruns both price-index runs,
  with home internet, with and without the stage, under each of the CE's 44
  replicate weights and stores every replicate's thresholds, for each
  implicate. It holds no run without home internet.

``load_inkind`` checks the bytes, the provenance, and the receipts' agreement
with each other and with the out-of-pocket replication in ``data/current``.
``inkind_figures`` recomputes every growth rate, gap, share and dollar change
the in-kind tables and prose report from the receipts' thresholds and band
means, and ``uncertainty_figures`` recomputes every standard error the prose
reports from the stored replicate thresholds. Each checks its results against
the values the receipts record and raises ``ValueError`` on any
inconsistency.

Those checks test consistency. A receipt someone edits and reseals, updating
every hash that records it, can keep every relationship they test: reflecting
a year's replicate thresholds around the full-sample estimate leaves each
squared deviation, and so each standard error, unchanged. ``check_receipt_pins``
therefore compares each receipt with the SHA-256 and calculator commit that
``RECEIPT_PINS`` records here, outside ``data/inkind``. Replacing a receipt
takes an edit to ``RECEIPT_PINS``. The module uses the standard library only.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from statistics import mean, stdev, variance

TENURES = ("owner_with_mortgage", "owner_without_mortgage", "renter")
YEARS = tuple(str(year) for year in range(2019, 2026))
REPLICATION = "ce_inkind_replication_2019_2025.json"
COMPONENTS = "ce_inkind_bls_components_2019_2025.json"
UNCERTAINTY = "ce_replicate_uncertainty_2019_2025.json"
PROVENANCE = "provenance.json"
INKIND_FILES = (COMPONENTS, REPLICATION, UNCERTAINTY, PROVENANCE)
CLASSIFICATION = "current_retrospective_research"
# Run name -> (deflator, Garner and Munoz's (2021) shelter, utilities and food restrictions applied).
RUNS = {
    "package": ("package", False),
    "fcsuti": ("fcsuti", False),
    "package_bls_definition": ("package", True),
    "fcsuti_bls_definition": ("fcsuti", True),
}
AMOUNTS = ("imputed_total", "rental_assistance_per_renter", "school_lunch")
# Each receipt's schema. Replication schema 2, component schema 3 and
# replicate schema 2 add home internet: ``without_home_internet`` names the
# out-of-pocket run, and ``without_in_kind`` and ``with_in_kind`` both carry
# home internet. Earlier schemas used ``without_in_kind`` for the run without
# it, so an earlier receipt must fail here rather than pass with that meaning.
# Replicate schema 3 renames a full-sample check and records the threshold
# series' hash; this module reads neither.
REPLICATION_SCHEMA = 2
COMPONENTS_SCHEMA = 3
UNCERTAINTY_SCHEMA = 3
STAGES = ("without_home_internet", "without_in_kind", "with_in_kind")
# The component receipt's two accountings of the Other share.
ACCOUNTINGS = ("other_spread", "other_separate")
# Home internet as the receipts record it: each unit's spending on CE UCC
# 690114 from the MTBI file, added to FCSUti alone and priced with CPI-U
# series CUUR0000SEEE03.
INTERNET_UCC = 690114
INTERNET_CPI_SERIES = "CUUR0000SEEE03"
# BLS's threshold for tenure h is s * (C + SU_h + 0.2 F), with F = C + sum_h
# P_h SU_h. School lunch, WIC and broadband enter the shared term C; LIHEAP
# and rental assistance enter SU_h. ``_imputed_terms`` gives each benefit its
# part of 0.2 F, the component receipt's ``other_spread`` accounting, and
# checks the split against that accounting's imputed-term dollars.
ANCHOR_SHARE = 0.82
SHARED_IMPUTED = ("nslp", "wic", "broadband")
SHELTER_UTILITY_IMPUTED = ("liheap", "rental_assistance")
# The paper states this bound for BLS's share identities, in dollars.
BLS_IDENTITY_TOLERANCE_DOLLARS = 1e-5
# Our runs' imputed terms against a rebuild from their band means: the
# receipt averages each implicate's terms, so the two differ by cents, while
# home internet counted among the terms would add more than $100.
OUR_TERMS_TOLERANCE_DOLLARS = 1.0
# The CE's balanced repeated replication: 44 replicate weights, standard BRR
# (Fay's coefficient 0) through 2024 CE data, and the 43 strata as the
# complete-data degrees of freedom. The windows for 2019-2025 end in 2025Q1,
# so every file they read carries standard BRR weights.
REPLICATES = 44
STANDARD_BRR = 0.0
COMPLETE_DATA_DF = 43
# The receipt reruns the two out-of-pocket price indexes, not the
# Garner–Munoz runs.
UNCERTAINTY_RUNS = ("package", "fcsuti")
# BLS's published threshold standard errors, as the paper records them.
BLS_SERIES = "bls-corrected-2026-07-17"
BLS_REVISED_SEGMENT = "revised_2019_2024"
# Each receipt's SHA-256 and the spm-calculator commit that holds the same
# bytes. We checked each digest against ``git show <commit>:<calculator
# path>`` in PolicyEngine/spm-calculator when we copied the receipt here.
RECEIPT_PINS = {
    REPLICATION: (
        "ea463f56f96ae5425d31ef5e58ed58d20be8759a5a07f91e811b6fa233c1c7d3",
        "83afa0c97c170026fe42b00ec703298a4447eaa8",
    ),
    COMPONENTS: (
        "e70acb195f8e45458f73d01deeea5f800b0192b12542b8a0d218e5d7c4c68c8a",
        "83afa0c97c170026fe42b00ec703298a4447eaa8",
    ),
    UNCERTAINTY: (
        "97836f87c78a3d21dff3a387e2634b4a171dfab7d65b6755546a60cc260cc166",
        "83afa0c97c170026fe42b00ec703298a4447eaa8",
    ),
}
# The growth window whose standard errors the section reports.
GROWTH_WINDOW = ("2022", "2025")


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
    uncertainty = json.loads((data_dir / UNCERTAINTY).read_text())
    provenance = json.loads((data_dir / PROVENANCE).read_text())
    current_bytes = (current_dir / "ce_replication_2019_2025.json").read_bytes()
    current = json.loads(current_bytes)

    _require(
        provenance["classification"]
        == replication["classification"]
        == components["classification"]
        == uncertainty["classification"]
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
        "provenance covers exactly the three receipts",
    )
    receipts = {REPLICATION: replication, COMPONENTS: components, UNCERTAINTY: uncertainty}
    fingerprints: dict[str, str] = {}
    for name, receipt in receipts.items():
        record = provenance["artifacts"][f"data/inkind/{name}"]
        _require(record["sha256"] == manifest[f"data/inkind/{name}"], f"provenance hash {name}")
        _require(record["code_sha256"] == receipt["code_sha256"], f"code fingerprints {name}")
        _require(record["generated_at_git_head"] == receipt["git_head"], f"git head {name}")
        _require(re.fullmatch(r"[0-9a-f]{40}", record["calculator_commit"]) is not None, f"commit {name}")
        # A source file two receipts both fingerprint must carry one hash, so
        # the receipts come from the same imputation and threshold code.
        for path, digest in receipt["code_sha256"].items():
            _require(fingerprints.setdefault(path, digest) == digest, f"{path} differs across receipts")
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
    _require(
        replication.get("schema_version") == REPLICATION_SCHEMA
        and all(set(STAGES) <= set(replication["results"][year]) for year in YEARS),
        f"replication receipt schema {REPLICATION_SCHEMA} with its three stages",
    )
    # Every receipt prices home internet with the same pinned CPI input,
    # and every replication year reads it from UCC 690114 into FCSUti.
    internet = replication["home_internet"]
    internet_cpi = {
        "path": internet["cpi_input"]["path"],
        "series_id": internet["cpi_series"],
        "sha256": internet["cpi_input"]["sha256"],
    }
    _require(
        internet["ucc"] == INTERNET_UCC
        and internet["cpi_series"] == INTERNET_CPI_SERIES
        and components["inputs"]["internet_cpi"] == internet_cpi
        and all(
            replication["results"][year]["home_internet"]["ucc"] == INTERNET_UCC
            and replication["results"][year]["home_internet"]["cpi_series"] == INTERNET_CPI_SERIES
            and replication["results"][year]["home_internet"]["enters"] == "fcsuti"
            for year in YEARS
        ),
        f"home internet from UCC {INTERNET_UCC}, priced with {INTERNET_CPI_SERIES}, in FCSUti",
    )
    _require(
        components.get("schema_version") == COMPONENTS_SCHEMA
        and tuple(sorted(components.get("accountings", ()))) == tuple(sorted(ACCOUNTINGS)),
        f"component receipt schema {COMPONENTS_SCHEMA} with both accountings of the Other share",
    )
    growth_rows = [components["bls"]["growth_2022_2025"]["by_tenure"]] + [
        components["runs"][run]["growth_2022_2025"]["by_tenure"] for run in RUNS
    ]
    level_rows = [
        components["runs"][run]["years"][year]["level_gap_percent_of_bls"]
        for run in ("package", "package_bls_definition")
        for year in YEARS
    ]
    _require(
        all(set(ACCOUNTINGS) <= set(rows.get(tenure, ())) for rows in growth_rows for tenure in TENURES)
        and all(set(ACCOUNTINGS) <= set(gaps) for gaps in level_rows)
        and all(set(TENURES) <= set(gaps[accounting]) for gaps in level_rows for accounting in ACCOUNTINGS)
        and all(
            set(STAGES) <= set(components["runs"][run]["years"][year])
            and set(ACCOUNTINGS) <= set(components["runs"][run]["years"][year].get("home_internet", ()))
            for run in RUNS
            for year in YEARS
        ),
        f"component receipt schema {COMPONENTS_SCHEMA} with both accountings of the Other share",
    )
    for run, (deflator, garner_munoz) in RUNS.items():
        entry = components["runs"][run]
        _require(
            entry["deflator"] == deflator and entry["bls_written_definitions"] is garner_munoz,
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
        # The largest gap, across tenures, between each published share and
        # the receipt's Other-separate term over the threshold, in dollars of
        # band mean: the share gap times the threshold, over s.
        largest = max(components["bls"]["years"][year]["published_thresholds"].values())
        _require(
            all(
                abs(error) * largest / ANCHOR_SHARE < BLS_IDENTITY_TOLERANCE_DOLLARS
                for error in checks["other_separate_share_error"].values()
            ),
            f"the Other-separate terms reproduce each share BLS publishes within "
            f"${BLS_IDENTITY_TOLERANCE_DOLLARS:.5f} in {year}",
        )
    for year in YEARS:
        record = replication["results"][year]
        baseline = current["results"][year]["variants"]["exclude_unresolved"]
        published = components["bls"]["years"][year]["published_thresholds"]
        _require(len(record["with_in_kind_by_implicate"]) == implicates, f"implicates {year}")
        for tenure in TENURES:
            label = f"{year} {tenure}"
            # The run without home internet or benefits is the out-of-pocket
            # replication, to the bit.
            _require(
                record["without_home_internet"][tenure] == baseline["thresholds"][tenure],
                f"out-of-pocket threshold {label}",
            )
            _close(record["published"][tenure], current["results"][year]["published"][tenure], f"published {label}")
            _close(published[tenure], record["published"][tenure], f"BLS receipt published {label}")
            _close(
                mean(draw[tenure] for draw in record["with_in_kind_by_implicate"]),
                record["with_in_kind"][tenure],
                f"implicate mean {label}",
            )
            # Each stage's effect, as the receipt records it, follows from
            # the thresholds on either side of it.
            effects = record["stage_effects"]
            _close(
                record["without_in_kind"][tenure] - record["without_home_internet"][tenure],
                effects["home_internet_dollars"][tenure],
                f"home internet stage {label}",
            )
            _close(
                _growth(record["without_home_internet"][tenure], record["without_in_kind"][tenure]),
                effects["home_internet_percent"][tenure],
                f"home internet lift {label}",
            )
            _close(
                record["with_in_kind"][tenure] - record["without_in_kind"][tenure],
                effects["in_kind_dollars"][tenure],
                f"in-kind stage {label}",
            )
            _close(
                _growth(record["without_in_kind"][tenure], record["with_in_kind"][tenure]),
                record["in_kind_lift_percent"][tenure],
                f"in-kind lift {label}",
            )
            _close(effects["in_kind_percent"][tenure], record["in_kind_lift_percent"][tenure], f"in-kind stage lift {label}")
            _close(
                _growth(published[tenure], record["without_home_internet"][tenure]),
                record["gap_percent_without_home_internet"][tenure],
                f"out-of-pocket gap {label}",
            )
            package = components["runs"]["package"]["years"][year]
            _close(package["with_in_kind"]["thresholds"][tenure], record["with_in_kind"][tenure], f"package run with {label}")
            _close(package["without_in_kind"]["thresholds"][tenure], record["without_in_kind"][tenure], f"package run without {label}")
            _close(
                package["without_home_internet"]["thresholds"][tenure],
                record["without_home_internet"][tenure],
                f"package run without home internet {label}",
            )
            fcsuti = components["runs"]["fcsuti"]["years"][year]
            deflated = record["fcsuti_deflated"]
            _close(fcsuti["with_in_kind"]["gap_percent"][tenure], deflated["gap_percent_with"][tenure], f"FCSUti run with {label}")
            _close(fcsuti["without_in_kind"]["gap_percent"][tenure], deflated["gap_percent_without"][tenure], f"FCSUti run without {label}")
            _close(
                fcsuti["without_home_internet"]["thresholds"][tenure],
                deflated["without_home_internet"][tenure],
                f"FCSUti run without home internet {label}",
            )
            _close(
                _growth(deflated["without_home_internet"][tenure], deflated["without_in_kind"][tenure]),
                deflated["home_internet_percent"][tenure],
                f"FCSUti home internet lift {label}",
            )
            for run in RUNS:
                entry = components["runs"][run]["years"][year]
                for stage in STAGES:
                    _close(
                        _growth(published[tenure], entry[stage]["thresholds"][tenure]),
                        entry[stage]["gap_percent"][tenure],
                        f"{run} {stage} gap {label}",
                    )
    _check_uncertainty_receipt(uncertainty, replication, components, manifest)
    return {
        "replication": replication,
        "components": components,
        "uncertainty": uncertainty,
        "provenance": provenance,
    }


def _check_uncertainty_receipt(uncertainty: dict, replication: dict, components: dict, manifest: dict) -> None:
    """Check that the replicate receipt names the other two receipts' hashes,
    reads the replication's raw CE, CPS ASEC and CPI files with its seed, and
    starts from both receipts' full-sample thresholds. These checks test
    consistency, not authenticity: ``check_receipt_pins`` covers a receipt
    resealed with altered replicates. Runs after every other check, so an
    edit to the replication or component receipt fails where those checks
    catch it. Every replicate run carries home internet: its
    ``without_in_kind`` is the replication's run with home internet and no
    benefits."""
    _require(
        uncertainty.get("schema_version") == UNCERTAINTY_SCHEMA,
        f"replicate receipt schema {UNCERTAINTY_SCHEMA} with home internet",
    )
    for name, key in ((REPLICATION, "replication_receipt"), (COMPONENTS, "components_receipt")):
        _require(
            uncertainty["inputs"][key]["sha256"] == manifest[f"data/inkind/{name}"],
            f"uncertainty receipt derives from the recorded {key.replace('_', ' ')}",
        )
    inputs = uncertainty["inputs"]
    _require(
        inputs["ce_bundles"] == replication["ce_bundles"]
        and inputs["cps_asec_files"] == replication["cps_asec_files"]
        and inputs["cpi"] == replication["cpi_input"]
        and {key: components["inputs"]["cpi"][key] for key in ("path", "sha256")} == replication["cpi_input"]
        and inputs["internet_cpi"] == components["inputs"]["internet_cpi"]
        and inputs["imputation_seed"] == replication["in_kind_methodology"]["seed"],
        "uncertainty receipt reads the replication receipt's raw inputs and seed",
    )
    method = uncertainty["method"]
    implicates = replication["in_kind_methodology"]["implicates"]
    _require(
        uncertainty["complete"] is True
        and uncertainty["replicates_run"] == method["replicates"] == REPLICATES
        and method["fay_coefficient"] == STANDARD_BRR
        and method["complete_data_df"] == COMPLETE_DATA_DF
        and uncertainty["inputs"]["implicates"] == implicates,
        "uncertainty receipt runs standard BRR over every replicate and implicate",
    )
    full_sample = {
        "package": lambda year: (
            replication["results"][year]["with_in_kind_by_implicate"],
            replication["results"][year]["without_in_kind"],
        ),
        "fcsuti": lambda year: (
            components["runs"]["fcsuti"]["years"][year]["with_in_kind"]["thresholds_by_implicate"],
            components["runs"]["fcsuti"]["years"][year]["without_in_kind"]["thresholds"],
        ),
    }
    for run in UNCERTAINTY_RUNS:
        _require(set(uncertainty["runs"][run]["years"]) == set(YEARS), f"uncertainty years {run}")
        for year in YEARS:
            entry = uncertainty["runs"][run]["years"][year]
            replicates = entry["replicates"]
            by_implicate, without = full_sample[run](year)
            published = components["bls"]["years"][year]["published_thresholds"]
            for tenure in TENURES:
                label = f"{run} {year} {tenure}"
                draws = replicates["with_in_kind"][tenure]
                _require(
                    len(draws) == implicates
                    and all(len(draw) == 1 + REPLICATES for draw in draws)
                    and len(replicates["without_in_kind"][tenure]) == 1 + REPLICATES,
                    f"replicate counts {label}",
                )
                for index, (draw, full) in enumerate(zip(draws, by_implicate, strict=True)):
                    _close(draw[0], full[tenure], f"full-sample threshold with benefits, implicate {index}, {label}")
                _close(replicates["without_in_kind"][tenure][0], without[tenure], f"full-sample threshold without benefits {label}")
                _close(entry["bls"]["thresholds"][tenure], published[tenure], f"BLS threshold in the uncertainty receipt {label}")


def _imputed_terms(band: dict, components: tuple[str, ...]) -> dict[str, float]:
    """Dollars the named imputed components add to each tenure's threshold,
    each with its part of 0.2 F (the ``other_spread`` accounting)."""
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
        spread = row["other_spread"]
        c22, c25 = spread["imputed_term_dollars"]["2022"], spread["imputed_term_dollars"]["2025"]
        for year, recorded in (("2022", c22), ("2025", c25)):
            rebuilt = _imputed_terms(bls_years[year]["band"], SHARED_IMPUTED + SHELTER_UTILITY_IMPUTED)
            _close(rebuilt[tenure], recorded, f"BLS imputed terms {year} {tenure}")
        _close(growth, span["published_growth_percent"][tenure], f"BLS growth {tenure}")
        _close(growth, row["growth"], f"BLS receipt growth {tenure}")
        without = _growth(t22 - c22, t25 - c25)
        _close(without, spread["growth_without_imputed_terms"], f"BLS growth without imputed terms {tenure}")
        _close(growth - without, spread["band_fixed_effect_points"], f"BLS imputed points {tenure}")
        share = share_beyond_cpi(c22, c25, t22, t25)
        _close(share, spread["imputed_share_of_growth_beyond_cpi_u_percent"], f"BLS imputed share {tenure}")
        figures["bls"][tenure] = {
            "growth": growth,
            "growth_deflated_by_fcsuti": _growth(price, 1 + growth / 100),
            "growth_without_imputed_terms": without,
            "imputed_points": growth - without,
            "imputed_share_beyond_cpi_u": share,
        }

    # The replication receipt's own 2022-2025 growth without home internet or
    # benefits, for the two runs it deflates: the component receipt records
    # no growth for that stage, so we recompute it from each run's thresholds.
    no_internet_growth = {
        "package": span["growth_percent_without_home_internet"],
        "fcsuti": span["fcsuti_deflated"]["growth_percent_without_home_internet"],
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
            no_internet = _growth(
                years["2022"]["without_home_internet"]["thresholds"][tenure],
                years["2025"]["without_home_internet"]["thresholds"][tenure],
            )
            if run in no_internet_growth:
                _close(no_internet, no_internet_growth[run][tenure], f"growth without home internet {label}")
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
            spread, separate = row["other_spread"], row["other_separate"]
            c22, c25 = spread["imputed_term_dollars"]["2022"], spread["imputed_term_dollars"]["2025"]
            # Our terms, like BLS's, sum only the benefits, so home internet
            # stays with out-of-pocket spending.
            for year, recorded in (("2022", c22), ("2025", c25)):
                rebuilt = _imputed_terms(years[year]["with_in_kind"]["band"], SHARED_IMPUTED + SHELTER_UTILITY_IMPUTED)
                _require(
                    abs(rebuilt[tenure] - recorded) < OUR_TERMS_TOLERANCE_DOLLARS,
                    f"our imputed terms rebuild from the band means {year} {label}",
                )
            share = share_beyond_cpi(c22, c25, with22, with25)
            _close(share, spread["imputed_share_of_growth_beyond_cpi_u_percent"], f"imputed share {label}")
            for year in ("2022", "2025"):
                _close(
                    _benefit_rows(years[year]["with_in_kind"]["band"])[tenure],
                    separate["imputed_term_dollars"][year],
                    f"benefit rows {year} {label}",
                )
            share_separate = separate["imputed_share_of_growth_beyond_cpi_u_percent"]
            _close(
                share_beyond_cpi(
                    separate["imputed_term_dollars"]["2022"], separate["imputed_term_dollars"]["2025"], with22, with25
                ),
                share_separate,
                f"imputed share, Other separate {label}",
            )
            without_terms = _growth(with22 - c22, with25 - c25)
            _close(without_terms, spread["growth_without_imputed_terms"], f"growth without imputed terms {label}")
            bls_row = figures["bls"][tenure]
            _close(with_stage - bls_row["growth"], row["growth_less_bls_points"], f"growth less BLS {label}")
            _close(
                without_terms - bls_row["growth_without_imputed_terms"],
                spread["growth_without_imputed_terms_less_bls_points"],
                f"growth without imputed terms less BLS {label}",
            )
            out[tenure] = {
                "growth_without_home_internet": no_internet,
                "growth_without_stage": without,
                "growth_with_stage": with_stage,
                "internet_change": without - no_internet,
                "stage_change": with_stage - without,
                "stage_change_sd": stdev(draws),
                "imputed_share_beyond_cpi_u": share,
                "imputed_share_beyond_cpi_u_other_separate": share_separate,
                "less_bls": with_stage - bls_row["growth"],
                "less_bls_without_imputed_terms": without_terms - bls_row["growth_without_imputed_terms"],
            }
        gaps = {stage: {year: dict(years[year][stage]["gap_percent"]) for year in YEARS} for stage in STAGES}
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
    # Home internet's lift to each threshold over the out-of-pocket run, by
    # tenure across the seven years, as the replication receipt records it.
    internet_lifts = {
        tenure: [replication["results"][y]["stage_effects"]["home_internet_percent"][tenure] for y in YEARS]
        for tenure in TENURES
    }
    figures["home_internet_lift_range"] = {tenure: (min(v), max(v)) for tenure, v in internet_lifts.items()}
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
        for stage, key in (
            ("without_home_internet", "growth_percent_without_home_internet"),
            ("without_in_kind", "growth_percent_without"),
            ("with_in_kind", "growth_percent_with"),
        ):
            _close(
                _growth(results["2024"][stage][tenure], results["2025"][stage][tenure]),
                recent[key][tenure],
                f"replication growth 2024-2025 {stage} {tenure}",
            )
        everything = SHARED_IMPUTED + SHELTER_UTILITY_IMPUTED
        all24 = _imputed_terms(bls_years["2024"]["band"], everything)[tenure]
        all25 = _imputed_terms(bls_years["2025"]["band"], everything)[tenure]
        _close(
            all25,
            bls_span["by_tenure"][tenure]["other_spread"]["imputed_term_dollars"]["2025"],
            f"BLS imputed terms 2025 {tenure}",
        )
        rent24 = _imputed_terms(bls_years["2024"]["band"], ("rental_assistance",))[tenure]
        rent25 = _imputed_terms(bls_years["2025"]["band"], ("rental_assistance",))[tenure]
        without = _growth(t24 - all24, t25 - all25)
        bls_recent[tenure] = {
            "growth": growth,
            "growth_without_imputed_terms": without,
            "imputed_points": growth - without,
            "rental_assistance_points": growth - _growth(t24 - rent24, t25 - rent25),
            "replication_without_home_internet": recent["growth_percent_without_home_internet"][tenure],
            "replication_without_stage": recent["growth_percent_without"][tenure],
            "replication_with_stage": recent["growth_percent_with"][tenure],
        }
    figures["bls_2024_2025"] = bls_recent
    figures["bls_rental_assistance_per_renter_2024_2025"] = (
        bls_years["2024"]["band"]["by_tenure"]["renter"]["rental_assistance"],
        bls_years["2025"]["band"]["by_tenure"]["renter"]["rental_assistance"],
    )
    package_years = components["runs"]["package"]["years"]
    figures["rental_assistance_per_renter_2024_2025"] = tuple(
        mean(package_years[year]["with_in_kind"]["rental_assistance_per_renter_by_implicate"])
        for year in ("2024", "2025")
    )
    figures["accounting"] = _growth_accounting(figures, components, cpi_ratio, price)
    figures["accounting_other_separate"] = _growth_accounting_other_separate(components, cpi_ratio, price)
    figures["rank_shift"] = _rank_shift(components)
    figures.update(_internet_and_levels(components))
    figures["year_table"] = _year_table(components, figures)
    figures["cpi_u_growth_bls_vintage"] = _growth(1, cpi_ratio * BLS_2025_CPI_U_INTERPOLATED / OFFICIAL_2025_CPI_U)
    return figures


# BLS's 2025 thresholds page (last modified September 24, 2026; read in a
# browser on 2026-11-11) gives 2025 CPI-U as a twelve-month average with
# October 2025 interpolated, 138.289 (2013 = 100), against the official
# eleven-month average of 138.198, and 2024-2025 growth of 2.699 percent
# against 2.631. ``check_cpi_vintage`` ties the two index values to those
# growth rates and the first rate to the paper's record of the page.
BLS_2025_CPI_U_INTERPOLATED = 138.289
OFFICIAL_2025_CPI_U = 138.198
BLS_2025_CPI_U_GROWTH = (2.699, 2.631)


def check_cpi_vintage(recorded_growth: float) -> None:
    interpolated, official = BLS_2025_CPI_U_GROWTH
    _require(
        abs(BLS_2025_CPI_U_INTERPOLATED / OFFICIAL_2025_CPI_U - (1 + interpolated / 100) / (1 + official / 100))
        < 1e-5,
        "BLS's interpolated and official 2025 CPI-U agree with its two growth rates",
    )
    _require(abs(recorded_growth - interpolated) < 1e-9, "BLS's page growth for 2025 CPI-U")


def _three_parts(b22: float, b25: float, i22: float, i25: float, cpi_ratio: float, price: float, label: str) -> dict:
    """Split one BLS threshold's 2022-2025 growth beyond CPI-U into three
    parts, in points of its 2022 level, with phi the FCSUti factor, pi
    CPI-U's, and I the dollars the imputed benefits put in the threshold:
    the index's growth beyond CPI-U on the rest of the threshold,
    (phi - pi)(B22 - I22) / B22; the benefits' growth beyond CPI-U,
    (I25 - pi I22) / B22; and growth in the rest beyond the index,
    ((B25 - I25) - phi (B22 - I22)) / B22. The parts sum to
    (B25 - pi B22) / B22 exactly. The same split with the index's lead on
    the whole threshold moves (phi - pi) I22 / B22 from the benefits'
    part to the prices' part and leaves the third part unchanged."""
    parts = {
        "prices": 100 * (price - cpi_ratio) * (b22 - i22) / b22,
        "benefits": 100 * (i25 - cpi_ratio * i22) / b22,
        "out_of_pocket": 100 * ((b25 - i25) - price * (b22 - i22)) / b22,
    }
    excess = 100 * (b25 - cpi_ratio * b22) / b22
    _close(sum(parts.values()), excess, f"growth accounting sums to growth beyond CPI-U {label}")
    _require(all(value > 0 for value in parts.values()), f"accounting parts positive {label}")
    index_on_benefits = {
        "prices": 100 * (price - cpi_ratio),
        "benefits": 100 * (i25 - price * i22) / b22,
        "out_of_pocket": parts["out_of_pocket"],
    }
    _close(
        sum(index_on_benefits.values()),
        excess,
        f"growth accounting with the index on the benefits sums to growth beyond CPI-U {label}",
    )
    return {
        "excess": excess,
        **parts,
        "shares": {name: 100 * value / excess for name, value in parts.items()},
        "index_on_benefits_shares": {name: 100 * value / excess for name, value in index_on_benefits.items()},
    }


def _growth_accounting(figures: dict, components: dict, cpi_ratio: float, price: float) -> dict:
    """The three-part split of each BLS threshold's 2022-2025 growth beyond
    CPI-U, with I the imputed benefits' terms the component receipt records
    under ``other_spread``: each benefit's band mean times s, with its part
    of the Other share, 0.2 F. The benefits' part over the growth beyond
    CPI-U must equal the share the receipt records for that accounting."""
    bls_years = components["bls"]["years"]
    out = {}
    for tenure in TENURES:
        b22 = bls_years["2022"]["published_thresholds"][tenure]
        b25 = bls_years["2025"]["published_thresholds"][tenure]
        spread = components["bls"]["growth_2022_2025"]["by_tenure"][tenure]["other_spread"]
        terms = spread["imputed_term_dollars"]
        split = _three_parts(b22, b25, terms["2022"], terms["2025"], cpi_ratio, price, tenure)
        _close(
            split["shares"]["benefits"],
            figures["bls"][tenure]["imputed_share_beyond_cpi_u"],
            f"accounting's benefit share {tenure}",
        )
        _close(
            split["shares"]["benefits"],
            spread["imputed_share_of_growth_beyond_cpi_u_percent"],
            f"accounting's benefit share matches the receipt's, Other spread {tenure}",
        )
        out[tenure] = split
    return out


# BLS's shares workbook reports each threshold's 0.2 F term as its own row,
# "Other Share", and five rows for the benefits. A row's share times the
# threshold gives s times the benefit's band mean: school lunch and WIC at
# equal dollars in every tenure, and LIHEAP, rental assistance and the
# broadband subsidy at tenure h's own means, which BLS reports by tenure.
BENEFIT_ROWS_SHARED = ("nslp", "wic")
BENEFIT_ROWS_BY_TENURE = ("broadband", "liheap", "rental_assistance")


def _benefit_rows(band: dict) -> dict[str, float]:
    """Dollars BLS's five benefit rows put in each tenure's threshold."""
    shared = sum(band["pooled"][name] for name in BENEFIT_ROWS_SHARED)
    return {
        tenure: ANCHOR_SHARE * (shared + sum(band["by_tenure"][tenure][name] for name in BENEFIT_ROWS_BY_TENURE))
        for tenure in TENURES
    }


def _growth_accounting_other_separate(components: dict, cpi_ratio: float, price: float) -> dict:
    """The same split with the Other share kept separate, as BLS's shares
    workbook reports it: I counts only the benefits' five rows, and the
    Other share, the benefits' 0.2 included, joins the rest of the
    threshold. I is the dollars the component receipt records under
    ``other_separate``, which must equal the five rows rebuilt from the
    band, and the benefits' part of the growth must equal the share it
    records there. A tenure's rows fall short of its ``other_spread`` terms
    by s (0.2 A + b - b_h), with A the band's mean imputed benefits, b its
    mean broadband subsidy and b_h tenure h's. Each tenure-specific row's
    band mean must also pool to the band's mean under BLS's tenure mix."""
    bls_years = components["bls"]["years"]
    for year in ("2022", "2025"):
        band = bls_years[year]["band"]
        for name in BENEFIT_ROWS_BY_TENURE:
            _close(
                band["pooled"][name],
                sum(band["tenure_mix"][tenure] * band["by_tenure"][tenure][name] for tenure in TENURES),
                f"band mean of {name} pools the tenures' means {year}",
            )
    rebuilt = {year: _benefit_rows(bls_years[year]["band"]) for year in ("2022", "2025")}
    out = {}
    for tenure in TENURES:
        row = components["bls"]["growth_2022_2025"]["by_tenure"][tenure]
        terms = row["other_spread"]["imputed_term_dollars"]
        rows = row["other_separate"]["imputed_term_dollars"]
        for year in ("2022", "2025"):
            band = bls_years[year]["band"]
            _close(rebuilt[year][tenure], rows[year], f"benefit rows match the receipt's {year} {tenure}")
            _close(
                terms[year] - rows[year],
                ANCHOR_SHARE
                * (
                    0.2 * bls_years[year]["imputed_total"]
                    + band["pooled"]["broadband"]
                    - band["by_tenure"][tenure]["broadband"]
                ),
                f"benefit rows fall short of the benefits' terms by their Other share {year} {tenure}",
            )
        split = _three_parts(
            bls_years["2022"]["published_thresholds"][tenure],
            bls_years["2025"]["published_thresholds"][tenure],
            rows["2022"],
            rows["2025"],
            cpi_ratio,
            price,
            f"{tenure}, Other separate",
        )
        _close(
            split["shares"]["benefits"],
            row["other_separate"]["imputed_share_of_growth_beyond_cpi_u_percent"],
            f"accounting's benefit share matches the receipt's, Other separate {tenure}",
        )
        out[tenure] = split
    return out


def _rank_shift(components: dict) -> dict[str, float]:
    """How much the benefits move our 2022-2025 growth by changing which
    units fall in the band: the full with-and-without change less the
    change with each year's band held as it stands."""
    out = {}
    for tenure in TENURES:
        row = components["runs"]["package"]["growth_2022_2025"]["by_tenure"][tenure]
        spread = row["other_spread"]
        _close(
            row["growth_with_stage"] - spread["growth_without_imputed_terms"],
            spread["band_fixed_effect_points"],
            f"band-fixed effect {tenure}",
        )
        _close(
            row["stage_change_points"] - spread["band_fixed_effect_points"],
            spread["rank_shift_points"],
            f"rank shift {tenure}",
        )
        out[tenure] = spread["rank_shift_points"]
    return out


def _internet_and_levels(components: dict) -> dict:
    """Home internet's term in each threshold, ours beside BLS's, as the
    component receipt's ``home_internet`` record gives it under both
    accountings, each checked against the band means. With the Other share
    spread, each side's term is s * 1.2 times its band's mean home internet;
    with it kept separate, as BLS's workbook publishes it, s times that mean
    plus the band's mean broadband subsidy less the tenure's own, which
    leaves internet's part of 0.2 F in the Other share. Our term is a percent
    of our threshold with home internet and benefits, BLS's of its published
    threshold, and each run's level gap for internet is our term less BLS's
    over BLS's threshold. The figures come from the package run, whose band
    the section reports. Also the Garner–Munoz runs' owner rent."""
    bls_years = components["bls"]["years"]

    def terms(band: dict, tenure: str) -> dict[str, float]:
        pooled = band["pooled"]
        return {
            "other_spread": ANCHOR_SHARE * 1.2 * pooled["internet"],
            "other_separate": ANCHOR_SHARE
            * (pooled["internet"] + pooled["broadband"] - band["by_tenure"][tenure]["broadband"]),
        }

    shares = {(side, accounting): [] for side in ("ours", "bls") for accounting in ACCOUNTINGS}
    for year in YEARS:
        bls_band = bls_years[year]["band"]
        for run in ("package", "package_bls_definition"):
            entry = components["runs"][run]["years"][year]
            ours_band = entry["with_in_kind"]["band"]
            for tenure in TENURES:
                label = f"{run} {year} {tenure}"
                published = bls_years[year]["published_thresholds"][tenure]
                ours_terms, bls_terms = terms(ours_band, tenure), terms(bls_band, tenure)
                for accounting in ACCOUNTINGS:
                    record = entry["home_internet"][accounting][tenure]
                    _close(record["ours_dollars"], ours_terms[accounting], f"our internet term, {accounting} {label}")
                    _close(record["bls_dollars"], bls_terms[accounting], f"BLS internet term, {accounting} {label}")
                    _close(
                        record["ours_percent_of_threshold"],
                        100 * record["ours_dollars"] / entry["with_in_kind"]["thresholds"][tenure],
                        f"our internet share, {accounting} {label}",
                    )
                    _close(
                        record["bls_percent_of_threshold"],
                        100 * record["bls_dollars"] / published,
                        f"BLS internet share, {accounting} {label}",
                    )
                    gaps = entry["level_gap_percent_of_bls"][accounting][tenure]
                    _close(
                        gaps["terms"]["internet"],
                        100 * (record["ours_dollars"] - record["bls_dollars"]) / published,
                        f"internet level term, {accounting} {label}",
                    )
                    _close(
                        gaps["total"],
                        entry["with_in_kind"]["gap_percent"][tenure],
                        f"level terms total, {accounting} {label}",
                    )
                    if run == "package":
                        shares[("ours", accounting)].append(record["ours_percent_of_threshold"])
                        shares[("bls", accounting)].append(record["bls_percent_of_threshold"])
    ours = [components["runs"]["package"]["years"][year]["with_in_kind"]["band"]["pooled"]["internet"] for year in YEARS]
    bls = [bls_years[year]["band"]["pooled"]["internet"] for year in YEARS]
    ratios = [a / b for a, b in zip(ours, bls, strict=True)]
    # Owners' spending under the CE's rented-dwelling summary, which the
    # Garner–Munoz runs keep: per owner without a mortgage in the band.
    kept = [
        components["runs"]["package_bls_definition"]["years"][year]["with_in_kind"]["band_pieces"][
            "owner_without_mortgage"
        ]["rent_and_rental_costs"]
        for year in YEARS
    ]

    def span(values: list[float]) -> tuple[float, float]:
        return (min(values), max(values))

    return {
        "bls_internet_share_range": span(shares[("bls", "other_spread")]),
        "bls_internet_row_share_range": span(shares[("bls", "other_separate")]),
        "our_internet_share_range": span(shares[("ours", "other_spread")]),
        "our_internet_row_share_range": span(shares[("ours", "other_separate")]),
        "our_internet_range": span(ours),
        "internet_ratio_range": span(ratios),
        "garner_munoz_owner_rent_range": span(kept),
    }


def _year_table(components: dict, figures: dict) -> dict:
    """BLS's and our band means in every threshold year: all imputed
    benefits per unit and rental assistance per renter."""
    out = {}
    for year in YEARS:
        bls = components["bls"]["years"][year]
        ours = components["runs"]["package"]["years"][year]["with_in_kind"]
        _close(mean(ours["imputed_total_by_implicate"]), ours["imputed_total"], f"imputed total implicate mean {year}")
        out[year] = {
            "bls_total": bls["imputed_total"],
            "bls_rent": bls["band"]["by_tenure"]["renter"]["rental_assistance"],
            "total": ours["imputed_total"],
            "rent": mean(ours["rental_assistance_per_renter_by_implicate"]),
        }
    for year, column in (("2022", 0), ("2025", 1)):
        _close(out[year]["total"], figures["amounts"]["package"]["imputed_total"][column], f"year table total {year}")
        _close(out[year]["rent"], figures["amounts"]["package"]["rental_assistance_per_renter"][column], f"year table rent {year}")
        _close(out[year]["bls_rent"], figures["amounts"]["bls"]["rental_assistance_per_renter"][column], f"year table BLS rent {year}")
    early = [out[year]["rent"] / out[year]["bls_rent"] - 1 for year in YEARS if int(year) <= 2023]
    figures_range = (100 * min(early), 100 * max(early))
    return {"years": out, "rent_excess_2019_2023": figures_range}


def published_standard_errors(data_dir: Path) -> dict[str, dict[str, float]]:
    """BLS's published threshold standard errors for 2019-2025 from the
    paper's own records: the revised 2019-2024 series and the 2025 workbook.
    The paper's checksum manifest covers both files."""
    series = json.loads((data_dir / "threshold_series.json").read_text())
    revised = series["series"][BLS_SERIES]["segments"][BLS_REVISED_SEGMENT]["years"]
    out = {
        year: {tenure: revised[year][tenure]["standard_error"] for tenure in TENURES}
        for year in YEARS
        if year in revised
    }
    out["2025"] = {
        tenure: json.loads((data_dir / "bls_2025_thresholds.json").read_text())["standard_errors"][tenure]
        for tenure in TENURES
    }
    _require(set(out) == set(YEARS), "BLS standard errors for every year")
    return out


def _replicate_variance(full: float, replicates: list[float]) -> float:
    """Standard BRR: squared deviations of the 44 replicate estimates from
    the full-sample estimate, summed and divided by 44 (BLS, "Standard Errors
    in the Consumer Expenditure Surveys")."""
    _require(len(replicates) == REPLICATES, f"{REPLICATES} replicates")
    return sum((value - full) ** 2 for value in replicates) / (REPLICATES * (1 - STANDARD_BRR) ** 2)


def _rubin(series: list[list[float]]) -> dict[str, float]:
    """Rubin's rules over implicates, each given as [full sample, replicates
    1-44]: T = U + (1 + 1/M) B, with Barnard and Rubin's degrees of freedom on
    the CE's 43 complete-data degrees of freedom."""
    m = len(series)
    _require(m >= 2, "at least two implicates")
    estimates = [values[0] for values in series]
    within = mean(_replicate_variance(values[0], values[1:]) for values in series)
    between = variance(estimates)
    total = within + (1 + 1 / m) * between
    fraction = (1 + 1 / m) * between / total if total > 0 else 0.0
    observed = COMPLETE_DATA_DF * (COMPLETE_DATA_DF + 1) * (1 - fraction) / (COMPLETE_DATA_DF + 3)
    df = 1 / (fraction**2 / (m - 1) + 1 / observed) if observed > 0 else 0.0
    return {
        "estimate": mean(estimates),
        "within_variance": within,
        "between_variance": between,
        "total_variance": total,
        "standard_error": math.sqrt(total),
        "fraction_missing_information": fraction,
        "df": df,
    }


def _check_combined(recomputed: dict[str, float], recorded: dict, label: str) -> None:
    for key in ("estimate", "within_variance", "between_variance", "standard_error", "fraction_missing_information", "df"):
        _close(recomputed[key], recorded[key], f"{key.replace('_', ' ')} {label}")


def uncertainty_figures(inputs: dict, published_se: dict[str, dict[str, float]]) -> dict:
    """Recompute, from the stored replicate thresholds, every standard error
    the prose reports, and check each against the receipt."""
    uncertainty, components = inputs["uncertainty"], inputs["components"]
    first, last = GROWTH_WINDOW
    figures: dict = {"runs": {}, "growth_window": GROWTH_WINDOW}
    for run in UNCERTAINTY_RUNS:
        entry = uncertainty["runs"][run]
        ratios: dict = {"with_in_kind": {t: [] for t in TENURES}, "without_in_kind": {t: [] for t in TENURES}}
        for year in YEARS:
            record = entry["years"][year]
            replicates = record["replicates"]
            for tenure in TENURES:
                label = f"{run} {year} {tenure}"
                _close(record["bls"]["standard_errors"][tenure], published_se[year][tenure], f"BLS standard error {label}")
                with_stage = _rubin(replicates["with_in_kind"][tenure])
                _check_combined(with_stage, record["with_in_kind"][tenure], f"level with benefits {label}")
                without = replicates["without_in_kind"][tenure]
                without_se = math.sqrt(_replicate_variance(without[0], without[1:]))
                _close(without[0], record["without_in_kind"][tenure]["estimate"], f"level without benefits {label}")
                _close(without_se, record["without_in_kind"][tenure]["standard_error"], f"standard error without benefits {label}")
                for stage, se in (("with_in_kind", with_stage["standard_error"]), ("without_in_kind", without_se)):
                    ratio = se / published_se[year][tenure]
                    _close(ratio, record["ratio_to_bls_standard_error"][stage][tenure], f"ratio to BLS {stage} {label}")
                    ratios[stage][tenure].append(ratio)
        start, end = entry["years"][first]["replicates"], entry["years"][last]["replicates"]
        growth = entry["growth"][f"{first}-{last}"]["stage_change_points"]
        stage_change = {}
        for tenure in TENURES:
            label = f"{run} {first}-{last} {tenure}"
            # Replicate r of each window shares one replicate weight, so the
            # growth replicates pair them index by index.
            without_growth = [
                _growth(a, b) for a, b in zip(start["without_in_kind"][tenure], end["without_in_kind"][tenure], strict=True)
            ]
            changes = [
                [_growth(a, b) - w for a, b, w in zip(early, late, without_growth, strict=True)]
                for early, late in zip(start["with_in_kind"][tenure], end["with_in_kind"][tenure], strict=True)
            ]
            combined = _rubin(changes)
            _check_combined(combined, growth[tenure], f"stage change {label}")
            # The prose states the change in growth of the mean thresholds,
            # as the component receipt records it.
            change = components["runs"][run]["growth_2022_2025"]["by_tenure"][tenure]["stage_change_points"]
            _close(change, growth[tenure]["from_mean_thresholds"], f"stage change of mean thresholds {label}")
            stage_change[tenure] = {
                "change": change,
                "standard_error": combined["standard_error"],
                "standard_errors_from_zero": abs(change) / combined["standard_error"],
                "implicate_variance_share": combined["fraction_missing_information"],
            }
        figures["runs"][run] = {
            "level_ratio_range": {
                stage: {tenure: (min(values), max(values)) for tenure, values in by_tenure.items()}
                for stage, by_tenure in ratios.items()
            },
            "stage_change": stage_change,
            **_amount_and_lift_errors(entry, run),
        }
    patterns = uncertainty["checks"]["half_sample_patterns"]["quarters_with_changes"]
    figures["half_sample_changes"] = {
        quarter: record["share_keeping_pattern"] for quarter, record in patterns.items()
    }
    return figures


def _amount_and_lift_errors(entry: dict, run: str) -> dict:
    """Standard errors of the band amounts in each year and of their
    2022-2025 rises, and of the benefits' lift to each year's threshold,
    from the stored replicates. Replicate r of every window shares one
    replicate weight, so rises and lifts pair replicates index by index."""
    first, last = GROWTH_WINDOW
    amounts = {}
    for year in YEARS:
        record = entry["years"][year]
        amounts[year] = {}
        for name in AMOUNTS:
            combined = _rubin(record["replicates"]["amounts"][name])
            _check_combined(combined, record["amounts"][name], f"{name} {run} {year}")
            amounts[year][name] = combined
    rises = {}
    for name in AMOUNTS:
        series = [
            [b - a for a, b in zip(early, late, strict=True)]
            for early, late in zip(
                entry["years"][first]["replicates"]["amounts"][name],
                entry["years"][last]["replicates"]["amounts"][name],
                strict=True,
            )
        ]
        combined = _rubin(series)
        _check_combined(combined, entry["amount_rise_2022_2025"][name], f"{name} rise {run}")
        rises[name] = combined
    lifts = {tenure: {} for tenure in TENURES}
    for year in YEARS:
        replicates = entry["years"][year]["replicates"]
        for tenure in TENURES:
            series = [
                [_growth(w, v) for w, v in zip(replicates["without_in_kind"][tenure], draw, strict=True)]
                for draw in replicates["with_in_kind"][tenure]
            ]
            combined = _rubin(series)
            _check_combined(combined, entry["years"][year]["in_kind_lift_percent"][tenure], f"lift {run} {year} {tenure}")
            lifts[tenure][year] = combined
    return {"amounts": amounts, "amount_rises": rises, "lifts": lifts}


def check_receipt_pins(data_dir: Path) -> None:
    """Each receipt's bytes and calculator commit match ``RECEIPT_PINS``.
    The guard runs this after every consistency check, so an edit those
    checks catch fails with their label first."""
    provenance = json.loads((data_dir / PROVENANCE).read_text())
    _require(set(RECEIPT_PINS) == set(INKIND_FILES) - {PROVENANCE}, "pins cover exactly the three receipts")
    for name, (digest, commit) in RECEIPT_PINS.items():
        _require(_sha256(data_dir / name) == digest, f"{name} matches the SHA-256 pinned in inkind_inputs.py")
        _require(
            provenance["artifacts"][f"data/inkind/{name}"]["calculator_commit"] == commit,
            f"{name} comes from the calculator commit pinned in inkind_inputs.py",
        )

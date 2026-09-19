"""Successor MODEL-CONTRACT replay of saved September 15 housing-cap vectors.

This reads trusted, locally generated checkpoint pickles. It never runs a country
model, modifies an old oracle/receipt, or computes weighted population outcomes.
Array extraction is solely for unweighted elementwise engine-contract validation.
The published calculator supplies unrounded housing portions, since the saved
float32 housing portions cannot establish the cap's float64 arithmetic.

The A4 tenant-payment proxy is a model assumption, not an established Census rule.
See housing-cap-adjudication.md for the scientific distinction and primary sources.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import sys
from dataclasses import dataclass
from functools import cache
from importlib import metadata
from pathlib import Path
from zipfile import ZipFile

import numpy as np

ENDPOINTS = (
    (2024, "ce_trend"),
    (2025, "ce_trend"),
    (2026, "ce_trend"),
    (2026, "zero_real"),
)
REQUIRED = {
    "housing_assistance": "spm_unit",
    "hud_ttp": "spm_unit",
    "spm_unit_capped_housing_subsidy": "spm_unit",
    "spm_unit_spm_threshold_housing_portion": "spm_unit",
    "spm_measurement_adults": "spm_unit",
    "spm_measurement_children": "spm_unit",
    "spm_unit_tenure_type": "spm_unit",
    "county_fips": "household",
}


def require(condition: bool, message: str) -> None:
    """Fail closed when an input cannot support this replay."""
    if not condition:
        raise ValueError(message)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


@cache
def authenticate_calculator(wheel_path: str, expected_hash: str, version: str) -> dict:
    """Bind the lightweight calculator used for unrounded values to the saved wheel."""
    import spm_calculator

    wheel = Path(wheel_path)
    require(sha256(wheel) == expected_hash, "Calculator wheel hash mismatch")
    distribution = metadata.distribution("spm-calculator")
    require(distribution.version == version, "Wrong installed calculator version")
    require(
        Path(spm_calculator.__file__).resolve()
        == Path(distribution.locate_file("spm_calculator/__init__.py")).resolve(),
        "Calculator import does not come from installed distribution",
    )
    members = {}
    with ZipFile(wheel) as archive:
        for name in archive.namelist():
            if name.startswith("spm_calculator/") and not name.endswith("/"):
                expected = hashlib.sha256(archive.read(name)).hexdigest()
                require(
                    sha256(Path(distribution.locate_file(name))) == expected,
                    f"Installed calculator differs from wheel: {name}",
                )
                members[name] = expected
    require(bool(members), "Calculator wheel contains no package files")
    return {
        "wheel_sha256": expected_hash,
        "version": version,
        "verified_package_members": members,
    }


@dataclass(frozen=True)
class Membership:
    """Integer row mappings, with one native SPM record per unit."""

    person_spm: np.ndarray
    person_household: np.ndarray
    spm_household: np.ndarray
    spm_size: np.ndarray
    household_size: np.ndarray


def build_membership(
    *, person_ids, spm_ids, household_ids, person_spm_ids, person_household_ids
) -> Membership:
    """Validate ID mappings and reject duplicate, unknown, or cross-household SPMs."""
    for name, ids in (
        ("person", person_ids),
        ("spm", spm_ids),
        ("household", household_ids),
    ):
        require(len(ids) > 0 and len(set(ids)) == len(ids), f"Invalid {name} IDs")
    require(
        len(person_ids) == len(person_spm_ids) == len(person_household_ids),
        "Membership lengths differ",
    )

    def positions(ids, members):
        lookup = {identity: position for position, identity in enumerate(ids)}
        require(set(members) <= set(ids), "Unknown membership ID")
        return np.array([lookup[item] for item in members], dtype=np.int64)

    person_spm = positions(spm_ids, person_spm_ids)
    person_household = positions(household_ids, person_household_ids)
    spm_size = np.bincount(person_spm, minlength=len(spm_ids))
    household_size = np.bincount(person_household, minlength=len(household_ids))
    require(
        bool((spm_size > 0).all() and (household_size > 0).all()),
        "An entity has no members",
    )
    lower = np.full(len(spm_ids), len(household_ids), dtype=np.int64)
    upper = np.full(len(spm_ids), -1, dtype=np.int64)
    np.minimum.at(lower, person_spm, person_household)
    np.maximum.at(upper, person_spm, person_household)
    require(np.array_equal(lower, upper), "An SPM unit spans households")
    return Membership(person_spm, person_household, lower, spm_size, household_size)


def replay_housing_cap(
    raw_subsidy: np.ndarray,
    raw_tenant_payment: np.ndarray,
    housing_portion: np.ndarray,
    membership: Membership,
) -> dict[str, np.ndarray]:
    """Replay country 2.2.1's allocation and float32 storage boundaries.

    The two per-person divisions/sums preserve Core 3.32.5's floating-point
    operation order. Each native SPM amount is divided by its membership count
    before it is projected, so a broadcast amount is never counted repeatedly.
    """
    count = len(membership.spm_size)
    for name, values in (("subsidy", raw_subsidy), ("tenant", raw_tenant_payment)):
        require(values.shape == (count,), f"Wrong {name} shape")
        require(values.dtype == np.float32, f"Expected float32 {name} input")
        require(
            bool(np.isfinite(values).all() and (values >= 0).all()),
            f"Invalid {name} amount",
        )
    require(housing_portion.shape == (count,), "Wrong housing portion shape")

    def allocate(values):
        per_person = values / membership.spm_size
        household_total = np.bincount(
            membership.person_household,
            weights=per_person[membership.person_spm],
            minlength=len(membership.household_size),
        )
        per_resident = household_total / membership.household_size
        return np.bincount(
            membership.person_spm,
            weights=per_resident[membership.person_household],
            minlength=count,
        ).astype(np.float32)

    subsidy = allocate(raw_subsidy)
    # A4 includes actual recipients' contributions, not co-residents' hypothetical TTP.
    tenant = allocate(
        np.where(raw_subsidy > 0, raw_tenant_payment, 0).astype(np.float64)
    )
    assisted = subsidy > 0
    require(
        bool(np.isfinite(housing_portion[assisted]).all()),
        "Missing assisted housing portion",
    )
    cap = np.maximum(housing_portion.astype(np.float64) - tenant.astype(np.float64), 0)
    capped = np.where(assisted, np.minimum(subsidy.astype(np.float64), cap), 0)
    return {
        "allocated_subsidy": subsidy,
        "allocated_tenant_payment": tenant,
        "capped_subsidy": capped.astype(np.float32),
    }


@cache
def forecast_for(content_hash: str):
    from spm_calculator import load_forecast

    return load_forecast(expected_sha256=content_hash)


@cache
def housing_amount(content_hash, year, scenario, adults, children, tenure, county):
    from spm_calculator import SPMUnit

    forecast = forecast_for(content_hash)
    area = forecast.resolve_county(year, county, scenario=scenario)["area_id"]
    unit = SPMUnit(
        unit_id="successor-model-contract-replay",
        num_adults=adults,
        num_children=children,
        tenure=tenure,
        year=year,
        geography_kind="metro",
        geography_id=area,
    )
    return forecast.calculate_unit(unit, scenario=scenario)["housing_portion"]


def load_bound_pickle(path: Path, expected: str):
    require(sha256(path) == expected, f"Checkpoint hash mismatch: {path.name}")
    with path.open("rb") as stream:
        return pickle.load(stream)


def packet_array(packet, name: str, entity: str) -> np.ndarray:
    require(packet["format"] == "spm-final-native-v2", "Unknown packet format")
    require(packet["entities"][name] == entity, f"Wrong entity: {name}")
    saved = packet["vectors"][name]
    series = saved["series"]
    require(str(series.dtype) == saved["dtype"], f"Wrong dtype: {name}")
    require(len(series) == len(packet["ids"][entity]), f"Wrong row count: {name}")
    require(list(series.index) == list(range(len(series))), f"Wrong index: {name}")
    # No weighting operation is performed: these are elementwise identity checks.
    return series.to_numpy()


def comparison(actual: np.ndarray, expected: np.ndarray) -> dict:
    require(actual.dtype == expected.dtype, "Comparison dtype mismatch")
    return {
        "bit_identical": actual.tobytes() == expected.tobytes(),
        "different_records": int(np.count_nonzero(actual != expected)),
        "max_absolute_error": float(
            np.max(np.abs(actual.astype(np.float64) - expected.astype(np.float64)))
        ),
    }


def replay_cell(root: Path, loader: str, year: int, scenario: str, seed: int) -> dict:
    """Authenticate saved records, replay independently, and compare both grains."""
    cell = f"canonical-{loader}-{year}-{scenario}-seed{seed}"
    directory = root / "endpoints" / loader / cell
    checkpoint_path = directory / "all-vectors-checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text())
    require(
        (
            checkpoint["loader"],
            checkpoint["year"],
            checkpoint["scenario"],
            checkpoint["seed"],
        )
        == (loader, year, scenario, seed),
        "Wrong checkpoint",
    )
    config_path = root / "configs" / f"canonical-{loader}-{scenario}.json"
    require(sha256(config_path) == checkpoint["config_sha256"], "Config hash mismatch")
    config = json.loads(config_path.read_text())
    require(
        metadata.version("spm-calculator")
        == config["wheels"]["spm-calculator"]["version"],
        "Calculator version differs from checkpoint",
    )
    wheel = config["wheels"]["spm-calculator"]
    calculator_binding = authenticate_calculator(
        wheel["path"], wheel["sha256"], wheel["version"]
    )
    packets = {
        grain: load_bound_pickle(
            directory / f"{grain}-vectors.pkl", checkpoint[f"{grain}_vectors"]["sha256"]
        )
        for grain in ("native", "person")
    }
    native, person = packets["native"], packets["person"]
    identities = load_bound_pickle(
        directory / "input-identities-and-role.pkl", checkpoint["input_identity_sha256"]
    )
    for key in ("ids", "memberships", "identity"):
        require(native[key] == person[key] == identities[key], f"Changed {key}")
    member = build_membership(
        person_ids=native["ids"]["person"],
        spm_ids=native["ids"]["spm_unit"],
        household_ids=native["ids"]["household"],
        person_spm_ids=native["memberships"]["spm_unit"],
        person_household_ids=native["memberships"]["household"],
    )
    values = {}
    for name, entity in REQUIRED.items():
        values[name] = packet_array(native, name, entity)
        broadcast = packet_array(person, name, "person")
        row = member.person_spm if entity == "spm_unit" else member.person_household
        require(
            np.array_equal(values[name][row], broadcast),
            f"Person projection differs from native {name}",
        )
    county = values["county_fips"][member.spm_household]
    housing = np.array(
        [
            housing_amount(
                config["spm"]["forecast_content_sha256"],
                year,
                scenario,
                int(adults),
                int(children),
                str(tenure).lower(),
                str(county_id).zfill(5),
            )
            for adults, children, tenure, county_id in zip(
                values["spm_measurement_adults"],
                values["spm_measurement_children"],
                values["spm_unit_tenure_type"],
                county,
                strict=True,
            )
        ],
        dtype=np.float64,
    )
    housing_check = comparison(
        values["spm_unit_spm_threshold_housing_portion"], housing.astype(np.float32)
    )
    require(housing_check["bit_identical"], "Canonical housing portion differs")
    result = replay_housing_cap(
        values["housing_assistance"], values["hud_ttp"], housing, member
    )
    actual = values["spm_unit_capped_housing_subsidy"]
    native_check = comparison(actual, result["capped_subsidy"])
    person_check = comparison(
        packet_array(person, "spm_unit_capped_housing_subsidy", "person"),
        result["capped_subsidy"][member.person_spm],
    )
    old = np.minimum(
        values["housing_assistance"].astype(np.float64),
        np.maximum(housing - values["hud_ttp"].astype(np.float64), 0),
    )
    return {
        "cell": cell,
        "status": "PASS"
        if native_check["bit_identical"] and person_check["bit_identical"]
        else "MISMATCH",
        "native_records": len(actual),
        "person_records": len(member.person_spm),
        "zero_raw_award_units_receiving_positive_allocation": int(
            np.count_nonzero(
                (values["housing_assistance"] == 0) & (result["allocated_subsidy"] > 0)
            )
        ),
        "canonical_housing_portion": housing_check,
        "model_contract_native": native_check,
        "model_contract_person": person_check,
        "superseded_unallocated_oracle_native": comparison(
            actual, old.astype(np.float32)
        ),
        "original_calculator_replay": json.loads(
            (directory / "calculator-replay.json").read_text()
        ),
        "inputs": {
            name: {"path": str(directory / name), "sha256": sha256(directory / name)}
            for name in (
                "all-vectors-checkpoint.json",
                "native-vectors.pkl",
                "person-vectors.pkl",
                "input-identities-and-role.pkl",
                "calculator-replay.json",
            )
        },
        "config_sha256": checkpoint["config_sha256"],
        "dataset_sha256": checkpoint["dataset_sha256"],
        "forecast_content_sha256": config["spm"]["forecast_content_sha256"],
        "calculator_wheel_sha256": calculator_binding["wheel_sha256"],
        "verified_calculator_package_members": len(
            calculator_binding["verified_package_members"]
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "Refusing to overwrite an existing receipt")
    cells = []
    for loader in ("direct_country", "base_wrapper"):
        for year, scenario in ENDPOINTS:
            for seed in (0, 42):
                cell = f"canonical-{loader}-{year}-{scenario}-seed{seed}"
                try:
                    result = replay_cell(
                        args.artifacts_root, loader, year, scenario, seed
                    )
                except (FileNotFoundError, KeyError, ValueError, ImportError) as exc:
                    result = {
                        "cell": cell,
                        "status": "UNVERIFIABLE",
                        "reason": str(exc),
                    }
                cells.append(result)
                print(f"{cell}: {result['status']}", flush=True)
    passed = sum(item["status"] == "PASS" for item in cells)
    report = {
        "schema": "spm-housing-model-contract-successor-v1",
        "scope": "MODEL-CONTRACT ONLY; not Census scientific qualification or population acceptance",
        "model_assumption": "A4: household-summed awards and recipient-only tenant payments, each prorated to every household SPM by headcount",
        "dtype_contract": "float32 allocated amounts; float64 cap using unrounded canonical housing portion; float32 final amount",
        "original_artifacts_modified": False,
        "heavy_model_runs": 0,
        "status": "PASS" if passed == 16 else "INCOMPLETE_OR_MISMATCH",
        "cells_passed": passed,
        "cells_expected": 16,
        "script_sha256": sha256(Path(__file__)),
        "runtime_versions": {
            name: metadata.version(name)
            for name in (
                "numpy",
                "pandas",
                "spm-calculator",
                "policyengine-us",
                "policyengine-core",
            )
        },
        "cells": cells,
    }
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    return 0 if passed == 16 else 1


if __name__ == "__main__":
    sys.exit(main())

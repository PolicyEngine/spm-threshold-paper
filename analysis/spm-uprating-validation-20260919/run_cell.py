"""Run one dated SPM uprating diagnostic without changing the registered forecast.

Run each year/variant/runtime in a fresh process. All population statistics use
person-mapped MicroSeries; source H5 arrays and weights are never read directly.
An explicit local dataset permits controlled experimental country snapshots;
the resulting calculation is not a newly certified PolicyEngine bundle.
"""

import argparse
import hashlib
import json
import math
import os
import platform
import random
import resource
import sys
import time
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

DATASET_SHA256 = "6496cc4393d4d3c6574f76eca231de5898c803b9067645591fd5c4d3e65aee84"
FORECAST_SHA256 = "3d86d5c4c0423480e6b69b75d222ffa4a7a2639e4094df5ba2504af01be17173"
CPI_FACTOR = 32649 / 31812
BASE_2024 = {
    "OWNER_WITH_MORTGAGE": 39230.994457,
    "OWNER_WITHOUT_MORTGAGE": 32878.594848,
    "RENTER": 39219.893902,
}
BASE_2025 = {
    "OWNER_WITH_MORTGAGE": 41322.707394,
    "OWNER_WITHOUT_MORTGAGE": 34325.99772,
    "RENTER": 41700.555713,
}
ANCHOR_FACTORS = {
    tenure: BASE_2024[tenure] * CPI_FACTOR / BASE_2025[tenure] for tenure in BASE_2024
}


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verified_dataset(path, expected_sha256):
    path = Path(path).expanduser().resolve(strict=True)
    actual = sha256_file(path)
    if actual != expected_sha256:
        raise ValueError(
            f"Dataset hash mismatch: expected {expected_sha256}, got {actual}"
        )
    return path, actual


def age_groups(age):
    return {
        "all": age >= 0,
        "under_4": age < 4,
        "under_6": age < 6,
        "under_18": age < 18,
        "age_6_17": (age >= 6) & (age < 18),
        "age_18_64": (age >= 18) & (age < 65),
        "age_65_74": (age >= 65) & (age < 75),
        "age_75_plus": age >= 75,
        "age_65_plus": age >= 65,
    }


def distribution(series):
    """Distribution of a person's associated unit amount, person-weighted."""
    return {
        "mean": float(series.mean()),
        "p25": float(series.quantile(0.25)),
        "median": float(series.median()),
        "p75": float(series.quantile(0.75)),
    }


def summarize(age, poor, resources, threshold, components=None):
    """Aggregate aligned person MicroSeries without extracting weights/arrays."""
    series = (age, poor, resources, threshold, *(components or {}).values())
    if any(not item.index.equals(age.index) for item in series):
        raise ValueError("Person indexes are not aligned")
    if any(item.isna().any() or (abs(item) == math.inf).any() for item in series):
        raise ValueError("Non-finite person values")
    if (age < 0).any() or (threshold <= 0).any():
        raise ValueError("Age must be nonnegative and thresholds positive")
    ratio = resources / threshold
    # Equality is not poverty: this also verifies the true threshold reform is
    # visible to the model's canonical poverty indicator.
    if (poor != (resources < threshold)).any():
        raise ValueError(
            "Canonical poverty indicator disagrees with resources < threshold"
        )
    out = {}
    for name, mask in age_groups(age).items():
        population = float(mask.sum())
        if population == 0:
            out[name] = {"people": 0.0, "spm_pct": None, "poor_people": 0.0}
            continue
        group_ratio = ratio[mask]
        out[name] = {
            "people": population,
            "poor_people": float(poor[mask].sum()),
            "spm_pct": 100 * float(poor[mask].mean()),
            "spm_unit_resources_usd": distribution(resources[mask]),
            "spm_unit_threshold_usd": distribution(threshold[mask]),
            "resource_threshold_ratio": distribution(group_ratio),
            "resource_ratio_band_pct": {
                "below_0_75": 100 * float((group_ratio < 0.75).mean()),
                "0_75_to_below_1": 100
                * float(((group_ratio >= 0.75) & (group_ratio < 1)).mean()),
                "1_to_below_1_25": 100
                * float(((group_ratio >= 1) & (group_ratio < 1.25)).mean()),
                "1_25_to_below_1_5": 100
                * float(((group_ratio >= 1.25) & (group_ratio < 1.5)).mean()),
                "1_5_or_more": 100 * float((group_ratio >= 1.5).mean()),
            },
            "component_person_mapped_mean_usd": {
                key: float(value[mask].mean())
                for key, value in (components or {}).items()
            },
        }
    return out


def make_anchor_reform():
    """Scale national tenure bases, preserving 2025 geography/composition."""
    import numpy as np
    from policyengine_core.model_api import YEAR, Variable
    from policyengine_core.reforms import Reform
    from policyengine_us.system import system

    base_class = type(system.variables["spm_unit_spm_threshold"])
    base_formula, base_entity = base_class.formula, base_class.entity

    class spm_unit_spm_threshold(Variable):
        value_type = float
        entity = base_entity
        definition_period = YEAR
        label = "SPM threshold with 2024 national bases times CPI-U"
        unit = "currency-USD"

        def formula(unit, period, parameters):
            # Arrays here are internal model formula outputs, not MicroSeries
            # or population aggregation. Match the original anchored reform.
            base = np.asarray(base_formula(unit, period, parameters), dtype=np.float64)
            tenure = unit("spm_unit_tenure_type", period).decode_to_str()
            factors = np.select(
                [tenure == key for key in ANCHOR_FACTORS],
                list(ANCHOR_FACTORS.values()),
                default=np.nan,
            )
            if np.isnan(factors).any():
                raise ValueError("Unknown SPM housing tenure")
            return base * factors

    class Anchor2024CPI(Reform):
        def apply(self):
            self.update_variable(spm_unit_spm_threshold)

    return Anchor2024CPI


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--year", type=int, choices=(2024, 2025), required=True)
    result.add_argument(
        "--variant", choices=("baseline", "anchored_2024_cpi"), default="baseline"
    )
    result.add_argument("--dataset", type=Path, required=True)
    result.add_argument("--expected-dataset-sha256", default=DATASET_SHA256)
    result.add_argument("--runtime-label", required=True)
    result.add_argument(
        "--country-source-sha",
        required=True,
        help="Full source revision supplied by the runtime builder; recorded alongside installed metadata",
    )
    result.add_argument(
        "--development-country-model",
        action="store_true",
        help="Explicit country-model regression mode; bypasses the wrapper interface, never certification",
    )
    result.add_argument(
        "--expected-model-version",
        help="Required installed country version for explicit development mode",
    )
    result.add_argument("--seed", type=int, default=0)
    result.add_argument(
        "--component",
        action="append",
        default=[],
        help="Optional model variable; report person-mapped mean by age",
    )
    result.add_argument("--output", type=Path, required=True)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    if args.variant == "anchored_2024_cpi" and args.year != 2025:
        raise ValueError("The anchored variant is defined only for 2025")
    if len(args.country_source_sha) != 40 or any(
        c not in "0123456789abcdef" for c in args.country_source_sha
    ):
        raise ValueError("--country-source-sha must be a full lowercase Git SHA")
    if args.development_country_model and not args.expected_model_version:
        raise ValueError("Development mode requires --expected-model-version")
    if args.output.exists():
        raise FileExistsError(
            f"Refusing to overwrite an existing result: {args.output}"
        )
    dataset_path, dataset_hash = verified_dataset(
        args.dataset, args.expected_dataset_sha256
    )
    started = datetime.now(timezone.utc).isoformat()
    started_clock = time.monotonic()
    import numpy as np
    import policyengine_us

    installed_model_version = metadata.version("policyengine-us")
    if (
        args.expected_model_version
        and installed_model_version != args.expected_model_version
    ):
        raise ValueError(
            f"Expected model {args.expected_model_version}, installed {installed_model_version}"
        )
    random.seed(args.seed)
    np.random.seed(args.seed)
    reform = make_anchor_reform() if args.variant == "anchored_2024_cpi" else None
    options = {
        "dataset": str(dataset_path),
        "spm": {"scenario": "ce_trend", "forecast_content_sha256": FORECAST_SHA256},
        "reform": reform,
    }
    if args.development_country_model:
        sim = policyengine_us.Microsimulation(**options)
        interface = (
            "policyengine_us.Microsimulation (explicit model-development comparison)"
        )
    else:
        import policyengine as pe

        sim = pe.us.managed_microsimulation(allow_unmanaged=True, **options)
        interface = (
            "policyengine.us.managed_microsimulation (explicit verified local H5)"
        )
    load_seconds = time.monotonic() - started_clock
    # Core seeds construction/per-variable calculations itself; there is no
    # constructor seed argument. Record this caller seed separately, accurately.
    random.seed(args.seed)
    np.random.seed(args.seed)
    calc = lambda name: sim.calc(name, period=args.year, map_to="person")
    age = calc("age")
    poor = calc("spm_unit_is_in_spm_poverty")
    resources = calc("spm_unit_net_income")
    threshold = calc("spm_unit_spm_threshold")
    components = {name: calc(name) for name in args.component}
    groups = summarize(age, poor, resources, threshold, components)
    packages = (
        "policyengine",
        "policyengine-us",
        "policyengine-core",
        "spm-calculator",
        "microdf-python",
        "numpy",
        "pandas",
    )
    country_file = Path(policyengine_us.__file__).resolve()
    result = {
        "format": "spm/uprating-validation-cell/v1",
        "started_at_utc": started,
        "year": args.year,
        "variant": args.variant,
        "groups": groups,
        "spm_pct": {name: group["spm_pct"] for name, group in groups.items()},
        "anchor_factors": ANCHOR_FACTORS if reform else None,
        "provenance": {
            "status": "controlled experimental runtime; not a new certified bundle",
            "interface": interface,
            "development_country_model": args.development_country_model,
            "bundle_certified": False,
            "runtime_label": args.runtime_label,
            "country_source_sha_declared": args.country_source_sha,
            "expected_model_version": args.expected_model_version,
            "country_import_path": str(country_file),
            "country_init_sha256": sha256_file(country_file),
            "package_versions": {name: metadata.version(name) for name in packages},
            "dataset_path": str(dataset_path),
            "dataset_sha256": dataset_hash,
            "expected_dataset_sha256": args.expected_dataset_sha256,
            "runner_path": str(Path(__file__).resolve()),
            "runner_sha256": sha256_file(__file__),
            "python": sys.version,
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "caller_seed": args.seed,
            "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
            "seed_note": "Caller Python/NumPy seed before construction and calculation; Core also applies its own deterministic construction/per-variable seeds.",
            "bundle_reference_metadata": getattr(sim, "policyengine_bundle", None),
            "spm_config": sim.spm_config,
            "spm_provenance": sim.spm_provenance(),
        },
        "runtime": {
            "load_seconds": load_seconds,
            "total_seconds": time.monotonic() - started_clock,
            "peak_rss_gb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            / (1e9 if sys.platform == "darwin" else 1e6),
        },
        "interpretation": {
            "threshold_effect": "2025 baseline rate minus 2025 rate with national tenure threshold bases held at 2024 values plus CPI-U; conditional on 2025 resources and geography/composition.",
            "residual_label": "Change with national threshold bases held constant in real terms",
            "residual_note": "Anchored 2025 rate minus 2024 rate; includes resources, geography, composition and weighting, not an isolated causal resource effect.",
            "distribution_note": "Resources and thresholds are associated SPM-unit amounts mapped to people; their quantiles are person-weighted. Ratios of annual medians are not medians of individual growth.",
        },
    }
    serialized = json.dumps(result, indent=2, allow_nan=False) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as handle:
        handle.write(serialized)
    print(
        json.dumps(
            {"output": str(args.output.resolve()), "spm_pct": result["spm_pct"]},
            allow_nan=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()

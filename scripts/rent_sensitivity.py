#!/usr/bin/env python3
"""Rental-assistance sensitivities for one reference year.

Two choices move the replication's rental assistance per assisted renter:
the rent paid that enters the rent model, and the rule that turns the fitted
rent distribution into each assisted unit's market rent. This script reruns
spm-calculator's model (``spm_calculator.ce_inkind._rental_assistance``) for
reference year 2022 and varies each choice:

- ``base``: the replication's model. A weighted Tobit of log monthly rent on
  CE renters treats assisted renters' rents as censored from above at the
  rent they pay; each assisted unit gets a market rent drawn from the fitted
  distribution above its rent paid, in five implicates.
- ``next_interview_rent``: the base model after one change to rent paid.
  Where a renter's monthly rent paid is 25 to 75 percent of the same unit's
  at its next interview, the pattern of rent paid for part of the three
  months, it takes the next interview's.
- ``predicted_median`` and ``predicted_mean``: the base fit at its point
  estimates, with each assisted unit's market rent set to the fitted median
  or mean and negative benefits set to zero.
- ``levels_predicted``: the same Tobit fitted to rent in dollars, with each
  assisted unit's market rent set to the linear prediction and negative
  benefits set to zero.

Monthly rent paid is one third of the unit's three-month rent total in the
CE's RNT file (``QRT3MCMX``); the public files give no single month's rent.

The script needs an export of spm-calculator at the commit that
``scripts/inkind_inputs.py`` pins for the replication receipt, and the CE
Interview bundles that receipt fingerprints. It checks both against the
receipt, and its base case must reproduce the receipt's 2022 amount per
assisted renter. The helpers above ``main`` use the standard library only, so
the tests run without the calculator.

Usage, with the library versions the replication receipt records:

    uv run --no-project --python 3.14.7 --with numpy==2.4.1 \\
        --with pandas==3.0.0 --with scipy==1.18.1 --with requests \\
        --with census --with us --with openpyxl \\
        python scripts/rent_sensitivity.py --calculator <export> \\
        --cache ~/.cache/spm-calculator/ce-pumd
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from inkind_inputs import RECEIPT_PINS, REPLICATION  # noqa: E402

REFERENCE_YEAR = 2022
RECEIPT = REPO / "data" / "rent_sensitivity" / "rent_model_sensitivity_2022.json"
REPLICATION_RECEIPT = REPO / "data" / "inkind" / REPLICATION
# A renter's rent paid at this share of its next interview's, inclusive,
# marks rent paid for part of the three months.
PART_PERIOD_BOUNDS = (0.25, 0.75)
# The rent-in-dollars Tobit fits rent in thousands, so its coefficients sit
# on the same scale as the log model's.
LEVELS_SCALE = 1000.0
# The relative tolerance within which the base case must match the receipt.
BASE_TOLERANCE = 1e-9
VARIANTS = {
    "base": "The replication's model: market rent drawn above rent paid, five implicates",
    "next_interview_rent": (
        "The base model, with a renter's rent paid replaced by its next interview's where it is 25 to 75 "
        "percent of that one"
    ),
    "predicted_median": "The base fit's median market rent, negative benefits set to zero",
    "predicted_mean": "The base fit's mean market rent, negative benefits set to zero",
    "levels_predicted": (
        "The same Tobit fitted to rent in dollars, its linear prediction as market rent, negative benefits "
        "set to zero"
    ),
}
PREDICTED = ("predicted_median", "predicted_mean", "levels_predicted")
LIMITATIONS = [
    "One reference year, 2022, from CE interviews collected from 2022Q2 through 2023Q1",
    "Amounts are per assisted renter across the CE, not within the 47th-53rd percentile band",
    "Only renters with a next interview, in the following quarter, can take its rent paid",
    "The point-prediction variants use the fitted parameters, not parameter draws",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def part_period(rent: float, next_rent: float) -> bool:
    """Whether ``rent`` is 25 to 75 percent of a positive, finite ``next_rent``."""
    if not (math.isfinite(next_rent) and next_rent > 0 and math.isfinite(rent)):
        return False
    low, high = PART_PERIOD_BOUNDS
    return low <= rent / next_rent <= high


def floored_annual_benefit(market: float, paid: float) -> float:
    """Twelve times market rent less rent paid, and zero where that is negative."""
    return 12.0 * max(market - max(paid, 0.0), 0.0)


def weighted_mean(values, weights) -> float:
    values, weights = list(values), list(weights)
    if len(values) != len(weights) or not values:
        raise ValueError("values and weights must be equal, non-empty sequences")
    total = math.fsum(weights)
    if not total > 0:
        raise ValueError("weights must sum to a positive number")
    return math.fsum(v * w for v, w in zip(values, weights)) / total


def percent_change(value: float, base: float) -> float:
    return 100.0 * (value / base - 1.0)


def summarize(dollars: dict[str, float], zero_shares: dict[str, float]) -> dict:
    """Each variant's dollars, percent change from ``base`` and share given no benefit."""
    if set(dollars) != set(VARIANTS):
        raise ValueError("dollars must cover exactly the variants")
    return {
        name: {
            "description": VARIANTS[name],
            "dollars_per_assisted_renter": dollars[name],
            "percent_vs_base": percent_change(dollars[name], dollars["base"]),
            "share_with_zero_benefit": zero_shares.get(name),
        }
        for name in VARIANTS
    }


def _require(condition: bool, label: str) -> None:
    if not condition:
        raise SystemExit(f"rent sensitivity: {label}")


def _check_inputs(calculator: Path, commit: str, cache: Path, replication: dict) -> tuple[dict, dict]:
    _require(commit == RECEIPT_PINS[REPLICATION][1], "calculator commit is the replication receipt's")
    _require(sha256(REPLICATION_RECEIPT) == RECEIPT_PINS[REPLICATION][0], "replication receipt matches its pin")
    code = {
        name: digest
        for name, digest in replication["code_sha256"].items()
        if name.startswith("spm_calculator/")
    }
    for name, digest in code.items():
        _require(sha256(calculator / name) == digest, f"{name} matches the replication receipt")
    bundles = {}
    for year in (REFERENCE_YEAR, REFERENCE_YEAR + 1):
        name = f"intrvw{year % 100:02d}.zip"
        bundles[name] = sha256(cache / name)
        _require(bundles[name] == replication["ce_bundles"][name]["sha256"], f"{name} matches the replication receipt")
    return code, bundles


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--calculator", type=Path, required=True, help="spm-calculator export at the pinned commit")
    parser.add_argument("--commit", default=RECEIPT_PINS[REPLICATION][1], help="the export's commit")
    parser.add_argument("--cache", type=Path, required=True, help="folder holding the CE Interview bundles")
    parser.add_argument("--output", type=Path, default=RECEIPT)
    args = parser.parse_args()

    replication = json.loads(REPLICATION_RECEIPT.read_text())
    code, bundles = _check_inputs(args.calculator, args.commit, args.cache, replication)
    recorded = replication["imputation_diagnostics"]["rental_assistance"][str(REFERENCE_YEAR)]

    sys.path.insert(0, str(args.calculator))
    import numpy as np
    import pandas as pd
    import scipy

    from spm_calculator import ce_inkind as ck
    from spm_calculator.ce_threshold import load_ce_quarter

    quarters = [(REFERENCE_YEAR, 2), (REFERENCE_YEAR, 3), (REFERENCE_YEAR, 4), (REFERENCE_YEAR + 1, 1)]
    next_quarter = (REFERENCE_YEAR + 1, 2)
    fmli = pd.concat(
        [load_ce_quarter(*q, cache_dir=args.cache, allow_download=False) for q in quarters],
        ignore_index=True,
    )
    units = ck.load_ce_unit_inputs(quarters, cache_dir=args.cache)
    ce = ck.ce_unit_covariates(fmli, units)
    ce = ck._sorted_by_key(ce.loc[ce["reference_year"] == REFERENCE_YEAR])
    config = ck.InKindConfig(implicates=replication["in_kind_methodology"]["implicates"])
    for field in ("seed", "ridge", "parameter_draws"):
        _require(getattr(config, field) == replication["in_kind_methodology"][field], f"config {field} matches")

    weight = ce["weight"].to_numpy(dtype=float)
    renters = (ce["cutenure"] == 4).to_numpy()
    assisted = renters & ce["housing_assistance"].to_numpy()
    rent = ce["rent_paid_monthly"].to_numpy(dtype=float)
    w = weight[assisted]

    def per_assisted(implicates: list) -> float:
        return float(np.mean([weighted_mean(v[assisted], w) for v in implicates]))

    dollars, zero_shares = {}, {}
    diagnostics: dict = {}
    dollars["base"] = per_assisted(ck._rental_assistance(ce, REFERENCE_YEAR, config, diagnostics))
    for field in ("renters", "assisted", "fit_rows"):
        _require(diagnostics[field] == recorded[field], f"base {field} matches the replication receipt")
    _require(math.isclose(diagnostics["sigma"], recorded["sigma"], rel_tol=BASE_TOLERANCE), "base sigma matches")
    _require(
        math.isclose(dollars["base"], recorded["ce_mean_amount_per_participant"], rel_tol=BASE_TOLERANCE),
        "base amount per assisted renter matches the replication receipt",
    )

    # Each CE unit's next interview carries the next NEWID, one quarter later.
    following = ck.load_ce_unit_inputs([next_quarter], cache_dir=args.cache).set_index("NEWID")
    rent_by_id = pd.concat([units.set_index("NEWID")["rent_paid_monthly"], following["rent_paid_monthly"]])
    rent_by_id = rent_by_id[~rent_by_id.index.duplicated()]
    next_rent = pd.Series(ce["key"].to_numpy() + 1).map(rent_by_id).to_numpy(dtype=float)
    linked = renters & np.isfinite(next_rent) & (next_rent > 0)
    part = np.array([bool(r) and part_period(a, b) for r, a, b in zip(renters, rent, next_rent)])
    adjusted = ce.copy()
    adjusted.loc[part, "rent_paid_monthly"] = next_rent[part]
    dollars["next_interview_rent"] = per_assisted(ck._rental_assistance(adjusted, REFERENCE_YEAR, config, {}))

    states = sorted(int(s) for s in ce["state"].dropna().unique())
    x = ck._rent_design(ce, states)
    fit = (renters & ~assisted & (rent >= ck.MIN_UNASSISTED_MONTHLY_RENT)) | (assisted & (rent > 0))
    order = np.argsort(ce["key"].to_numpy(), kind="stable")
    rows = order[fit[order]]
    paid = rent[assisted]

    theta, _ = ck.fit_tobit(
        x[rows], np.log(np.where(rent > 0, rent, 1.0))[rows], assisted[rows], weight[rows], config.ridge
    )
    sigma = 1.0 / theta[-1]
    _require(math.isclose(sigma, recorded["sigma"], rel_tol=BASE_TOLERANCE), "point fit is the base fit")
    mu = x[assisted] @ (theta[:-1] * sigma)
    levels, _ = ck.fit_tobit(x[rows], (rent / LEVELS_SCALE)[rows], assisted[rows], weight[rows], config.ridge)
    markets = {
        "predicted_median": np.exp(mu),
        "predicted_mean": np.exp(mu + sigma**2 / 2.0),
        "levels_predicted": x[assisted] @ (levels[:-1] / levels[-1]) * LEVELS_SCALE,
    }
    for name, market in markets.items():
        benefit = [floored_annual_benefit(m, p) for m, p in zip(market, paid)]
        dollars[name] = weighted_mean(benefit, w)
        zero_shares[name] = weighted_mean([float(b == 0.0) for b in benefit], w)

    variants = summarize(dollars, zero_shares)
    _require(all(variants[name]["percent_vs_base"] < 0 for name in PREDICTED), "predicted market rents give less")
    receipt = {
        "schema_version": 1,
        "generated_by": "scripts/rent_sensitivity.py",
        "generated_on": date.today().isoformat(),
        "script_sha256": sha256(Path(__file__).resolve()),
        "calculator_commit": args.commit,
        "code_sha256": code,
        "ce_bundles": bundles,
        "replication_receipt": {
            "path": f"data/inkind/{REPLICATION}",
            "sha256": sha256(REPLICATION_RECEIPT),
        },
        "runtime": {
            "python": ".".join(str(part) for part in sys.version_info[:3]),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scipy": scipy.__version__,
        },
        "reference_year": REFERENCE_YEAR,
        "collection_quarters": [f"{y}Q{q}" for y, q in quarters],
        "next_interview_quarter": f"{next_quarter[0]}Q{next_quarter[1]}",
        "part_period_bounds": list(PART_PERIOD_BOUNDS),
        "sample": {
            "renters": int(renters.sum()),
            "assisted": int(assisted.sum()),
            "fit_rows": int(fit.sum()),
            "renters_with_next_interview_rent": int(linked.sum()),
            "part_period_renters": int(part.sum()),
            "part_period_assisted": int((part & assisted).sum()),
        },
        "fit": {
            "sigma": float(sigma),
            "mean_rent_paid_assisted_monthly": weighted_mean(paid, w),
            "mean_fitted_median_market_rent_assisted_monthly": weighted_mean(np.exp(mu), w),
        },
        "variants": variants,
        "limitations": LIMITATIONS,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    for name, row in variants.items():
        print(f"{name:20s} ${row['dollars_per_assisted_renter']:,.0f} ({row['percent_vs_base']:+.1f}%)")


if __name__ == "__main__":
    main()

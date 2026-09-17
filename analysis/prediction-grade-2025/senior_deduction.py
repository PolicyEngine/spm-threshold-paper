"""The OBBBA senior deduction's contribution to the modeled 2025 change, and three ways of anchoring to Census 2024.

Uses the person arrays written by run_senior_deduction.py: 2024 baseline, 2025 baseline, and 2025 with
gov.irs.deductions.senior_deduction.amount set to zero.

usage: python senior_deduction.py <arrays-dir>
"""
import json
import sys
from pathlib import Path

import numpy as np

SRC = Path(sys.argv[1])
HERE = Path(__file__).parent

CENSUS_2024_CORRECTED = {"all": 13.0, "under_18": 13.4, "age_65_plus": 15.1}  # SEHSD WP 2026-17
REGISTERED = {"all": 13.2, "under_18": 14.3, "age_65_plus": 14.6}  # 2025-spm-poverty-rates-2026-09-11.json

def load(year, variant):
    z = np.load(SRC / f"arrays-{year}-{variant}.npz")
    return {k: z[k] for k in z.files}

def groups(age):
    return {"all": np.ones_like(age, bool), "under_18": age < 18, "age_65_plus": age >= 65}

def wrate(flag, w, m):
    return float((flag[m] * w[m]).sum() / w[m].sum() * 100)

def rates(d):
    pov = d["spm_unit_is_in_spm_poverty"].astype(float)
    return {g: wrate(pov, d["weight"], m) for g, m in groups(d["age"]).items()}

def solve_k(d, target_pct, mask):
    """Threshold scale k such that share(net_income < k*threshold) == target within the group."""
    ratio = d["spm_unit_net_income"][mask] / d["spm_unit_spm_threshold"][mask]
    w = d["weight"][mask]
    order = np.argsort(ratio)
    cum = np.cumsum(w[order]) / w.sum() * 100
    i = int(np.searchsorted(cum, target_pct))
    return float(ratio[order][min(i, len(order) - 1)])

def rate_at_k(d, k, mask):
    flag = (d["spm_unit_net_income"] < k * d["spm_unit_spm_threshold"]).astype(float)
    return wrate(flag, d["weight"], mask)

b24, b25, r25 = load(2024, "baseline"), load(2025, "baseline"), load(2025, "no_senior_deduction")
R24, R25, RR25 = rates(b24), rates(b25), rates(r25)
out = {"model_levels_pct": {"2024": R24, "2025": R25, "2025_no_senior_deduction": RR25}}
out["modeled_change_pp"] = {g: R25[g] - R24[g] for g in R24}
out["senior_deduction_contribution_pp"] = {g: R25[g] - RR25[g] for g in R24}  # negative = deduction lowered poverty
out["change_without_senior_deduction_pp"] = {g: RR25[g] - R24[g] for g in R24}
# who is lifted: in poverty without the deduction, not in poverty with it
lifted = (r25["spm_unit_is_in_spm_poverty"] == 1) & (b25["spm_unit_is_in_spm_poverty"] == 0)
pushed = (r25["spm_unit_is_in_spm_poverty"] == 0) & (b25["spm_unit_is_in_spm_poverty"] == 1)
w = b25["weight"]; g25 = groups(b25["age"])
out["people_lifted_by_senior_deduction_thousands"] = {g: float(w[lifted & m].sum() / 1e3) for g, m in g25.items()}
out["people_pushed_in_by_removing_it_check_thousands"] = {g: float(w[pushed & m].sum() / 1e3) for g, m in g25.items()}
sd = b25["additional_senior_deduction"]; it_b, it_r = b25["income_tax"], r25["income_tax"]
sen = g25["age_65_plus"]; poor_or_near = b25["spm_unit_net_income"] < 1.25 * b25["spm_unit_spm_threshold"]
out["seniors_2025"] = {
    "share_in_tax_unit_with_positive_senior_deduction_pct": wrate((sd > 0).astype(float), w, sen),
    "share_with_income_tax_cut_by_deduction_pct": wrate((it_r - it_b > 0.5).astype(float), w, sen),
    "share_with_income_tax_cut_among_below_125pct_threshold_pct": wrate((it_r - it_b > 0.5).astype(float), w, sen & poor_or_near),
    "mean_income_tax_cut_usd_among_seniors": float(((it_r - it_b) * w)[sen].sum() / w[sen].sum()),
    "mean_income_tax_cut_usd_among_seniors_below_125pct_threshold": float(((it_r - it_b) * w)[sen & poor_or_near].sum() / w[sen & poor_or_near].sum()),
}
anch = {}
for g in R24:
    c = CENSUS_2024_CORRECTED[g]
    k = solve_k(b24, c, groups(b24["age"])[g])
    anch[g] = {
        "additive": c + (R25[g] - R24[g]),
        "multiplicative": c * R25[g] / R24[g],
        "level_anchored_threshold_scale": {"k_solved_on_2024": k, "check_2024": rate_at_k(b24, k, groups(b24["age"])[g]), "forecast_2025": rate_at_k(b25, k, g25[g])},
        "registered_2026_09_11": REGISTERED[g],
    }
k_all = anch["all"]["level_anchored_threshold_scale"]["k_solved_on_2024"]
anch["single_k_from_all_people"] = {"k": k_all, "2024_check": {g: rate_at_k(b24, k_all, m) for g, m in groups(b24["age"]).items()}, "2025_forecast": {g: rate_at_k(b25, k_all, m) for g, m in g25.items()}}
out["anchored_2025_forecasts_pct"] = anch
out["meta"] = {v: json.load(open(SRC / f"meta-{y}-{v2}.json")) for y, v2, v in ((2024, "baseline", "2024_baseline"), (2025, "baseline", "2025_baseline"), (2025, "no_senior_deduction", "2025_no_senior_deduction"))}
(HERE / "results" / "senior_deduction.json").write_text(json.dumps(out, indent=1) + "\n")
print(json.dumps({k: out[k] for k in out if k != "meta"}, indent=1))

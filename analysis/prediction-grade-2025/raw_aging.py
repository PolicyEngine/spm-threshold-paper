"""What aging the raw 2025 CPS ASEC file (calendar 2024) forward one year would have predicted for 2025.

Steps: replicate the published 2024 SPM rates from the public-use person file; re-base the unit thresholds to
the corrected 2024 BLS values; move them to the published 2025 BLS values by housing tenure; grow every unit's
SPM resources by a common factor; compare with the 2025 rates Census published (P60-290 Table 5, unrounded).

Input: pppub25.csv from https://www2.census.gov/programs-surveys/cps/datasets/2025/march/asecpub25csv.zip
usage: python raw_aging.py <dir-containing-pppub25.csv>
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
cols = ["A_AGE", "MARSUPWT", "SPM_POOR", "SPM_RESOURCES", "SPM_POVTHRESHOLD", "SPM_TENMORTSTATUS"]
d = pd.read_csv(Path(sys.argv[1]) / "pppub25.csv", usecols=cols)
w = d.MARSUPWT.to_numpy(float) / 100  # two implied decimals
age, res = d.A_AGE.to_numpy(), d.SPM_RESOURCES.to_numpy(float)
thr, ten = d.SPM_POVTHRESHOLD.to_numpy(float), d.SPM_TENMORTSTATUS.to_numpy()

# Two-adult-two-child thresholds by tenure: 1 owner with mortgage, 2 owner without mortgage, 3 renter.
ORIG_2024 = {1: 39068.0, 2: 32586.0, 3: 39430.0}  # in the 2025 file, before the BLS correction
CORR_2024 = {1: 39230.994457, 2: 32878.594848, 3: 39219.893902}  # BLS corrected workbook
BLS_2025 = {1: 41322.707394, 2: 34325.99772, 3: 41700.555713}
CPI_U = 32649 / 31812  # official-measure threshold growth, P60-290 Table 10
ACTUAL_2025 = {"all": 13.11, "under_18": 13.40, "under_6": 14.15, "age_18_64": 12.28, "age_65_plus": 15.37}
REGISTERED = {"all": 13.2, "under_18": 14.3, "age_65_plus": 14.6}

groups = {
    "all": age >= 0, "under_18": age < 18, "under_6": age < 6,
    "age_18_64": (age >= 18) & (age < 65), "age_65_plus": age >= 65,
}


def rate(flag, m):
    return float((flag[m] * w[m]).sum() / w[m].sum() * 100)


def rates(flag):
    return {g: round(rate(flag.astype(float), m), 2) for g, m in groups.items()}


thr_corr = thr * np.vectorize(lambda t: CORR_2024[t] / ORIG_2024[t])(ten)
thr_2025 = thr_corr * np.vectorize(lambda t: BLS_2025[t] / CORR_2024[t])(ten)

out = {
    "replication_2024_published_flag": rates(d.SPM_POOR.to_numpy() == 1),
    "recomputed_2024_original_thresholds": rates(res < thr),
    "recomputed_2024_corrected_thresholds": rates(res < thr_corr),
    "actual_2025_census_table_5": ACTUAL_2025,
}
growth = [("cpi_u_2.63", CPI_U), ("3.5", 1.035), ("4.0", 1.04), ("4.5", 1.045), ("5.0", 1.05), ("6.0", 1.06)]
out["projected_2025_by_uniform_resource_growth_pct"] = {name: rates(res * g < thr_2025) for name, g in growth}
at_2024 = rates(res * CPI_U < thr_corr * CPI_U)
out["threshold_effect_pp"] = {
    g: round(out["projected_2025_by_uniform_resource_growth_pct"]["cpi_u_2.63"][g] - at_2024[g], 2) for g in groups
}

required = {}
for g, m in groups.items():
    lo, hi = 1.0, 1.15
    for _ in range(40):
        mid = (lo + hi) / 2
        if rate((res * mid < thr_2025).astype(float), m) > ACTUAL_2025[g]:
            lo = mid
        else:
            hi = mid
    required[g] = round((mid - 1) * 100, 2)
out["uniform_resource_growth_pct_that_matches_actual_2025"] = required

# The model's own median resource growth near the line (near_line_growth.py), applied to the raw file.
model_growth = json.loads((HERE / "results" / "near_line_growth.json").read_text())
g_all = 1 + model_growth["all"]["median_resource_growth_pct"] / 100
uniform = rates(res * g_all < thr_2025)
by_group = {
    g: round(rate((res * (1 + model_growth[g]["median_resource_growth_pct"] / 100) < thr_2025).astype(float), groups[g]), 2)
    for g in ("under_18", "age_18_64", "age_65_plus")
}
out["raw_file_with_model_growth"] = {
    "uniform_model_median_growth_pct": model_growth["all"]["median_resource_growth_pct"],
    "projected_2025_uniform": uniform,
    "error_uniform_pp": {g: round(uniform[g] - ACTUAL_2025[g], 2) for g in ACTUAL_2025},
    "projected_2025_group_specific": by_group,
    "error_group_specific_pp": {g: round(by_group[g] - ACTUAL_2025[g], 2) for g in by_group},
    "registered_prediction_error_pp": {g: round(REGISTERED[g] - ACTUAL_2025[g], 2) for g in REGISTERED},
}
(HERE / "results" / "raw_aging.json").write_text(json.dumps(out, indent=1) + "\n")
print(json.dumps(out, indent=1))

"""Resource growth from 2024 to 2025 for the same people near the poverty line, in the model.

Uses the person arrays written by run_decomp.py (arrays-2024-baseline.npz, arrays-2025-baseline.npz).
"Near the line" = 2024 SPM resources between 75 and 150 percent of the 2024 threshold, resources positive.

usage: python near_line_growth.py <arrays-dir>
"""
import json
import sys
from pathlib import Path

import numpy as np

src = Path(sys.argv[1])
a, b = np.load(src / "arrays-2024-baseline.npz"), np.load(src / "arrays-2025-baseline.npz")
ni24, ni25 = a["spm_unit_net_income"], b["spm_unit_net_income"]
th24, th25, w, age = a["spm_unit_spm_threshold"], b["spm_unit_spm_threshold"], a["weight"], a["age"]
ratio24 = ni24 / th24


def wq(x, wt, q):
    order = np.argsort(x)
    cum = np.cumsum(wt[order])
    return float(x[order][np.searchsorted(cum, q * cum[-1])])


out = {}
for label, m in (("all", age >= 0), ("under_18", age < 18), ("age_18_64", (age >= 18) & (age < 65)), ("age_65_plus", age >= 65)):
    near = m & (ratio24 > 0.75) & (ratio24 < 1.5) & (ni24 > 0)
    g = ni25[near] / ni24[near]
    out[label] = {
        "median_resource_growth_pct": round(100 * (wq(g, w[near], 0.5) - 1), 2),
        "p25_resource_growth_pct": round(100 * (wq(g, w[near], 0.25) - 1), 2),
        "p75_resource_growth_pct": round(100 * (wq(g, w[near], 0.75) - 1), 2),
        "median_threshold_growth_pct": round(100 * (wq(th25[near] / th24[near], w[near], 0.5) - 1), 2),
        "weighted_people_millions": round(float(w[near].sum()) / 1e6, 2),
    }
(Path(__file__).parent / "results" / "near_line_growth.json").write_text(json.dumps(out, indent=1) + "\n")
print(json.dumps(out, indent=1))

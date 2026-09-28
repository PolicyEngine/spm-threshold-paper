"""Split each variant's modeled 2024->2025 change into a threshold effect and a resource effect, on the variant run itself.

threshold effect = 2025 rate - 2025 rate with thresholds anchored to 2024 (corrected BLS 2024 national value by tenure
                   times CPI-U annual-average growth, 32,649/31,812, as in ../run_decomp.py)
resource effect  = anchored 2025 rate - 2024 rate
The split is order-dependent: a source that moves children into the band between the anchored and actual 2025
thresholds shows up in the threshold term. Report totals first.

usage: python split_variants.py   (in the directory holding sources-*.npz; tenure comes from any run that saved it)
"""
import json
from pathlib import Path

import numpy as np

T25 = {"OWNER_WITH_MORTGAGE": 41322.707394, "OWNER_WITHOUT_MORTGAGE": 34325.99772, "RENTER": 41700.555713}
T24 = {"OWNER_WITH_MORTGAGE": 39230.994457, "OWNER_WITHOUT_MORTGAGE": 32878.594848, "RENTER": 39219.893902}
CPI = 32649 / 31812
FACTORS = {k: T24[k] * CPI / T25[k] for k in T25}
CENSUS = {"all": (0.07, 0.80, -0.73), "under_18": (-0.06, 1.09, -1.15), "age_65_plus": (0.24, 0.71, -0.47)}
VARIANTS = ["baseline", "ss_cola", "ss_cola_pension_cpi", "wages_by_decile", "se_like_wages", "all_three",
            "wages_by_family_decile", "all_three_cpi_avg", "all_three_ss_survey", "all_three_ss_66plus", "all_four"]

a = np.load("sources-2024-baseline.npz")
tenure = None
for f in sorted(Path(".").glob("sources-*.npz")):
    z = np.load(f)
    if "tenure" in z.files:
        assert (z["person_id"] == a["person_id"]).all()
        tenure = z["tenure"]
        break
assert tenure is not None, "no run saved tenure"
factor = np.select([tenure == k for k in FACTORS], [FACTORS[k] for k in FACTORS], default=np.nan)
assert not np.isnan(factor).any(), "unknown tenure"
w, age = a["weight"], a["age"]
groups = {"all": age >= 0, "under_18": age < 18, "age_18_64": (age >= 18) & (age < 65), "age_65_plus": age >= 65}


def rate(poor, m):
    return float((poor[m] * w[m]).sum() / w[m].sum() * 100)


out = {"census": {g: dict(zip(("change", "threshold", "resources"), v)) for g, v in CENSUS.items()}, "variants": {}}
for v in VARIANTS:
    f = Path(f"sources-2025-{v}.npz")
    if not f.exists():
        continue
    b = np.load(f)
    assert (b["person_id"] == a["person_id"]).all()
    poor24 = a["net_income"] < a["threshold"]
    poor25 = b["net_income"] < b["threshold"]
    poor25_anchored = b["net_income"] < b["threshold"] * factor
    # the saved poverty flags and the resources-below-threshold test must agree
    assert np.allclose(rate(poor25, groups["all"]), rate(b["in_spm_poverty"] > 0, groups["all"]), atol=1e-9)
    row = {}
    for g, m in groups.items():
        r24, r25, r25a = rate(poor24, m), rate(poor25, m), rate(poor25_anchored, m)
        row[g] = {"change": round(r25 - r24, 3), "threshold": round(r25 - r25a, 3), "resources": round(r25a - r24, 3)}
    out["variants"][v] = row
json.dump(out, open("variant_split.json", "w"), indent=1)

print(f"{'variant':24s} " + " ".join(f"{g:>26s}" for g in CENSUS))
print(f"{'census':24s} " + " ".join(f"{c:+.2f} = {t:+.2f} {r:+.2f}".rjust(26) for c, t, r in CENSUS.values()))
for v, row in out["variants"].items():
    print(f"{v:24s} " + " ".join(f"{row[g]['change']:+.2f} = {row[g]['threshold']:+.2f} {row[g]['resources']:+.2f}".rjust(26) for g in CENSUS))

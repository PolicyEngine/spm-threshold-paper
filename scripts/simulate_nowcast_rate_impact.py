"""SPM headcount effect of adopting the 2025 nowcast in policyengine-us.

Current aging: corrected 2024 base x PolicyEngine CPI-U ratio.
Nowcast aging: corrected 2024 base x blend ratio (2025), price-aged
beyond. For both 2025 and 2026 the nowcast/current threshold ratio per
tenure is blend_ratio[tenure] / cpiu_factor(2025/2024) — the later CPI
factors are common to both scenarios and cancel.

One simulation per year: net income is scenario-invariant, so the
nowcast counterfactual rescales each unit's threshold exactly.
"""

import gc
import json

import numpy as np

from policyengine_us import CountryTaxBenefitSystem, Microsimulation
from spm_calculator import nowcast_with_metadata

OUT = "/private/tmp/claude-501/-Users-maxghenis/df49f127-9b39-49ca-a681-58a1a922dc27/scratchpad/nowcast_rate_impact.json"

doc = nowcast_with_metadata(2025)
blend = {t.upper(): c["blend_ratio"] for t, c in doc["components"].items()}

cpi_u = CountryTaxBenefitSystem().parameters.gov.bls.cpi.cpi_u
cpi_factor = float(cpi_u("2025-02-01") / cpi_u("2024-02-01"))
RATIO = {t: b / cpi_factor for t, b in blend.items()}
print(f"PE CPI-U factor 2025/2024: {cpi_factor:.5f}")
print("nowcast/current threshold ratios:", {k: round(v, 5) for k, v in RATIO.items()})

results = {"threshold_ratio_nowcast_over_current": RATIO}
for year in (2025, 2026):
    sim = Microsimulation()
    net = sim.calculate("spm_unit_net_income", year)
    thr_cur = sim.calculate("spm_unit_spm_threshold", year)
    tenure = sim.calculate("spm_unit_tenure_type", year)

    ratio_arr = np.array(
        [RATIO.get(str(t).upper(), RATIO["RENTER"]) for t in tenure.values]
    )
    thr_now = thr_cur.values * ratio_arr

    pov_cur_u = (net.values < thr_cur.values).astype(float)
    pov_now_u = (net.values < thr_now).astype(float)

    person_weight = sim.calculate("person_weight", year).values
    age = sim.calculate("age", year).values
    pov_cur_p = sim.map_result(pov_cur_u, "spm_unit", "person")
    pov_now_p = sim.map_result(pov_now_u, "spm_unit", "person")

    def rate(flags, mask=None):
        w = person_weight if mask is None else person_weight * mask
        return float(np.sum(flags * w) / np.sum(w))

    groups = {
        "all": None,
        "children (<18)": (age < 18).astype(float),
        "seniors (65+)": (age >= 65).astype(float),
    }
    year_out = {}
    for label, mask in groups.items():
        r_cur = rate(pov_cur_p, mask)
        r_now = rate(pov_now_p, mask)
        year_out[label] = {
            "current_cpi_aging_rate": r_cur,
            "nowcast_rate": r_now,
            "delta_pp": (r_now - r_cur) * 100,
        }
        print(
            f"{year} {label:15s} cpi-aged {r_cur:6.2%}  "
            f"nowcast {r_now:6.2%}  delta {(r_now - r_cur) * 100:+.3f}pp"
        )
    results[year] = year_out

    del sim
    gc.collect()

with open(OUT, "w") as f:
    json.dump(results, f, indent=1)
print("wrote", OUT)

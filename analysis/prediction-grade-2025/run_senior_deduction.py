"""Run one population simulation and save person-level SPM arrays.

usage: python run_one.py <year> <variant>   variant in {baseline, no_senior_deduction}
"""
import json, resource, sys, time
import numpy as np
from policyengine_us import Microsimulation
from policyengine_us.system import DEFAULT_DATASET, DEFAULT_DATASET_SHA256

year, variant = int(sys.argv[1]), sys.argv[2]
t0 = time.time()
reform = None
if variant == "no_senior_deduction":
    from policyengine_core.reforms import Reform
    reform = Reform.from_dict(
        {"gov.irs.deductions.senior_deduction.amount": {f"{year}-01-01.{year}-12-31": 0}},
        country_id="us",
    )
sim = Microsimulation(reform=reform) if reform is not None else Microsimulation()
load = time.time() - t0
t1 = time.time()
cols = {}
for var in ("spm_unit_is_in_spm_poverty", "spm_unit_net_income", "spm_unit_spm_threshold", "age", "additional_senior_deduction", "income_tax"):
    s = sim.calc(var, period=year, map_to="person")
    cols[var] = np.asarray(s.values)
    if "weight" not in cols:
        cols["weight"] = np.asarray(s.weights)
cols["spm_unit_id"] = np.asarray(sim.calc("spm_unit_id", period=year, map_to="person").values)
np.savez_compressed(f"arrays-{year}-{variant}.npz", **cols)
w, pov, age = cols["weight"], cols["spm_unit_is_in_spm_poverty"].astype(float), cols["age"]
def rate(mask):
    return float((pov[mask] * w[mask]).sum() / w[mask].sum() * 100)
meta = {
    "year": year, "variant": variant, "dataset": DEFAULT_DATASET, "dataset_sha256": DEFAULT_DATASET_SHA256,
    "reform": {"gov.irs.deductions.senior_deduction.amount": 0} if reform is not None else None,
    "load_seconds": round(load, 1), "calc_seconds": round(time.time() - t1, 1),
    "peak_rss_gb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9, 2),
    "rates_pct": {"all": rate(np.ones_like(age, bool)), "under_18": rate(age < 18), "age_65_plus": rate(age >= 65)},
    "weighted_people_millions": round(float(w.sum()) / 1e6, 3),
}
json.dump(meta, open(f"meta-{year}-{variant}.json", "w"), indent=1)
print(json.dumps(meta), flush=True)

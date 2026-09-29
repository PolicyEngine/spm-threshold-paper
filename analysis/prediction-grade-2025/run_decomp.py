"""One population run; variants: baseline | anchored_2024_cpi (2025 thresholds scaled by tenure to the
corrected 2024 BLS national base x 32,649/31,812, the same anchoring as the ASEC recomputation).
usage: python run_decomp.py <year> <variant>"""
import json, resource, sys, time
import numpy as np
from policyengine_us import Microsimulation
from policyengine_us.system import system, DEFAULT_DATASET, DEFAULT_DATASET_SHA256

year, variant = int(sys.argv[1]), sys.argv[2]
T25 = {"OWNER_WITH_MORTGAGE": 41322.707394, "OWNER_WITHOUT_MORTGAGE": 34325.99772, "RENTER": 41700.555713}
T24 = {"OWNER_WITH_MORTGAGE": 39230.994457, "OWNER_WITHOUT_MORTGAGE": 32878.594848, "RENTER": 39219.893902}
CPI = 32649 / 31812
FACTORS = {k: T24[k] * CPI / T25[k] for k in T25}
reform = None
if variant == "anchored_2024_cpi":
    from policyengine_core.reforms import Reform
    from policyengine_core.model_api import Variable, YEAR
    base_cls = type(system.variables["spm_unit_spm_threshold"]); base_formula = base_cls.formula
    entity = base_cls.entity
    class spm_unit_spm_threshold(Variable):
        value_type = float; entity = entity; definition_period = YEAR; label = "SPM threshold anchored to 2024 x CPI-U"; unit = "currency-USD"
        def formula(unit, period, parameters):
            base = np.asarray(base_formula(unit, period, parameters), dtype=np.float64)
            ten = np.asarray(unit("spm_unit_tenure_type", period).decode_to_str())
            f = np.select([ten == k for k in FACTORS], [FACTORS[k] for k in FACTORS], default=np.nan)
            assert not np.isnan(f).any(), "unknown tenure"
            return base * f
    class Anchor(Reform):
        def apply(self):
            self.update_variable(spm_unit_spm_threshold)
    reform = Anchor
t0 = time.time()
sim = Microsimulation(reform=reform) if reform is not None else Microsimulation()
load = time.time() - t0; t1 = time.time()
cols = {}
for var in ("spm_unit_is_in_spm_poverty", "in_poverty", "spm_unit_net_income", "spm_unit_spm_threshold", "age", "spm_unit_tenure_type"):
    s = sim.calc(var, period=year, map_to="person")
    cols[var] = np.asarray(s.values) if var != "spm_unit_tenure_type" else np.asarray(s.values).astype(str)
    if "weight" not in cols: cols["weight"] = np.asarray(s.weights)
np.savez_compressed(f"arrays-{year}-{variant}.npz", **cols)
w, age = cols["weight"], cols["age"]
def rate(flag, m): return float((flag[m].astype(float) * w[m]).sum() / w[m].sum() * 100)
groups = {"all": age >= 0, "under_18": age < 18, "under_6": age < 6, "age_18_64": (age >= 18) & (age < 65), "age_65_plus": age >= 65}
meta = {"year": year, "variant": variant, "factors": FACTORS if reform is not None else None, "dataset": DEFAULT_DATASET, "dataset_sha256": DEFAULT_DATASET_SHA256,
        "load_seconds": round(load, 1), "calc_seconds": round(time.time() - t1, 1), "peak_rss_gb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9, 2),
        "spm_pct": {g: rate(cols["spm_unit_is_in_spm_poverty"], m) for g, m in groups.items()},
        "official_pct": {g: rate(cols["in_poverty"], m) for g, m in groups.items()},
        "median_threshold_2a2k_by_tenure": {}}
json.dump(meta, open(f"meta-{year}-{variant}.json", "w"), indent=1); print(json.dumps(meta), flush=True)

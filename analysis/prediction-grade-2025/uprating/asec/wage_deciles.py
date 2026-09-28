"""Survey wage growth from calendar 2024 (ASEC 2025) to 2025 (ASEC 2026): mean wage within each wage decile,
and mean wage per earner by SPM band. Cross-sections, not a panel. Writes wage_deciles.json."""
import json
import numpy as np
import pandas as pd


def load(yy):
    d = pd.read_csv(f"pppub{yy}.csv", usecols=["A_AGE", "MARSUPWT", "WSAL_VAL", "WKSWORK", "HRSWK", "SPM_RESOURCES", "SPM_POVTHRESHOLD"])
    d["w"] = d.MARSUPWT / 100
    return d


a, b = load(25), load(26)


def bins(d, m, nb=10):
    x, w = d.WSAL_VAL[m].to_numpy(float), d.w[m].to_numpy()
    o = np.argsort(x, kind="stable")
    x, w = x[o], w[o]
    c = np.cumsum(w) / w.sum()
    idx = np.minimum((c * nb).astype(int), nb - 1)
    return [float((x[idx == k] * w[idx == k]).sum() / w[idx == k].sum()) for k in range(nb)]


out = {}
for label, f in (("all_earners", lambda d: (d.WSAL_VAL > 0) & (d.A_AGE >= 16)),
                 ("fyft", lambda d: (d.WSAL_VAL > 0) & (d.A_AGE >= 16) & (d.WKSWORK >= 50) & (d.HRSWK >= 35))):
    ma, mb = bins(a, f(a)), bins(b, f(b))
    out[label] = {"decile_mean_2024": [round(v) for v in ma], "decile_mean_2025": [round(v) for v in mb],
                  "growth_pct": [round(100 * (y / x - 1), 2) for x, y in zip(ma, mb)]}
    print(label, out[label]["growth_pct"])
# Earners ranked by their SPM unit's resources over threshold (family income relative to need), each year's own deciles
def ratio_bins(d, nb=10):
    m = (d.WSAL_VAL > 0) & (d.A_AGE >= 16)
    r, x, w = (d.SPM_RESOURCES / d.SPM_POVTHRESHOLD)[m].to_numpy(float), d.WSAL_VAL[m].to_numpy(float), d.w[m].to_numpy()
    o = np.argsort(r, kind="stable")
    r, x, w = r[o], x[o], w[o]
    c = np.cumsum(w) / w.sum()
    idx = np.minimum((c * nb).astype(int), nb - 1)
    return ([float((x[idx == k] * w[idx == k]).sum() / w[idx == k].sum()) for k in range(nb)],
            [float(r[idx == k].max()) for k in range(nb)])


(ma, ca), (mb, cb) = ratio_bins(a), ratio_bins(b)
out["by_spm_ratio_decile"] = {"decile_mean_2024": [round(v) for v in ma], "decile_mean_2025": [round(v) for v in mb],
                              "decile_upper_ratio_2024": [round(v, 2) for v in ca], "decile_upper_ratio_2025": [round(v, 2) for v in cb],
                              "growth_pct": [round(100 * (y / x - 1), 2) for x, y in zip(ma, mb)]}
print("by_spm_ratio_decile", out["by_spm_ratio_decile"]["growth_pct"])
# Fixed bands are selected on the outcome (resources include wages), so treat them as descriptive only.
for yr, d in (("2024", a), ("2025", b)):
    r = d.SPM_RESOURCES / d.SPM_POVTHRESHOLD
    e = (d.WSAL_VAL > 0) & (d.A_AGE >= 16)
    for lab, m in (("near", e & (r > 0.75) & (r < 1.5)), ("below", e & (r <= 0.75)), ("above", e & (r >= 1.5))):
        out.setdefault("by_spm_band", {}).setdefault(lab, {})[yr] = {
            "mean_wage": round(float((d.WSAL_VAL[m] * d.w[m]).sum() / d.w[m].sum())), "earners_m": round(float(d.w[m].sum()) / 1e6, 2)}
json.dump(out, open("wage_deciles.json", "w"), indent=1)

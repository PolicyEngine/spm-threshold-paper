"""Survey growth from calendar 2024 (ASEC 2025) to calendar 2025 (ASEC 2026): wages by wage level,
Social Security and pensions per recipient, and aggregate totals. Cross-sections, not a panel."""
import json
import numpy as np
import pandas as pd

COLS = ["PH_SEQ", "A_AGE", "MARSUPWT", "WSAL_VAL", "SEMP_VAL", "SS_VAL", "SSI_VAL", "PNSN_VAL", "ANN_VAL",
        "DST_VAL1", "DST_VAL2", "INT_VAL", "DIV_VAL", "UC_VAL", "WKSWORK", "HRSWK", "SPM_ID", "SPM_RESOURCES",
        "SPM_POVTHRESHOLD", "SPM_SNAPSUB", "SPM_CAPHOUSESUB", "SPM_SCHLUNCH", "SPM_WICVAL", "SPM_FEDTAX",
        "SPM_STTAX", "SPM_FICA", "SPM_MEDXPNS", "SPM_CAPWKCCXPNS", "SPM_CHILDSUPPD", "SPM_TOTVAL", "SPM_ENGVAL",
        "SPM_EITC", "SPM_ACTC", "SPM_FEDTAXBC"]


def load(yy):
    d = pd.read_csv(f"pppub{yy}.csv", usecols=COLS)
    d["w"] = d.MARSUPWT / 100
    d["pension"] = d.PNSN_VAL + d.ANN_VAL
    d["distrib"] = d.DST_VAL1 + d.DST_VAL2
    return d


def wq(x, w, q):
    o = np.argsort(x)
    c = np.cumsum(w[o])
    return float(x[o][np.searchsorted(c, q * c[-1])])


a, b = load(25), load(26)
out = {}

Q = [0.1, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.75, 0.9]
for label, f in (("all_wage_earners", lambda d: (d.WSAL_VAL > 0) & (d.A_AGE >= 16)),
                 ("full_year_full_time", lambda d: (d.WSAL_VAL > 0) & (d.A_AGE >= 16) & (d.WKSWORK >= 50) & (d.HRSWK >= 35))):
    ma, mb = f(a), f(b)
    row = {}
    for q in Q:
        qa = wq(a.WSAL_VAL[ma].to_numpy(float), a.w[ma].to_numpy(), q)
        qb = wq(b.WSAL_VAL[mb].to_numpy(float), b.w[mb].to_numpy(), q)
        row[f"p{int(q*100)}"] = {"2024": qa, "2025": qb, "growth_pct": round(100 * (qb / qa - 1), 2)}
    row["workers_millions"] = {"2024": round(a.w[ma].sum() / 1e6, 2), "2025": round(b.w[mb].sum() / 1e6, 2)}
    out[label] = row


def per_recipient(col, cond):
    r = {}
    for yr, d in (("2024", a), ("2025", b)):
        m = (d[col] > 0) & cond(d)
        x, w = d[col][m].to_numpy(float), d.w[m].to_numpy()
        r[yr] = {"mean": round(float((x * w).sum() / w.sum()), 0), "median": wq(x, w, 0.5),
                 "recipients_millions": round(float(w.sum()) / 1e6, 2), "total_billions": round(float((x * w).sum()) / 1e9, 1)}
    r["mean_growth_pct"] = round(100 * (r["2025"]["mean"] / r["2024"]["mean"] - 1), 2)
    r["median_growth_pct"] = round(100 * (r["2025"]["median"] / r["2024"]["median"] - 1), 2)
    r["recipients_growth_pct"] = round(100 * (r["2025"]["recipients_millions"] / r["2024"]["recipients_millions"] - 1), 2)
    r["total_growth_pct"] = round(100 * (r["2025"]["total_billions"] / r["2024"]["total_billions"] - 1), 2)
    return r


out["social_security_all"] = per_recipient("SS_VAL", lambda d: d.A_AGE >= 0)
out["social_security_65_plus"] = per_recipient("SS_VAL", lambda d: d.A_AGE >= 65)
out["pensions_annuities_65_plus"] = per_recipient("pension", lambda d: d.A_AGE >= 65)
out["retirement_distributions_65_plus"] = per_recipient("distrib", lambda d: d.A_AGE >= 65)
out["wages_all"] = per_recipient("WSAL_VAL", lambda d: d.A_AGE >= 0)
out["population_65_plus_millions"] = {"2024": round(a.w[a.A_AGE >= 65].sum() / 1e6, 2), "2025": round(b.w[b.A_AGE >= 65].sum() / 1e6, 2)}
out["population_millions"] = {"2024": round(a.w.sum() / 1e6, 2), "2025": round(b.w.sum() / 1e6, 2)}

# Near-line cross-sections: people whose SPM unit's resources fall between 75 and 150 percent of its threshold.
UNIT = {"wages_se": ["WSAL_VAL", "SEMP_VAL"], "social_security": ["SS_VAL"], "pensions_distrib": ["pension", "distrib"],
        "ssi": ["SSI_VAL"], "unemployment": ["UC_VAL"]}
SPM = {"snap": "SPM_SNAPSUB", "housing": "SPM_CAPHOUSESUB", "school_lunch": "SPM_SCHLUNCH", "wic": "SPM_WICVAL",
       "energy": "SPM_ENGVAL", "fed_tax_net": "SPM_FEDTAX", "eitc": "SPM_EITC", "actc": "SPM_ACTC", "state_tax": "SPM_STTAX",
       "fica": "SPM_FICA", "moop": "SPM_MEDXPNS", "work_childcare": "SPM_CAPWKCCXPNS", "resources": "SPM_RESOURCES",
       "threshold": "SPM_POVTHRESHOLD"}


def near(d):
    for k, cs in UNIT.items():
        d[k] = d.groupby(["PH_SEQ", "SPM_ID"])[cs].transform("sum").sum(axis=1)
    ratio = d.SPM_RESOURCES / d.SPM_POVTHRESHOLD
    return d[(ratio > 0.75) & (ratio < 1.5) & (d.SPM_RESOURCES > 0)]


na, nb = near(a), near(b)
nl = {}
for label, f in (("all", lambda d: d.A_AGE >= 0), ("under_18", lambda d: d.A_AGE < 18), ("age_65_plus", lambda d: d.A_AGE >= 65)):
    xa, xb = na[f(na)], nb[f(nb)]
    row = {"people_millions": {"2024": round(xa.w.sum() / 1e6, 2), "2025": round(xb.w.sum() / 1e6, 2)}}
    for k in list(UNIT) + list(SPM):
        col = SPM.get(k, k)
        ma_, mb_ = float((xa[col] * xa.w).sum() / xa.w.sum()), float((xb[col] * xb.w).sum() / xb.w.sum())
        row[k] = {"2024": round(ma_), "2025": round(mb_), "growth_pct": round(100 * (mb_ / ma_ - 1), 2) if ma_ else None}
    nl[label] = row
out["near_line_cross_section_unit_means"] = nl
json.dump(out, open("survey_growth.json", "w"), indent=1)

for k in ("all_wage_earners", "full_year_full_time"):
    print(k, {q: v["growth_pct"] for q, v in out[k].items() if q.startswith("p")}, out[k]["workers_millions"])
for k in ("social_security_all", "social_security_65_plus", "pensions_annuities_65_plus", "retirement_distributions_65_plus", "wages_all"):
    r = out[k]
    print(k, "mean", r["mean_growth_pct"], "median", r["median_growth_pct"], "recipients", r["recipients_growth_pct"], "total", r["total_growth_pct"], r["2024"], r["2025"])
print("pop65", out["population_65_plus_millions"], "pop", out["population_millions"])
for g, row in nl.items():
    print("near-line", g, row["people_millions"])
    for k, v in row.items():
        if k != "people_millions":
            print(f"    {k:18s} {v['2024']:>8} {v['2025']:>8} {v['growth_pct']}")

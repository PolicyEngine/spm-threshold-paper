"""Which resource sources drive 2024->2025 resource growth near the line, by age group.

Near the line = 2024 SPM resources between 75 and 150 percent of the 2024 threshold, resources positive
(the same cut as near_line_growth.py in spm-threshold-paper). Person-weighted; each person carries
their SPM unit's sources. Contribution of a source = weighted mean over people of
(source_2025 - source_2024) / resources_2024, in percent, so contributions add to the mean growth.
"""
import json
import sys
import numpy as np

VARIANT = sys.argv[1] if len(sys.argv) > 1 else "baseline"
a, b = np.load("sources-2024-baseline.npz"), np.load(f"sources-2025-{VARIANT}.npz")
assert (a["person_id"] == b["person_id"]).all()
w, age = a["weight"], a["age"]
r24, r25 = a["net_income"], b["net_income"]
ratio = r24 / a["threshold"]

ADD = ["wages", "self_employment", "pensions_retirement", "interest_dividends_gains", "rental",
       "social_security", "ssi", "unemployment", "snap", "housing_subsidy", "school_meals", "wic", "tanf"]
SUB = ["payroll_tax", "federal_tax", "state_tax", "moop", "work_childcare", "child_support_paid"]
SS_PARTS = ["social_security_retirement", "social_security_disability", "social_security_survivors", "social_security_dependents"]


def wq(x, wt, q):
    o = np.argsort(x)
    c = np.cumsum(wt[o])
    return float(x[o][np.searchsorted(c, q * c[-1])])


def other(d):
    market_other = d["market_total"] - sum(d[k] for k in ["wages", "self_employment", "pensions_retirement", "interest_dividends_gains", "rental"])
    ben_other = d["benefits_total"] - sum(d[k] for k in ["social_security", "ssi", "unemployment", "snap", "housing_subsidy", "school_meals", "wic", "tanf"])
    resid = d["net_income"] - (d["market_total"] + d["benefits_total"] - d["taxes_total"] - d["expenses_total"])
    return market_other + ben_other + resid


out = {}
for label, m in (("all", age >= 0), ("under_18", age < 18), ("age_18_64", (age >= 18) & (age < 65)), ("age_65_plus", age >= 65)):
    n = m & (ratio > 0.75) & (ratio < 1.5) & (r24 > 0)
    ww = w[n]
    def mean(x):
        return float((x[n] * ww).sum() / ww.sum())
    g = r25[n] / r24[n] - 1
    rows = {}
    for k in ADD + SUB:
        sign = 1 if k in ADD else -1
        d = sign * (b[k] - a[k]) / r24
        s24, s25 = (a[k][n] * ww).sum(), (b[k][n] * ww).sum()
        rows[k] = {
            "share_of_2024_resources_pct": round(100 * sign * mean(a[k] / r24), 2),
            "own_growth_pct": round(100 * (s25 / s24 - 1), 2) if s24 != 0 else None,
            "contribution_pp": round(100 * mean(d), 3),
            "people_with_source_pct": round(100 * float((ww * (a[k][n] != 0)).sum() / ww.sum()), 1),
        }
    oth = (other(b) - other(a)) / r24
    rows["other_and_residual"] = {"contribution_pp": round(100 * mean(oth), 3), "share_of_2024_resources_pct": round(100 * mean(other(a) / r24), 2)}
    ss_parts = {}
    for k in SS_PARTS:
        s24, s25 = (a[k][n] * ww).sum(), (b[k][n] * ww).sum()
        ss_parts[k] = {"own_growth_pct": round(100 * (s25 / s24 - 1), 2) if s24 else None, "contribution_pp": round(100 * mean((b[k] - a[k]) / r24), 3)}
    out[label] = {
        "people_millions": round(float(ww.sum()) / 1e6, 2),
        "median_growth_pct": round(100 * wq(g, ww, 0.5), 2),
        "mean_growth_pct": round(100 * float((g * ww).sum() / ww.sum()), 2),
        "sum_of_contributions_pp": round(sum(r["contribution_pp"] for r in rows.values()), 3),
        "sources": rows,
        "social_security_parts": ss_parts,
    }
json.dump(out, open(f"near_line_sources-{VARIANT}.json", "w"), indent=1)

for label, o in out.items():
    print(f"\n== {label}: {o['people_millions']}M near the line; median growth {o['median_growth_pct']}%, mean {o['mean_growth_pct']}% (sum of parts {o['sum_of_contributions_pp']})")
    print(f"   {'source':26s} {'share%':>7s} {'own gr%':>8s} {'contrib pp':>10s} {'has%':>6s}")
    for k, r in sorted(o["sources"].items(), key=lambda kv: -abs(kv[1]["contribution_pp"])):
        print(f"   {k:26s} {r.get('share_of_2024_resources_pct', ''):>7} {str(r.get('own_growth_pct', '')):>8s} {r['contribution_pp']:>10.3f} {str(r.get('people_with_source_pct', '')):>6s}")
    print("   SS parts:", {k.replace('social_security_', ''): v for k, v in o["social_security_parts"].items()})

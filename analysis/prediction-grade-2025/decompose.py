"""Split the modeled and the Census 2024-to-2025 SPM changes into a threshold effect and a resource effect.

threshold effect = rate at the year's thresholds minus rate at 2024 thresholds plus CPI-U (both on 2025 resources)
resource effect  = rate at 2024 thresholds plus CPI-U (2025 resources) minus the 2024 rate

Model side: three population runs (results/runs/decomp-meta-*.json, written by run_decomp.py).
Census side: unrounded rates from P60-290 Table 5 and the anchored recomputation on the 2026 CPS ASEC file
(analysis/asec-2026-anchored-thresholds in this repository).

usage: python decompose.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
RUNS = HERE / "results" / "runs"
GROUPS = ("all", "under_18", "age_18_64", "age_65_plus")

# https://www2.census.gov/programs-surveys/demo/tables/p60/290/table_5_spm_program_effect_rates.xlsx
CENSUS_TABLE_5 = {
    2024: {"all": 13.04, "under_18": 13.46, "age_18_64": 12.23, "age_65_plus": 15.13},
    2025: {"all": 13.11, "under_18": 13.40, "age_18_64": 12.28, "age_65_plus": 15.37},
}
# 2026 CPS ASEC public-use file, 2025 thresholds replaced by corrected 2024 thresholds x 32,649/31,812
ASEC_2025_AT_2024_THRESHOLDS = {"all": 12.31, "under_18": 12.31, "age_18_64": 11.55, "age_65_plus": 14.66}


def meta(name):
    return json.loads((RUNS / f"decomp-meta-{name}.json").read_text())["spm_pct"]


m24, m25, m25a = meta("2024-baseline"), meta("2025-baseline"), meta("2025-anchored_2024_cpi")
out = {"model": {}, "census": {}, "model_minus_census": {}}
for g in GROUPS:
    model = {
        "rate_2024": m24[g],
        "rate_2025": m25[g],
        "rate_2025_at_2024_thresholds": m25a[g],
        "change": m25[g] - m24[g],
        "threshold_effect": m25[g] - m25a[g],
        "resource_effect": m25a[g] - m24[g],
    }
    c24, c25, c25a = CENSUS_TABLE_5[2024][g], CENSUS_TABLE_5[2025][g], ASEC_2025_AT_2024_THRESHOLDS[g]
    census = {
        "rate_2024": c24,
        "rate_2025": c25,
        "rate_2025_at_2024_thresholds": c25a,
        "change": round(c25 - c24, 2),
        "threshold_effect": round(c25 - c25a, 2),
        "resource_effect": round(c25a - c24, 2),
    }
    out["model"][g] = {k: round(v, 6) for k, v in model.items()}
    out["census"][g] = census
    out["model_minus_census"][g] = {
        k: round(model[k] - census[k], 2) for k in ("change", "threshold_effect", "resource_effect")
    }
out["model"]["under_6"] = {
    "rate_2024": round(m24["under_6"], 6),
    "rate_2025": round(m25["under_6"], 6),
    "rate_2025_at_2024_thresholds": round(m25a["under_6"], 6),
    "change": round(m25["under_6"] - m24["under_6"], 6),
    "threshold_effect": round(m25["under_6"] - m25a["under_6"], 6),
    "resource_effect": round(m25a["under_6"] - m24["under_6"], 6),
}
(HERE / "results" / "model_decomposition.json").write_text(json.dumps(out, indent=1) + "\n")
for g in GROUPS:
    m, c = out["model"][g], out["census"][g]
    print(f"{g:12s} model {m['change']:+.2f} = {m['threshold_effect']:+.2f} {m['resource_effect']:+.2f}"
          f"   census {c['change']:+.2f} = {c['threshold_effect']:+.2f} {c['resource_effect']:+.2f}")

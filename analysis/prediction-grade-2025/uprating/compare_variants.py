"""Modeled 2024->2025 SPM poverty change under each 2025 variant, against Census (P60-290 Table 5, two decimals)."""
import json
from pathlib import Path

CENSUS = {"all": 0.07, "under_18": -0.06, "age_65_plus": 0.24}
REGISTERED = {"all": 0.22, "under_18": 0.86, "age_65_plus": -0.52}
base24 = json.load(open("sources-meta-2024-baseline.json"))["spm_pct"]
out = {"census_change_pp": CENSUS, "registered_change_pp": REGISTERED, "rate_2024_pct": base24, "variants": {}}
for v in ("baseline", "ss_cola", "ss_cola_pension_cpi", "wages_by_decile", "se_like_wages", "all_three"):
    f = Path(f"sources-meta-2025-{v}.json")
    if not f.exists():
        continue
    r = json.load(open(f))["spm_pct"]
    ch = {g: round(r[g] - base24[g], 3) for g in CENSUS}
    out["variants"][v] = {"rate_2025_pct": {g: round(r[g], 3) for g in r}, "change_pp": ch,
                          "miss_pp": {g: round(ch[g] - CENSUS[g], 3) for g in CENSUS}}
json.dump(out, open("variant_comparison.json", "w"), indent=1)
print(f"{'variant':22s} " + " ".join(f"{g:>22s}" for g in CENSUS))
print(f"{'census change':22s} " + " ".join(f"{CENSUS[g]:>22.2f}" for g in CENSUS))
for v, o in out["variants"].items():
    print(f"{v:22s} " + " ".join(f"{o['change_pp'][g]:>+10.2f} (miss {o['miss_pp'][g]:+.2f})" for g in CENSUS))

"""Score the pre-committed 2025 nowcast against BLS's published thresholds.

This is the evaluation the paper committed to in advance: signed
percent error per tenure and mean absolute error for the amended
nowcast, the original (pre-repair) nowcast, and every rule in the
backtest table, all computed from the corrected 2024 base exactly as
pinned in data/threshold_series.json — regardless of any later BLS
revision to 2024. Inputs are the pinned artifacts plus
data/bls_2025_thresholds.json (BLS's 2025 page, retrieved 2026-09-04).

Also validates the paper's FCSUti composite against BLS's own FCSUti
index growth, which BLS publishes only alongside each year's
thresholds (Chart 4 on the same page).

    uv run python scripts/evaluate_nowcast_2025.py
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
OUT = REPO / "paper" / "tables"

TENURES = ("owner_with_mortgage", "owner_without_mortgage", "renter")
LABELS = {
    "owner_with_mortgage": "Owners with mortgages",
    "owner_without_mortgage": "Owners without mortgages",
    "renter": "Renters",
}

actual = json.loads((DATA / "bls_2025_thresholds.json").read_text())
nowcast = json.loads((DATA / "nowcast_2025.json").read_text())
cpi = json.loads((DATA / "bls_cpi_series.json").read_text())
series_doc = json.loads((DATA / "threshold_series.json").read_text())

corrected_2024 = None
for seg in series_doc["series"]["bls-corrected-2026-07-17"]["segments"].values():
    if "2024" in seg["years"]:
        corrected_2024 = {
            t: m["threshold"] for t, m in seg["years"]["2024"].items()
        }
assert corrected_2024 is not None

# The original (pre-repair) nowcast, from the tagged release rather
# than a hand-copied number.
original = json.loads(
    subprocess.run(
        ["git", "show", "v1.0-original-nowcast:data/nowcast_2025.json"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
)

cpi_u_ratio = cpi["CUUR0000SA0"]["2025"] / cpi["CUUR0000SA0"]["2024"]

rules = {
    "Amended nowcast (50/50 blend, committed)": nowcast["values"],
    "Original nowcast (pre-repair blend)": original["values"],
    "CE replication growth ratio alone": {
        t: corrected_2024[t] * nowcast["components"][t]["replication_ratio"]
        for t in TENURES
    },
    "FCSUti-composite CPI aging alone": {
        t: corrected_2024[t] * nowcast["components"][t]["price_ratio"]
        for t in TENURES
    },
    "All-Items CPI-U aging (status quo)": {
        t: corrected_2024[t] * cpi_u_ratio for t in TENURES
    },
}

lines = [
    "| Rule | Owners w/ mortgage | Owners w/o mortgage | Renters "
    "| Mean abs. error |",
    "|---|---:|---:|---:|---:|",
]
results = {}
for name, values in rules.items():
    errs = {t: values[t] / actual["values"][t] - 1 for t in TENURES}
    mae = sum(abs(e) for e in errs.values()) / 3
    results[name] = {"errors": errs, "mae": mae, "values": values}
    cells = " | ".join(f"{errs[t]:+.2%}" for t in TENURES)
    bold = name.startswith("Amended")
    label = f"**{name}**" if bold else name
    mae_txt = f"**{mae:.2%}**" if bold else f"{mae:.2%}"
    lines.append(f"| {label} | {cells} | {mae_txt} |")
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "evaluation.md").write_text("\n".join(lines) + "\n")
print("wrote paper/tables/evaluation.md")

# Actual vs nowcast levels, for the reader who wants dollars.
lines = [
    "| Tenure | BLS 2025 threshold | Amended nowcast | Error "
    "| BLS-stated growth | Nowcast growth |",
    "|---|---:|---:|---:|---:|---:|",
]
for t in TENURES:
    a = actual["values"][t]
    n = nowcast["values"][t]
    g_bls = actual["bls_stated_growth_pct_2025_over_2024"][t]
    g_now = (n / corrected_2024[t] - 1) * 100
    lines.append(
        f"| {LABELS[t]} | \\${a:,.0f} | \\${n:,.2f} | {n / a - 1:+.2%} "
        f"| {g_bls:.2f}% | {g_now:.2f}% |"
    )
(OUT / "evaluation_levels.md").write_text("\n".join(lines) + "\n")
print("wrote paper/tables/evaluation_levels.md")

# Composite validation: our rebased FCSUti composite vs BLS's FCSUti.
CPI_IDS = {
    "food": "CUUR0000SAF",
    "apparel": "CUUR0000SAA",
    "shelter": "CUUR0000SAH1",
    "utilities": "CUUR0000SAH2",
    "telephone": "CUUR0000SEED",
}
WEIGHTS = {
    "food": 0.30,
    "apparel": 0.05,
    "shelter": 0.45,
    "utilities": 0.12,
    "telephone": 0.04,
}
REBASE_YEAR = 2019


def composite(year: int) -> float:
    avail = {
        c: w
        for c, w in WEIGHTS.items()
        if str(year) in cpi.get(CPI_IDS[c], {})
        and str(REBASE_YEAR) in cpi.get(CPI_IDS[c], {})
    }
    return sum(
        w * cpi[CPI_IDS[c]][str(year)] / cpi[CPI_IDS[c]][str(REBASE_YEAR)]
        for c, w in avail.items()
    ) / sum(avail.values())


lines = [
    "| Year | BLS FCSUti | Our composite | Gap (pp) | BLS CPI-U | Our CPI-U |",
    "|---|---:|---:|---:|---:|---:|",
]
gaps = []
for year in range(2020, 2026):
    bls = actual["bls_chart4_annual_average_inflation_pct"][str(year)]
    ours = (composite(year) / composite(year - 1) - 1) * 100
    ours_cpiu = (
        cpi["CUUR0000SA0"][str(year)] / cpi["CUUR0000SA0"][str(year - 1)] - 1
    ) * 100
    gap = ours - bls["fcsuti"]
    gaps.append(gap)
    lines.append(
        f"| {year} | {bls['fcsuti']:.2f}% | {ours:.2f}% | {gap:+.2f} "
        f"| {bls['cpi_u']:.2f}% | {ours_cpiu:.2f}% |"
    )
(OUT / "composite_validation.md").write_text("\n".join(lines) + "\n")
print("wrote paper/tables/composite_validation.md")

summary = {
    "actual_2025": actual["values"],
    "corrected_2024_base": corrected_2024,
    "cpi_u_ratio_pinned": cpi_u_ratio,
    "rules": {
        k: {"mae": v["mae"], "errors": v["errors"], "values": v["values"]}
        for k, v in results.items()
    },
    "composite_vs_bls_fcsuti_gap_pp": dict(zip(range(2020, 2026), gaps)),
}
(DATA / "evaluation_2025.json").write_text(json.dumps(summary, indent=1) + "\n")
print("wrote data/evaluation_2025.json")
for k, v in results.items():
    print(f"{k:45s} MAE {v['mae']:.2%}  " + "  ".join(f"{v['errors'][t]:+.2%}" for t in TENURES))
print("composite gap vs BLS FCSUti (pp):", [f"{g:+.2f}" for g in gaps])

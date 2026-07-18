"""Generate every numeric table in the paper from the data artifacts.

The paper's tables are includes, not prose: this script is the only
writer of paper/tables/*.md, so a number in the paper cannot drift from
the artifacts in data/ (whose SHA-256 sums are pinned in
data/SHA256SUMS). Rerun after any artifact update:

    uv run python scripts/build_tables.py
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
OUT = REPO / "paper" / "tables"

TENURES = ("owner_with_mortgage", "owner_without_mortgage", "renter")
TENURE_LABELS = {
    "owner_with_mortgage": "Owners with mortgages",
    "owner_without_mortgage": "Owners without mortgages",
    "renter": "Renters",
}

series_doc = json.loads((DATA / "threshold_series.json").read_text())
nowcast = json.loads((DATA / "nowcast_2025.json").read_text())
replication = json.loads((DATA / "replication_results.json").read_text())
cpi = json.loads((DATA / "bls_cpi_series.json").read_text())


def flat(series_name: str) -> dict[int, dict[str, float]]:
    entry = series_doc["series"][series_name]
    out: dict[int, dict[str, float]] = {}
    segments = (
        entry["segments"].values()
        if "segments" in entry
        else [{"years": entry["years"]}]
    )
    for seg in segments:
        for y, tenures in seg["years"].items():
            out[int(y)] = {t: m["threshold"] for t, m in tenures.items()}
    return out


corrected = flat("bls-corrected-2026-07-17")
published = flat("census-published-pre-correction")
legacy = flat("package-legacy-0.3")


def write(name: str, lines: list[str]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text("\n".join(lines) + "\n")
    print(f"wrote paper/tables/{name}")


# Table 1: published vs corrected, 2019-2024.
lines = [
    "| Year | Tenure | Published | Corrected | Change |",
    "|---|---|---:|---:|---:|",
]
for year in range(2019, 2025):
    for t in TENURES:
        pub, cor = published[year][t], corrected[year][t]
        lines.append(
            f"| {year} | {TENURE_LABELS[t]} | {pub:,.0f} | {cor:,.2f} "
            f"| {cor / pub - 1:+.1%} |"
        )
write("correction.md", lines)

# Table 2: what spm-calculator <=0.3.1 shipped vs published.
lines = [
    "| Year | Tenure | Package $\\leq$0.3.1 | Published | Error |",
    "|---|---|---:|---:|---:|",
]
for year in range(2019, 2025):
    for t in TENURES:
        leg, pub = legacy[year][t], published[year][t]
        lines.append(
            f"| {year} | {TENURE_LABELS[t]} | {leg:,.0f} | {pub:,.0f} "
            f"| {leg / pub - 1:+.1%} |"
        )
write("package_errors.md", lines)

# Table 3: replication signed deviations, matched anchors.
rows = {
    (r["target_year"], r["anchor"]): r
    for r in replication
    if r["principal"] == "include" and r["annualization"] == "quarter4"
}
lines = [
    "| Year | vs published (83% anchor) | vs corrected (82% anchor) |",
    "|---|---|---|",
]
for year in range(2019, 2025):
    pub_devs = rows[(year, "83")]["dev_vs_published"]
    cor_devs = rows[(year, "82")]["dev_vs_corrected"]

    def fmt(devs):
        return " / ".join(f"{devs[t]:+.1%}" for t in TENURES)

    lines.append(f"| {year} | {fmt(pub_devs)} | {fmt(cor_devs)} |")
write("replication.md", lines)

# Table 4: projection backtest. Recomputed here from the same inputs as
# scripts/backtest_threshold_projection.py in the spm-calculator repo.
CPI_IDS = {
    "food": "CUUR0000SAF",
    "apparel": "CUUR0000SAA",
    "shelter": "CUUR0000SAH1",
    "utilities": "CUUR0000SAH2",
    "telephone": "CUUR0000SEED",
    "all_items": "CUUR0000SA0",
}
WEIGHTS = {
    "food": 0.30,
    "apparel": 0.05,
    "shelter": 0.45,
    "utilities": 0.12,
    "telephone": 0.04,
}


def composite(year: int) -> float:
    avail = {
        c: w
        for c, w in WEIGHTS.items()
        if str(year) in cpi.get(CPI_IDS[c], {})
    }
    return sum(w * cpi[CPI_IDS[c]][str(year)] for c, w in avail.items()) / sum(
        avail.values()
    )


replicated_82 = {
    r["target_year"]: r["calculated"]
    for r in replication
    if r["principal"] == "include"
    and r["annualization"] == "quarter4"
    and r["anchor"] == "82"
}

RULES = ("cpi_u", "fcsuti_cpi", "replication_ratio", "blend")
RULE_LABELS = {
    "cpi_u": "All-Items CPI-U aging",
    "fcsuti_cpi": "FCSUti-composite CPI aging",
    "replication_ratio": "CE replication growth ratio",
    "blend": "50/50 blend (FCSUti CPI + replication)",
}
errors_by_rule: dict[str, list[float]] = {r: [] for r in RULES}
year_rows = []
for year in range(2020, 2025):
    base, actual = corrected[year - 1], corrected[year]
    f_cpi = cpi[CPI_IDS["all_items"]][str(year)] / cpi[CPI_IDS["all_items"]][
        str(year - 1)
    ]
    f_fcs = composite(year) / composite(year - 1)
    per_rule = {}
    for rule in RULES:
        errs = []
        for t in TENURES:
            r_rep = replicated_82[year][t] / replicated_82[year - 1][t]
            factor = {
                "cpi_u": f_cpi,
                "fcsuti_cpi": f_fcs,
                "replication_ratio": r_rep,
                "blend": (f_fcs + r_rep) / 2,
            }[rule]
            errs.append(base[t] * factor / actual[t] - 1)
        mean_abs = sum(abs(e) for e in errs) / 3
        errors_by_rule[rule].append(mean_abs)
        per_rule[rule] = mean_abs
    year_rows.append((year, per_rule))

lines = [
    "| Rule | "
    + " | ".join(str(y) for y, _ in year_rows)
    + " | Mean |",
    "|---|" + "---:|" * (len(year_rows) + 1),
]
for rule in RULES:
    cells = " | ".join(f"{pr[rule]:.2%}" for _, pr in year_rows)
    mean = sum(errors_by_rule[rule]) / len(errors_by_rule[rule])
    label = RULE_LABELS[rule]
    if rule == "blend":
        lines.append(f"| **{label}** | {cells} | **{mean:.2%}** |")
    else:
        lines.append(f"| {label} | {cells} | {mean:.2%} |")
write("backtest.md", lines)

# Table 5: the pre-registered 2025 nowcast.
lines = [
    "| Tenure | Replication ratio | FCSUti CPI ratio | Blend "
    "| Nowcast 2025 |",
    "|---|---:|---:|---:|---:|",
]
for t in TENURES:
    c = nowcast["components"][t]
    lines.append(
        f"| {TENURE_LABELS[t]} | {c['replication_ratio']:.4f} "
        f"| {c['price_ratio']:.4f} | {c['blend_ratio']:.4f} "
        f"| \\${nowcast['values'][t]:,.2f} |"
    )
write("nowcast.md", lines)

print("all tables written")

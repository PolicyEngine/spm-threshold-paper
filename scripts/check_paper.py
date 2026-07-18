"""Pre-render guard: fail the build if the paper drifts from the data.

Wired into ``_quarto.yml`` as a pre-render step, so ``quarto render``
fails when (a) the committed tables differ from what
``build_tables.py`` regenerates from the artifacts in ``data/``, (b)
``data/SHA256SUMS`` no longer matches the artifacts, or (c) a
load-bearing number quoted in the prose no longer matches the
artifact it derives from. This makes the Reproducibility section's
claim — the prose cannot drift from the data without the build
failing — literally true.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
QMD = (REPO / "paper" / "index.qmd").read_text()

failures: list[str] = []


def check(label: str, ok: bool) -> None:
    if not ok:
        failures.append(label)


# (a) Tables regenerate identically.
before = {
    p: p.read_text() for p in sorted((REPO / "paper" / "tables").glob("*.md"))
}
subprocess.run(
    [sys.executable, str(REPO / "scripts" / "build_tables.py")],
    check=True,
    capture_output=True,
)
for path, old in before.items():
    check(f"table drifted: {path.name}", path.read_text() == old)

# (b) Artifact hashes match SHA256SUMS.
for line in (REPO / "data" / "SHA256SUMS").read_text().splitlines():
    digest, name = line.split()
    actual = hashlib.sha256((REPO / name).read_bytes()).hexdigest()
    check(f"artifact hash mismatch: {name}", actual == digest)

# (c) Load-bearing prose numbers match artifacts.
TENURES = ("owner_with_mortgage", "owner_without_mortgage", "renter")

nowcast = json.loads((REPO / "data" / "nowcast_2025.json").read_text())
for literal, value in [
    ("41,036.34", nowcast["values"]["owner_with_mortgage"]),
    ("34,135.99", nowcast["values"]["owner_without_mortgage"]),
    ("40,755.98", nowcast["values"]["renter"]),
]:
    check(
        f"nowcast literal {literal}",
        literal in QMD and f"{value:,.2f}" == literal,
    )

# The superseded pre-amendment values quoted in the amendment note,
# and the stated 0.1-to-0.3-percent size of the amendment.
ORIGINAL = {
    "owner_with_mortgage": ("41,099.57", 41099.57),
    "owner_without_mortgage": ("34,250.70", 34250.70),
    "renter": ("40,791.72", 40791.72),
}
shifts = []
for t, (literal, value) in ORIGINAL.items():
    check(f"pre-amendment literal {literal}", literal in QMD)
    shifts.append(abs(nowcast["values"][t] / value - 1))
check(
    "amendment size 0.1 to 0.3 percent",
    "0.1 to 0.3 percent" in QMD
    and 0.0005 <= min(shifts)
    and max(shifts) < 0.0035,
)

rate = json.loads((REPO / "data" / "nowcast_rate_impact.json").read_text())
delta_2025 = rate["2025"]["all"]["delta_pp"]
check(
    "poverty sensitivity 0.4pp",
    "0.4 percentage points" in QMD and abs(delta_2025 - 0.4) < 0.05,
)

backtest = (REPO / "paper" / "tables" / "backtest.md").read_text()
for literal in ("2.23%", "1.57%", "0.41%", "**0.76%**"):
    check(f"backtest table literal {literal}", literal in backtest)
for literal in ("2.23", "1.57", "0.41", "0.76"):
    check(f"backtest prose literal {literal}", literal in QMD)

# Recompute all four backtest rules from the artifacts (mirrors
# build_tables.py, including the rebased composite).
cpi = json.loads((REPO / "data" / "bls_cpi_series.json").read_text())
replication = json.loads(
    (REPO / "data" / "replication_results.json").read_text()
)
series_doc = json.loads((REPO / "data" / "threshold_series.json").read_text())
corrected = {}
for seg in series_doc["series"]["bls-corrected-2026-07-17"][
    "segments"
].values():
    for y, tenures in seg["years"].items():
        corrected[int(y)] = {t: m["threshold"] for t, m in tenures.items()}

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


replicated_82 = {
    r["target_year"]: r["calculated"]
    for r in replication
    if r["principal"] == "include"
    and r["annualization"] == "quarter4"
    and r["anchor"] == "82"
}
signed_by_rule: dict[str, list[float]] = {}
annual_signed: dict[str, list[float]] = {}
abs_by_rule: dict[str, list[float]] = {}
for year in range(2020, 2025):
    f_cpi = cpi["CUUR0000SA0"][str(year)] / cpi["CUUR0000SA0"][str(year - 1)]
    f_fcs = composite(year) / composite(year - 1)
    for rule in ("cpi_u", "fcsuti_cpi", "replication_ratio", "blend"):
        errs = []
        for t in TENURES:
            r_rep = replicated_82[year][t] / replicated_82[year - 1][t]
            factor = {
                "cpi_u": f_cpi,
                "fcsuti_cpi": f_fcs,
                "replication_ratio": r_rep,
                "blend": (f_fcs + r_rep) / 2,
            }[rule]
            errs.append(
                corrected[year - 1][t] * factor / corrected[year][t] - 1
            )
        signed_by_rule.setdefault(rule, []).extend(errs)
        annual_signed.setdefault(rule, []).append(sum(errs) / 3)
        abs_by_rule.setdefault(rule, []).append(
            sum(abs(e) for e in errs) / 3
        )


def mae(rule: str) -> float:
    return sum(abs_by_rule[rule]) / len(abs_by_rule[rule])


signed_mean = sum(signed_by_rule["cpi_u"]) / len(signed_by_rule["cpi_u"])
check(
    "signed CPI-U bias -1.9",
    "1.9 percent" in QMD and abs(signed_mean - (-0.019)) < 0.002,
)
check(
    "composite removes ~thirty percent of CPI-U error",
    "thirty percent" in QMD
    and abs((1 - mae("fcsuti_cpi") / mae("cpi_u")) - 0.30) < 0.02,
)
rep_signed = sum(signed_by_rule["replication_ratio"]) / len(
    signed_by_rule["replication_ratio"]
)
check(
    "replication signed mean +0.1",
    "+0.1" in QMD and abs(rep_signed - 0.001) < 0.001,
)
check(
    "replication annual signed range +0.5 to −0.3",
    "+0.5 to −0.3" in QMD
    and abs(max(annual_signed["replication_ratio"]) - 0.005) < 0.001
    and abs(min(annual_signed["replication_ratio"]) - (-0.003)) < 0.001,
)
check(
    "blend annual signed range −0.1 to −1.4",
    "−0.1 to −1.4" in QMD
    and abs(max(annual_signed["blend"]) - (-0.001)) < 0.001
    and abs(min(annual_signed["blend"]) - (-0.014)) < 0.001,
)

# Replication level fidelity ranges quoted in prose (per-year mean
# absolute deviation across tenures, matched anchors).
mad_corrected, mad_published = [], []
for year in range(2019, 2025):
    for anchor, key, out in (
        ("82", "dev_vs_corrected", mad_corrected),
        ("83", "dev_vs_published", mad_published),
    ):
        row = next(
            r
            for r in replication
            if r["target_year"] == year
            and r["anchor"] == anchor
            and r["principal"] == "include"
            and r["annualization"] == "quarter4"
        )
        out.append(sum(abs(v) for v in row[key].values()) / 3)
check(
    "replication fidelity 1.5 to 2.1 vs corrected",
    "1.5 to 2.1" in QMD
    and abs(min(mad_corrected) - 0.015) < 0.001
    and abs(max(mad_corrected) - 0.021) < 0.001,
)
check(
    "replication fidelity 1.0 to 1.6 vs published",
    "1.0 to 1.6" in QMD
    and abs(min(mad_published) - 0.010) < 0.001
    and abs(max(mad_published) - 0.016) < 0.001,
)

# Nowcast growth ranges quoted in prose.
rep_growth = [
    nowcast["components"][t]["replication_ratio"] - 1 for t in TENURES
]
blend_growth = [nowcast["components"][t]["blend_ratio"] - 1 for t in TENURES]
price_growth = nowcast["components"]["renter"]["price_ratio"] - 1
check(
    "replication growth 4.4 to 6.0",
    "4.4 to 6.0" in QMD
    and abs(min(rep_growth) - 0.044) < 0.001
    and abs(max(rep_growth) - 0.060) < 0.001,
)
check(
    "price growth 3.2",
    "3.2 percent" in QMD and abs(price_growth - 0.032) < 0.001,
)
check(
    "blend growth 3.8 to 4.6",
    "3.8 to 4.6" in QMD
    and abs(min(blend_growth) - 0.038) < 0.001
    and abs(max(blend_growth) - 0.046) < 0.001,
)

# Realized 2025/2024 All-Items CPI-U growth quoted in prose.
realized_2025 = cpi["CUUR0000SA0"]["2025"] / cpi["CUUR0000SA0"]["2024"] - 1
check(
    "realized CPI-U 2025 growth 2.6",
    "2.6 percent" in QMD and abs(realized_2025 - 0.026) < 0.002,
)

if failures:
    print("PAPER DRIFT CHECK FAILED:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print(f"paper drift check passed ({len(before)} tables, prose pins OK)")

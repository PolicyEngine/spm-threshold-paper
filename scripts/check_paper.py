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
nowcast = json.loads((REPO / "data" / "nowcast_2025.json").read_text())
for literal, value in [
    ("41,099.57", nowcast["values"]["owner_with_mortgage"]),
    ("34,250.70", nowcast["values"]["owner_without_mortgage"]),
    ("40,791.72", nowcast["values"]["renter"]),
]:
    check(
        f"nowcast literal {literal}",
        literal in QMD and f"{value:,.2f}" == literal,
    )

rate = json.loads((REPO / "data" / "nowcast_rate_impact.json").read_text())
delta_2025 = rate["2025"]["all"]["delta_pp"]
check(
    "poverty sensitivity 0.4pp",
    "0.4 percentage points" in QMD and abs(delta_2025 - 0.39) < 0.05,
)

backtest = (REPO / "paper" / "tables" / "backtest.md").read_text()
for literal in ("2.23%", "1.40%", "1.58%", "**1.35%**"):
    check(f"backtest table literal {literal}", literal in backtest)
for literal in ("2.23", "1.35"):
    check(f"backtest prose literal {literal}", literal in QMD)

# Signed CPI-U bias quoted in prose (recomputed from artifacts).
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
signed = []
for year in range(2020, 2025):
    factor = cpi["CUUR0000SA0"][str(year)] / cpi["CUUR0000SA0"][str(year - 1)]
    for t in ("owner_with_mortgage", "owner_without_mortgage", "renter"):
        signed.append(
            corrected[year - 1][t] * factor / corrected[year][t] - 1
        )
signed_mean = sum(signed) / len(signed)
check(
    "signed CPI-U bias -1.9",
    "1.9 percent" in QMD and abs(signed_mean - (-0.019)) < 0.002,
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

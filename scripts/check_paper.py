"""Pre-render guard: fail the build if the paper drifts from the data.

Wired into ``_quarto.yml`` as a pre-render step and run by CI on every
push to master and every pull request. It fails when:

(a) the committed tables differ from what the generators regenerate
    from the artifacts in ``data/`` — with an explicit allowlist of
    generated tables, so a missing or extra table also fails;
(b) any QMD ``{{< include tables/... >}}`` names a table outside that
    allowlist;
(c) ``data/SHA256SUMS`` does not list exactly the artifacts present in
    ``data/`` or any listed hash mismatches (an emptied manifest fails);
(d) a figure quoted in the prose no longer matches the artifact it
    derives from. Literals are matched at numeric-token boundaries
    (so ``41,036.34`` does not match ``141,036.34``), and the three
    tenure amounts are matched as ordered triples in the sentences
    that state them, so a swap between tenures fails.

Scope, stated honestly: the guard covers artifact hashes, generated
tables, and the figures registered below. Numbers quoted from
external publications (P60 reports, BLS pages, Census working papers)
are bound to their citations, not to artifacts, and are the citation
referee's job; dates and ordinals are not registered. A 2026-09-04
reproducibility audit demonstrated the earlier substring-only version
passing under several of these attacks.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
from verify_commitments import verify_commitments

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
TABLES = REPO / "paper" / "tables"
QMD = (REPO / "paper" / "index.qmd").read_text()

TENURES = ("owner_with_mortgage", "owner_without_mortgage", "renter")

EXPECTED_TABLES = {
    "correction.md",
    "package_errors.md",
    "replication.md",
    "backtest.md",
    "nowcast.md",
    "evaluation.md",
    "evaluation_levels.md",
    "composite_validation.md",
    "current_release.md",
    "current_replication.md",
    "current_sensitivity.md",
    "current_projection.md",
}
GENERATORS = ("build_tables.py", "evaluate_nowcast_2025.py", "build_current_tables.py")

failures: list[str] = []


def check(label: str, ok: bool) -> None:
    if not ok:
        failures.append(label)


def has_number(literal: str, text: str = QMD, min_count: int = 1) -> bool:
    """Literal present at numeric-token boundaries: no digit, comma-digit,
    or dot-digit continuation on either side."""
    pattern = r"(?<![\d.,])" + re.escape(literal) + r"(?![\d]|[.,]\d)"
    return len(re.findall(pattern, text)) >= min_count


def has_ordered(literals: list[str], window: int = 400) -> bool:
    """The literals appear in this order within one window of text."""
    pattern = rf"[\s\S]{{0,{window}}}"
    body = pattern.join(re.escape(x) for x in literals)
    return re.search(body, QMD) is not None


# (c) SHA256SUMS lists exactly the artifacts present, and every hash holds.
# This must happen before any artifact is parsed or generator is invoked.
listed: dict[str, str] = {}
for number, line in enumerate((DATA / "SHA256SUMS").read_text().splitlines(), 1):
    fields = line.split()
    if len(fields) != 2:
        failures.append(f"malformed checksum manifest line {number}")
        continue
    digest, name = fields
    if not re.fullmatch(r"[0-9a-f]{64}", digest) or not re.fullmatch(
        r"data/[^/]+\.(?:json|xlsx)", name
    ):
        failures.append(f"invalid checksum manifest line {number}")
        continue
    if name in listed:
        failures.append(f"duplicate checksum manifest entry: {name}")
    listed[name] = digest
present_artifacts = {
    f"data/{p.name}" for p in DATA.iterdir() if p.suffix in (".json", ".xlsx")
}
check(
    f"SHA256SUMS coverage (unlisted {present_artifacts - set(listed)}, stale {set(listed) - present_artifacts})",
    set(listed) == present_artifacts and len(listed) > 0,
)
for name, digest in listed.items():
    path = REPO / name
    check(
        f"artifact hash mismatch: {name}",
        path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == digest,
    )

# Bundled BLS workbooks are the exact files BLS served on the stated dates.
BLS_WORKBOOK_SHA256 = "e7931a1f2540d52877d6fd14a8ed1e421e977a85c952ae1b6f690a04d904f2cb"
BLS_CURRENT_WORKBOOK_SHA256 = (
    "95f39fb5479ee5c196de627e06e10efd59af5148cf1c8466924e3fb2e5e2bd3b"
)
for fname, expected in (
    ("spm_threshold_200524_corrected.xlsx", BLS_WORKBOOK_SHA256),
    ("spm_thresholds_current_2026-09-04.xlsx", BLS_CURRENT_WORKBOOK_SHA256),
):
    check(
        f"bundled BLS workbook hash: {fname}",
        (DATA / fname).is_file()
        and hashlib.sha256((DATA / fname).read_bytes()).hexdigest() == expected,
    )

failures.extend(verify_commitments(REPO))

# The current experiment has a separate manifest, never the old timestamp.
current_names = {"spm-release.json", "ce_replication_2019_2025.json", "provenance.json"}
current_listed = {}
for number, line in enumerate(
    (DATA / "current" / "SHA256SUMS").read_text().splitlines(), 1
):
    fields = line.split()
    if (
        len(fields) != 2
        or not re.fullmatch(r"[0-9a-f]{64}", fields[0])
        or fields[1] not in {f"data/current/{name}" for name in current_names}
    ):
        failures.append(f"invalid current checksum manifest line {number}")
        continue
    digest, name = fields
    if name in current_listed:
        failures.append(f"duplicate current checksum entry: {name}")
    current_listed[name] = digest
current_present = {str(p.relative_to(REPO)) for p in (DATA / "current").glob("*.json")}
check(
    "current checksum coverage",
    set(current_listed)
    == current_present
    == {f"data/current/{name}" for name in current_names},
)
for name, digest in current_listed.items():
    path = REPO / name
    check(
        f"current artifact hash mismatch: {name}",
        path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest,
    )
if failures:
    print("PAPER INPUT CHECK FAILED (generators were not run):")
    for failure in failures:
        print(f"  - {failure}")
    sys.exit(1)

# All input byte checks have passed; it is now safe to parse current inputs.
release = json.loads((DATA / "current" / "spm-release.json").read_text())
content = {key: value for key, value in release.items() if key != "content_sha256"}
content_digest = hashlib.sha256(
    json.dumps(
        content,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
).hexdigest()
current_ce = json.loads(
    (DATA / "current" / "ce_replication_2019_2025.json").read_text()
)
current_provenance = json.loads((DATA / "current" / "provenance.json").read_text())
check(
    "release canonical content hash",
    release["content_sha256"]
    == content_digest
    == current_provenance["release_content_sha256"],
)
check(
    "current CE provenance hash",
    current_provenance["ce_artifact_sha256"]
    == current_listed["data/current/ce_replication_2019_2025.json"],
)
check(
    "current CE executed source fingerprints",
    current_provenance["ce_code_sha256"] == current_ce["code_sha256"],
)
check(
    "current inputs are outside frozen commitment",
    current_provenance["covered_by_original_timestamp"] is False
    and current_provenance["frozen_commitments_modified"] is False
    and current_ce["frozen_commitments_modified"] is False,
)
max_tenure_sensitivity = max(
    abs(value)
    for row in current_ce["results"].values()
    for value in row["sensitivity_change_percent_from_exclusion"][
        "include_5_6_as_renter_sensitivity"
    ].values()
)
check(
    "current tenure-sensitivity prose",
    has_number(f"{max_tenure_sensitivity:.2f} percent"),
)
if failures:
    print("PAPER INPUT CHECK FAILED (generators were not run):")
    for failure in failures:
        print(f"  - {failure}")
    sys.exit(1)

# (a) Generate only in scratch; never repair or restore source files.
present_before = {p.name for p in TABLES.glob("*.md")}
check(
    f"generated tables present == expected (missing {EXPECTED_TABLES - present_before}, extra {present_before - EXPECTED_TABLES})",
    present_before == EXPECTED_TABLES,
)
expected_outputs = {f"paper/tables/{name}" for name in EXPECTED_TABLES} | {
    "data/evaluation_2025.json"
}
with tempfile.TemporaryDirectory(prefix="spm-paper-check-") as tmp:
    scratch = Path(tmp)
    for script in GENERATORS:
        proc = subprocess.run(
            [
                sys.executable,
                str(REPO / "scripts" / script),
                "--output-root",
                str(scratch),
            ],
            capture_output=True,
            check=False,
            text=True,
            cwd=REPO,
        )
        if proc.returncode != 0:
            failures.append(f"{script} failed:\n{proc.stderr[-2000:]}")
    generated = {str(p.relative_to(scratch)) for p in scratch.rglob("*") if p.is_file()}
    check(
        f"generator output coverage: missing {expected_outputs - generated}, extra {generated - expected_outputs}",
        generated == expected_outputs,
    )
    for name in sorted(expected_outputs):
        original, regenerated = REPO / name, scratch / name
        check(
            f"generated output drifted: {name}",
            original.is_file()
            and regenerated.is_file()
            and original.read_bytes() == regenerated.read_bytes(),
        )

# (b) Every QMD include names an expected table.
includes = set(re.findall(r"\{\{<\s*include\s+tables/([^\s>]+)\s*>\}\}", QMD))
check(
    f"qmd includes outside allowlist: {includes - EXPECTED_TABLES}",
    includes <= EXPECTED_TABLES,
)
check(
    f"expected tables never included: {EXPECTED_TABLES - includes}",
    EXPECTED_TABLES <= includes,
)

# (d) Load-bearing prose figures re-derive from the artifacts.
nowcast = json.loads((DATA / "nowcast_2025.json").read_text())
AMENDED = {t: f"{nowcast['values'][t]:,.2f}" for t in TENURES}
for t, literal in AMENDED.items():
    check(f"nowcast literal {literal}", has_number(literal, min_count=2))
# Ordered tenure triples: abstract, amendment sentence, table caption order.
check(
    "abstract states the amended triple in tenure order",
    has_ordered(
        [
            AMENDED["owner_with_mortgage"],
            "owners with",
            AMENDED["owner_without_mortgage"],
            "owners without",
            AMENDED["renter"],
            "renters",
        ],
        window=120,
    ),
)
ORIGINAL = {
    "owner_with_mortgage": 41099.57,
    "owner_without_mortgage": 34250.70,
    "renter": 40791.72,
}
ORIG_LIT = {t: f"{v:,.2f}" for t, v in ORIGINAL.items()}
for t in TENURES:
    check(f"pre-amendment literal {ORIG_LIT[t]}", has_number(ORIG_LIT[t]))
check(
    "amendment sentence pairs original -> amended per tenure, in order",
    has_ordered(
        [
            ORIG_LIT["owner_with_mortgage"],
            AMENDED["owner_with_mortgage"],
            ORIG_LIT["owner_without_mortgage"],
            AMENDED["owner_without_mortgage"],
            ORIG_LIT["renter"],
            AMENDED["renter"],
        ],
        window=60,
    ),
)
shifts = [abs(nowcast["values"][t] / ORIGINAL[t] - 1) for t in TENURES]
check(
    "amendment size 0.1 to 0.3 percent",
    has_number("0.1 to 0.3") and 0.0005 <= min(shifts) and max(shifts) < 0.0035,
)

_prov = nowcast["method"] + " ".join(nowcast["caveats"])
check(
    "nowcast provenance strings repaired",
    "0.76" in nowcast["method"]
    and "0.41" in nowcast["method"]
    and "1.35" not in _prov
    and "biased low in 2022" not in _prov,
)

rate = json.loads((DATA / "nowcast_rate_impact.json").read_text())
delta_2025 = rate["2025"]["all"]["delta_pp"]
check(
    "poverty sensitivity 0.4pp",
    has_number("0.4 percentage points", min_count=1) and abs(delta_2025 - 0.4) < 0.05,
)

backtest = (TABLES / "backtest.md").read_text()
for literal in ("2.23%", "1.57%", "0.41%", "**0.76%**"):
    check(f"backtest table literal {literal}", literal in backtest)
for literal in ("2.23", "1.57", "0.41", "0.76"):
    check(f"backtest prose literal {literal}", has_number(literal))

# Recompute all four backtest rules (mirrors build_tables.py).
cpi = json.loads((DATA / "bls_cpi_series.json").read_text())
replication = json.loads((DATA / "replication_results.json").read_text())
series_doc = json.loads((DATA / "threshold_series.json").read_text())


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


def flat_measure(series_name: str, measure: str) -> dict[int, dict[str, float]]:
    entry = series_doc["series"][series_name]
    out: dict[int, dict[str, float]] = {}
    for seg in entry["segments"].values():
        for y, tenures in seg["years"].items():
            out[int(y)] = {t: m.get(measure) for t, m in tenures.items()}
    return out


corrected = flat("bls-corrected-2026-07-17")
published = flat("census-published-pre-correction")
legacy = flat("package-legacy-0.3")

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
            errs.append(corrected[year - 1][t] * factor / corrected[year][t] - 1)
        signed_by_rule.setdefault(rule, []).extend(errs)
        annual_signed.setdefault(rule, []).append(sum(errs) / 3)
        abs_by_rule.setdefault(rule, []).append(sum(abs(e) for e in errs) / 3)


def mae(rule: str) -> float:
    return sum(abs_by_rule[rule]) / len(abs_by_rule[rule])


signed_mean = sum(signed_by_rule["cpi_u"]) / len(signed_by_rule["cpi_u"])
check(
    "signed CPI-U bias -1.9",
    has_number("1.9 percent") and abs(signed_mean - (-0.019)) < 0.002,
)
cpiu_low_years = sum(1 for m in annual_signed["cpi_u"] if m < 0)
check(
    "CPI-U understated four of five years",
    "four of five" in QMD and cpiu_low_years == 4,
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
    has_number("+0.1") and abs(rep_signed - 0.001) < 0.001,
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

# Effective shelter weight under the pre-repair raw-level construction.
raw_2024 = {c: cpi[CPI_IDS[c]]["2024"] for c in WEIGHTS}
eff_shelter = (
    WEIGHTS["shelter"]
    * raw_2024["shelter"]
    / sum(WEIGHTS[c] * raw_2024[c] for c in WEIGHTS)
)
stated_shelter = WEIGHTS["shelter"] / sum(WEIGHTS.values())
check(
    "effective shelter weight ~55 vs stated 47",
    "near 55 percent" in QMD
    and "stated 47" in QMD
    and abs(eff_shelter - 0.55) < 0.02
    and abs(stated_shelter - 0.47) < 0.005,
)

# Correction and package-error magnitudes.
corr_changes = [
    corrected[y][t] / published[y][t] - 1 for y in range(2019, 2025) for t in TENURES
]
check(
    "correction within ±1.6 percent",
    has_number("1.6 percent") and max(abs(c) for c in corr_changes) < 0.016,
)
renter_falls = sum(
    1 for y in range(2019, 2025) if corrected[y]["renter"] < published[y]["renter"]
)
FALL_WORDS = {
    4: "fall in four of six years",
    5: "fall in five of six years",
    6: "fall in all six years",
}
check(
    f"renter thresholds {FALL_WORDS.get(renter_falls)} (computed {renter_falls})",
    FALL_WORDS.get(renter_falls, "") in QMD,
)
check(
    "reproducibility note cites the two miscounts the check found",
    "five of six\nyears, not four" in QMD or "five of six years, not four" in QMD,
)
pkg_err = {
    y: max(abs(legacy[y][t] / published[y][t] - 1) for t in TENURES)
    for y in range(2019, 2025)
}
check(
    "package errors reach 7.4 percent",
    has_number("7.4 percent") and abs(max(pkg_err.values()) - 0.074) < 0.001,
)
wrong_years = sum(1 for y, e in pkg_err.items() if e > 0.001)
WORDS = {
    3: "three of the six",
    4: "four of the six",
    5: "five of the six",
    6: "all six",
}
check(
    f"package wrong in {WORDS.get(wrong_years)} years (computed {wrong_years}; per-year max errors {{y: round(e, 4) for y, e in pkg_err.items()}})",
    WORDS.get(wrong_years, "") in QMD,
)
se = flat_measure("bls-corrected-2026-07-17", "standard_error")
se_ratio = [
    se[y][t] / corrected[y][t] for y in range(2019, 2025) for t in TENURES if se[y][t]
]
check(
    "SE range 0.7 to 2.1 percent",
    has_number("0.7")
    and has_number("2.1")
    and abs(min(se_ratio) - 0.007) < 0.001
    and abs(max(se_ratio) - 0.021) < 0.001,
)

# Replication level fidelity ranges.
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
    has_number("1.5 to 2.1")
    and abs(min(mad_corrected) - 0.015) < 0.001
    and abs(max(mad_corrected) - 0.021) < 0.001,
)
check(
    "replication fidelity 1.0 to 1.6 vs published",
    has_number("1.0 to 1.6")
    and abs(min(mad_published) - 0.010) < 0.001
    and abs(max(mad_published) - 0.016) < 0.001,
)

# Nowcast growth ranges.
rep_growth = [nowcast["components"][t]["replication_ratio"] - 1 for t in TENURES]
blend_growth = [nowcast["components"][t]["blend_ratio"] - 1 for t in TENURES]
price_growth = nowcast["components"]["renter"]["price_ratio"] - 1
check(
    "replication growth 4.4 to 6.0",
    has_number("4.4 to 6.0")
    and abs(min(rep_growth) - 0.044) < 0.001
    and abs(max(rep_growth) - 0.060) < 0.001,
)
check(
    "price growth 3.2", has_number("3.2 percent") and abs(price_growth - 0.032) < 0.001
)
check(
    "blend growth 3.8 to 4.6",
    has_number("3.8 to 4.6")
    and abs(min(blend_growth) - 0.038) < 0.001
    and abs(max(blend_growth) - 0.046) < 0.001,
)
realized_2025 = cpi["CUUR0000SA0"]["2025"] / cpi["CUUR0000SA0"]["2024"] - 1
check(
    "realized CPI-U 2025 growth 2.6",
    has_number("2.6 percent") and abs(realized_2025 - 0.026) < 0.002,
)
check(
    "eleven-month CPI-U growth 2.63 quoted",
    has_number("2.63") and abs(realized_2025 - 0.0263) < 0.0005,
)

# (e) The September evaluation, re-derived from data/evaluation_2025.json.
ev = json.loads((DATA / "evaluation_2025.json").read_text())
R = ev["rules"]
amended = R["Amended nowcast (50/50 blend, committed)"]
original = R["Original nowcast (pre-repair blend)"]
repl = R["CE replication growth ratio alone"]
comp = R["FCSUti-composite CPI aging alone"]
cpiu = R["All-Items CPI-U aging (status quo)"]
for label, value, literal in [
    ("evaluation amended MAE 1.17", amended["mae"], "1.17"),
    ("evaluation original MAE 0.98", original["mae"], "0.98"),
    ("evaluation replication MAE 0.75", repl["mae"], "0.75"),
    ("evaluation composite MAE 2.02", comp["mae"], "2.02"),
    ("evaluation CPI-U MAE 2.58", cpiu["mae"], "2.58"),
]:
    check(label, has_number(literal) and f"{value:.2%}".rstrip("%") == literal)
check(
    "evaluation per-tenure misses 0.69, 0.55, 2.27 in order",
    has_ordered(["0.69", "0.55", "2.27"], window=20)
    and abs(amended["errors"]["owner_with_mortgage"] - (-0.0069)) < 0.0001
    and abs(amended["errors"]["owner_without_mortgage"] - (-0.0055)) < 0.0001
    and abs(amended["errors"]["renter"] - (-0.0227)) < 0.0001,
)
ev_signed = sum(amended["errors"].values()) / 3
check(
    "evaluation signed mean −1.17 inside stated range",
    "−1.17" in QMD and -0.014 <= ev_signed <= -0.001,
)
cpiu_errs = [abs(v) for v in cpiu["errors"].values()]
check(
    "CPI-U 2025 understated every tenure by 1.70 to 3.48",
    has_number("1.70 to 3.48")
    and all(v < 0 for v in cpiu["errors"].values())
    and abs(min(cpiu_errs) - 0.0170) < 0.0001
    and abs(max(cpiu_errs) - 0.0348) < 0.0001,
)
check(
    "replication only rule with errors both sides of zero",
    max(repl["errors"].values()) > 0 > min(repl["errors"].values())
    and all(
        max(R[k]["errors"].values()) < 0
        for k in R
        if not k.startswith("CE replication")
    ),
)
actual = json.loads((DATA / "bls_2025_thresholds.json").read_text())
for literal, value in [
    ("41,323", actual["values"]["owner_with_mortgage"]),
    ("34,326", actual["values"]["owner_without_mortgage"]),
    ("41,701", actual["values"]["renter"]),
]:
    check(
        f"BLS 2025 literal {literal}",
        has_number(literal) and f"{round(value):,}" == literal,
    )
check(
    "BLS 2025 triple in tenure order",
    has_ordered(
        ["41,323", "owners with", "34,326", "owners without", "41,701", "renters"],
        window=80,
    ),
)
g = actual["bls_stated_growth_pct_2025_over_2024"]
check(
    "BLS-stated 2025 growth 4.40-6.33 and per-tenure 5.33/4.40/6.33",
    has_number("4.40 to 6.33")
    and has_number("6.33")
    and has_number("5.33")
    and has_number("4.40")
    and abs(min(g.values()) - 4.402) < 0.001
    and abs(max(g.values()) - 6.325) < 0.001
    and abs(g["owner_with_mortgage"] - 5.332) < 0.001,
)
now_growth_renter = (
    nowcast["values"]["renter"] / ev["corrected_2024_base"]["renter"] - 1
) * 100
check(
    "nowcast renter growth 3.92",
    has_number("3.92") and abs(now_growth_renter - 3.92) < 0.005,
)
check(
    "replication renter growth 4.62",
    has_number("4.62")
    and abs((nowcast["components"]["renter"]["replication_ratio"] - 1) * 100 - 4.62)
    < 0.005,
)
se25 = actual["standard_errors"]
miss_se = {t: (amended["values"][t] - actual["values"][t]) / se25[t] for t in TENURES}
check(
    "owner misses within one SE; renter about 2.4 SE",
    "2.4 standard errors" in QMD
    and abs(miss_se["owner_with_mortgage"]) < 1
    and abs(miss_se["owner_without_mortgage"]) < 1
    and abs(abs(miss_se["renter"]) - 2.4) < 0.05,
)
for literal, key in (
    ("327", "owner_with_mortgage"),
    ("560", "owner_without_mortgage"),
    ("393", "renter"),
):
    check(
        f"2025 SE literal {literal}",
        has_number(literal) and f"{round(se25[key])}" == literal,
    )
gaps = ev["composite_vs_bls_fcsuti_gap_pp"]
check(
    "composite within 0.7pp of BLS FCSUti, mean gap 0.4",
    "0.7 percentage point" in QMD
    and max(abs(v) for v in gaps.values()) < 0.7
    and "0.4 point" in QMD
    and abs(sum(abs(v) for v in gaps.values()) / len(gaps) - 0.4) < 0.05,
)
bls_cpiu_2025 = actual["bls_chart4_annual_average_inflation_pct"]["2025"]["cpi_u"]
check(
    "BLS page 2025 CPI-U growth 2.70 quoted",
    has_number("2.70 percent") and abs(bls_cpiu_2025 - 2.70) < 0.005,
)
census = json.loads((DATA / "census_wp2026_17_rates.json").read_text())
c23 = census["corrected_series_2023_to_2024"]["all_people"]
check(
    "Census corrected 2023->2024 = 12.7 -> 13.0",
    has_ordered(["12.7", "13.0"], window=10)
    and c23["2023"] == 12.7
    and c23["2024"] == 13.0,
)
diffs = [v["difference"] for y, v in census["all_people"].items() if y != "2024"]
check(
    "Census 2019-2023 corrected 0.1 to 0.3 below",
    has_number("0.1 to 0.3")
    and abs(max(diffs)) == 0.1
    and abs(min(diffs)) == 0.3
    and all(d < 0 for d in diffs),
)

if failures:
    print("PAPER DRIFT CHECK FAILED:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print(
    f"paper drift check passed ({len(EXPECTED_TABLES)} tables, {len(listed)} frozen + {len(current_listed)} current artifacts, prose pins OK)"
)

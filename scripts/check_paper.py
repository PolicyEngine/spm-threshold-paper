"""Pre-render guard: fail the build if the paper drifts from the data.

Wired into ``_quarto.yml`` as a pre-render step and run by CI on every
push to master and every pull request. It fails when:

(a) the committed tables differ from what the generators regenerate
    from the artifacts in ``data/`` — with an explicit allowlist of
    generated tables, so a missing or extra table also fails;
(b) any QMD ``{{< include tables/... >}}`` names a table outside that
    allowlist;
(c) ``data/SHA256SUMS`` does not list exactly the artifacts present in
    ``data/`` or any listed hash mismatches (an emptied manifest fails),
    or ``data/inkind`` fails ``inkind_inputs.load_inkind``: its own
    manifest, provenance, and the receipts' agreement with each other and
    with the out-of-pocket replication in ``data/current``; or a receipt
    differs from the SHA-256 and calculator commit that
    ``inkind_inputs.RECEIPT_PINS`` records outside ``data/inkind``;
(d) a figure quoted in the prose no longer matches the artifact it
    derives from. Literals are matched at numeric-token boundaries
    (so ``41,036.34`` does not match ``141,036.34``), spelled-out
    counts at word boundaries (so ``seven`` does not match inside
    ``sevens``), and the three tenure amounts are matched as ordered
    triples in the sentences that state them, so a swap between
    tenures fails. Figures that belong to one section — the
    conditional-forecast rates, the relative-index stabilization
    year, the area menus, the retrospective validation area count
    and the thin-donor support count — are pinned inside a
    whitespace-normalized slice of that section, so the same numeral
    occurring elsewhere in the paper cannot satisfy them and line
    rewrapping cannot split a multi-word literal. The guard reads each
    error rate the abstract quotes from the abstract alone, beside the
    rule it scores, so a copy in the body cannot rescue a drifted
    abstract figure and a swap between rules fails;
(e) the README miscounts the in-kind receipts or omits a calculator
    commit that their provenance records.

Scope, stated honestly: the guard covers artifact hashes, generated
tables, and the figures registered below. Numbers quoted from
external publications (P60 reports, BLS pages, Census working papers)
are bound to their citations, not to artifacts, and are the citation
referee's job; dates and ordinals are not registered. A 2026-09-04
reproducibility audit demonstrated the earlier substring-only version
passing under several of these attacks.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True
from rolling_inputs import (
    CALCULATOR_COMMIT,
    CONTENT_SHA256,
    ROLLING_FILES,
    load_rolling_forecast,
)
from verify_commitments import verify_commitments
from inkind_inputs import (
    BLS_IDENTITY_TOLERANCE_DOLLARS,
    INKIND_FILES,
    REPLICATES,
    YEARS,
    check_receipt_pins,
    inkind_figures,
    load_inkind,
    published_standard_errors,
    uncertainty_figures,
)

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
TABLES = REPO / "paper" / "tables"
FORECAST_RECORD = REPO / "docs" / "forecast-record.md"
QMD = (REPO / "paper" / "index.qmd").read_text()

TENURES = ("owner_with_mortgage", "owner_without_mortgage", "renter")

EXPECTED_TABLES = {
    "correction.md",
    "package_errors.md",
    "replication.md",
    "backtest.md",
    "nowcast.md",
    "evaluation.md",
    "evaluation_main.md",
    "evaluation_levels.md",
    "evaluation_levels_main.md",
    "composite_validation.md",
    "current_release.md",
    "current_replication.md",
    "current_sensitivity.md",
    "current_projection.md",
    "rolling_projection.md",
    "rolling_validation.md",
    "inkind_growth.md",
    "inkind_amounts.md",
    "inkind_levels.md",
}
ARCHIVED_TABLES = {
    "correction.md",
    "package_errors.md",
    "evaluation.md",
    "evaluation_levels.md",
}
ARTICLE_TABLES = EXPECTED_TABLES - ARCHIVED_TABLES
GENERATORS = (
    "build_tables.py",
    "evaluate_nowcast_2025.py",
    "build_current_tables.py",
    "build_inkind_tables.py",
)

failures: list[str] = []


def check(label: str, ok: bool) -> None:
    if not ok:
        failures.append(label)


def bounded(literal: str) -> str:
    """A literal that cannot match inside a longer token: numeric-token
    boundaries for figures, word boundaries for spelled-out counts."""
    pattern = re.escape(literal)
    if any(character.isdigit() for character in literal):
        return r"(?<![\d.,])" + pattern + r"(?![\d]|[.,]\d)"
    return r"\b" + pattern + r"\b"


def has_number(literal: str, text: str = QMD, min_count: int = 1) -> bool:
    """Literal present at numeric-token boundaries: no digit, comma-digit,
    or dot-digit continuation on either side."""
    return len(re.findall(bounded(literal), text)) >= min_count


def has_ordered(literals: list[str], window: int = 400, text: str = QMD) -> bool:
    """The literals appear in this order, each at a token boundary, within
    one window of text."""
    joiner = rf"[\s\S]{{0,{window}}}"
    return re.search(joiner.join(bounded(x) for x in literals), text) is not None


def section(start: str, end: str | None = None, text: str = QMD) -> str:
    """Whitespace-normalized prose between two headings that must each occur
    exactly once. A pin evaluated inside this slice cannot be satisfied by
    the same numeral elsewhere in the paper, and rewrapped lines cannot
    split a multi-word literal. A missing, duplicated or reordered heading
    yields an empty slice, so every pin inside it fails rather than
    silently widening to the whole document."""
    if text.count(start) != 1 or (end is not None and text.count(end) != 1):
        failures.append(f"paper section heading not unique: {start!r}")
        return ""
    first = text.index(start) + len(start)
    last = len(text) if end is None else text.index(end)
    if last <= first:
        failures.append(f"paper sections out of order: {start!r} before {end!r}")
        return ""
    return " ".join(text[first:last].split())


COUNT_WORDS = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
)


def count_word(value: int) -> str:
    """Small count as the paper spells it. A count outside that range yields
    a literal no prose can contain, so the pin fails instead of raising."""
    if 0 <= value < len(COUNT_WORDS):
        return COUNT_WORDS[value]
    return f"<unspelled count {value}>"


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
CURRENT_RETROSPECTIVE_MANIFEST_SHA256 = (
    "9bbba66e0a96fbb8b0524fa57a8e532c6401323db782042fc794e339824822cb"
)
check(
    "retrospective checksum manifest history changed",
    hashlib.sha256((DATA / "current" / "SHA256SUMS").read_bytes()).hexdigest()
    == CURRENT_RETROSPECTIVE_MANIFEST_SHA256,
)
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
rolling_paths = {f"data/current/{name}" for name in ROLLING_FILES}
check(
    "current checksum coverage",
    set(current_listed)
    == current_present - rolling_paths
    == {f"data/current/{name}" for name in current_names},
)
for name, digest in current_listed.items():
    path = REPO / name
    check(
        f"current artifact hash mismatch: {name}",
        path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest,
    )
try:
    rolling_forecast = load_rolling_forecast(DATA / "current")
except (OSError, KeyError, TypeError, ValueError) as error:
    failures.append(f"rolling input validation: {error}")
try:
    inkind_inputs = load_inkind(DATA / "inkind", DATA / "current")
    inkind = inkind_figures(inkind_inputs)
    inkind_se = uncertainty_figures(inkind_inputs, published_standard_errors(DATA))
    # Last, so a resealed edit that a consistency check catches fails with
    # that check's label; only edits that pass every one reach the pins.
    check_receipt_pins(DATA / "inkind")
except (OSError, KeyError, TypeError, ValueError, AttributeError, IndexError, ZeroDivisionError) as error:
    failures.append(f"in-kind input validation: {error!r}")
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
    f"qmd includes outside allowlist: {includes - ARTICLE_TABLES}",
    includes <= ARTICLE_TABLES,
)
check(
    f"article tables never included: {ARTICLE_TABLES - includes}",
    ARTICLE_TABLES <= includes,
)

# (d) Load-bearing prose figures re-derive from the artifacts.
nowcast = json.loads((DATA / "nowcast_2025.json").read_text())
AMENDED = {t: f"{nowcast['values'][t]:,.2f}" for t in TENURES}
check("forecast registration record exists", FORECAST_RECORD.is_file())
record_text = FORECAST_RECORD.read_text() if FORECAST_RECORD.is_file() else ""
SUPPORTING_COMMIT = "20bfbe1abcb83b4f9f60fbe54789144321ff62b0"
SUPPORTING_URL_BASE = (
    f"https://github.com/PolicyEngine/spm-threshold-paper/blob/{SUPPORTING_COMMIT}/"
)
FORECAST_RECORD_URL = SUPPORTING_URL_BASE + "docs/forecast-record.md"
for supporting_path in (
    "docs/forecast-record.md",
    "data/PROVENANCE.md",
    "docs/reproducing-experiments.md",
):
    pinned = subprocess.run(
        ["git", "show", f"{SUPPORTING_COMMIT}:{supporting_path}"],
        cwd=REPO,
        capture_output=True,
    )
    local_path = REPO / supporting_path
    check(
        f"pinned supporting document matches: {supporting_path}",
        pinned.returncode == 0
        and local_path.is_file()
        and pinned.stdout == local_path.read_bytes(),
    )
    check(
        f"manuscript links fixed supporting document: {supporting_path}",
        SUPPORTING_URL_BASE + supporting_path in QMD,
    )
check(
    "nowcast section links to the fixed forecast registration record",
    FORECAST_RECORD_URL in QMD.split("# Pre-committed 2025 validation", 1)[-1].split(
        "## Evaluation against published thresholds", 1
    )[0],
)
for t, literal in AMENDED.items():
    check(f"nowcast literal {literal}", has_number(literal))
# The committed estimate remains in the manuscript, in tenure order.
check(
    "committed estimate states the amended triple in tenure order",
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
    check(
        f"forecast record original literal {ORIG_LIT[t]}",
        has_number(ORIG_LIT[t], text=record_text),
    )
check(
    "forecast record pairs original -> amended per tenure, in order",
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
        text=record_text,
    ),
)
shifts = [abs(nowcast["values"][t] / ORIGINAL[t] - 1) for t in TENURES]
check(
    "forecast record size 0.1 to 0.3 percent",
    has_number("0.1 to 0.3", text=record_text)
    and 0.0005 <= min(shifts)
    and max(shifts) < 0.0035,
)
check(
    "forecast record preserves correction rationale and chronology",
    "different index bases" in record_text
    and "corrected the calculation before BLS" in record_text
    and "equal blend remained the primary forecast" in record_text,
)
check(
    "forecast record preserves timestamp qualification",
    "August 7, 2026 archived page" in record_text
    and "precede the August 24 publication" in record_text
    and "original timestamp does not cover that amendment" in record_text,
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
    "archived poverty sensitivity rounds to 0.4pp",
    abs(delta_2025 - 0.4) < 0.05,
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

# Archived correction and package tables remain byte-checked above.
# Their former audit claims are intentionally absent from this methods paper.
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

# Figures in the abstract also appear in the body or its tables, so their
# abstract ties read only the abstract, where a copy elsewhere cannot rescue a
# drifted figure. Each tie holds a figure beside the rule it scores, so a swap
# between rules fails too. Both markers must occur exactly once; otherwise the
# slice comes back empty and every abstract tie fails.
ABSTRACT = section("abstract: |", "# Introduction")

# Current retrospective results in the abstract are a separate experiment.
ABSTRACT_RETROSPECTIVE_RULES = {
    "cpi_u": "with the Consumer Price Index",
    "fcsuti_cpi": "with a composite price index",
    "replication_ratio": "with replicated consumption growth",
    "blend": "with an equal blend",
}
retrospective = current_ce["projection_evaluation"]["summary_2020_2025"]
check(
    "abstract names the retrospective rules and their count",
    set(retrospective) == set(ABSTRACT_RETROSPECTIVE_RULES)
    and has_number(
        f"compare {count_word(len(retrospective))} projection rules", text=ABSTRACT
    ),
)
for rule, value in retrospective.items():
    check(f"current projection prose {rule}", has_number(f"{value:.2f}"))
    rule_phrase = ABSTRACT_RETROSPECTIVE_RULES.get(rule, "<unnamed rule>")
    check(
        f"abstract current projection {rule} {value:.2f}",
        has_number(f"{value:.2f} percent {rule_phrase}", text=ABSTRACT),
    )

# (e) The September evaluation, re-derived from data/evaluation_2025.json.
ev = json.loads((DATA / "evaluation_2025.json").read_text())
R = ev["rules"]
amended = R["Amended nowcast (50/50 blend, committed)"]
original = R["Original nowcast (pre-repair blend)"]
repl = R["CE replication growth ratio alone"]
comp = R["FCSUti-composite CPI aging alone"]
cpiu = R["All-Items CPI-U aging (status quo)"]
# The abstract quotes three of these errors, and the body restates each.
for label, value, literal, abstract_phrase in [
    (
        "evaluation amended MAE 1.17",
        amended["mae"],
        "1.17",
        "blend yields a mean absolute error of {} percent",
    ),
    (
        "evaluation replication MAE 0.75",
        repl["mae"],
        "0.75",
        "{} percent for consumption growth alone",
    ),
    ("evaluation composite MAE 2.02", comp["mae"], "2.02", None),
    (
        "evaluation CPI-U MAE 2.58",
        cpiu["mae"],
        "2.58",
        "{} percent for CPI-U adjustment",
    ),
]:
    rounds_to_literal = f"{value:.2%}".rstrip("%") == literal
    check(label, has_number(literal) and rounds_to_literal)
    if abstract_phrase is not None:
        check(
            f"abstract {label}",
            rounds_to_literal
            and has_number(abstract_phrase.format(literal), text=ABSTRACT),
        )
check(
    "forecast record evaluation original MAE 0.98",
    has_number("0.98", text=record_text)
    and has_number("0.98")
    and f"{original['mae']:.2%}".rstrip("%") == "0.98",
)
check(
    "evaluation per-tenure misses 0.69, 0.55, 2.27 in order",
    has_ordered(["0.69", "0.55", "2.27"], window=20)
    and abs(amended["errors"]["owner_with_mortgage"] - (-0.0069)) < 0.0001
    and abs(amended["errors"]["owner_without_mortgage"] - (-0.0055)) < 0.0001
    and abs(amended["errors"]["renter"] - (-0.0227)) < 0.0001,
)
ev_signed = sum(amended["errors"].values()) / 3
check(
    "evaluation signed mean −1.17",
    "−1.17" in QMD and abs(ev_signed - (-0.0117)) < 0.00005,
)
cpiu_errs = [abs(v) for v in cpiu["errors"].values()]
cpiu_error_range = f"{min(cpiu_errs):.2%} to {max(cpiu_errs):.2%}".replace("%", "")
check(
    f"CPI-U 2025 understated every tenure by {cpiu_error_range} percent",
    has_number(f"{cpiu_error_range} percent")
    and all(v < 0 for v in cpiu["errors"].values()),
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

# (f) The conditional-forecast section, pinned inside its own two
# subsections so an occurrence of the same numeral anywhere else in the
# paper — a table column width, "seven target years", a hex digest — can
# never satisfy one of these figures.
ROLLING = section(
    "# Conditional forecasts beyond available microdata {#sec-rolling}",
    "# Discussion {#sec-discussion}",
)
ROLLING_CE = section(
    "## Projecting expenditure records and rolling windows",
    "## Projecting local relative housing costs",
    ROLLING,
)
ROLLING_ACS = section("## Projecting local relative housing costs", None, ROLLING)

REPRODUCIBILITY = section(
    "# Appendix B: reproducibility {.unnumbered}", "# References {.unnumbered}"
)
check(
    "rolling reproducibility identity matches the sealed calculator commit and content",
    has_ordered(
        [
            "projection uses the separate 1.0.0 release candidate at commit",
            f"`{CALCULATOR_COMMIT}`",
            "candidate's content digest is",
            CONTENT_SHA256,
        ],
        text=REPRODUCIBILITY,
    ),
)

fit = rolling_forecast["assumptions"]["real_growth_fit"]
SENSITIVITIES = fit["sensitivities"]
TEN_BLOCK = SENSITIVITIES["latest_ten_blocks"]
PANDEMIC_EXCLUDED = SENSITIVITIES["pandemic_excluded"]


def rate_literal(entry: dict, field: str = "shrunk_annual_rate") -> str:
    """Percent to three decimals, carrying the paper's typographic minus."""
    return f"{entry[field] * 100:.3f}".replace("-", "−")


def block_end_years(entry: dict) -> list[int]:
    return [block["end_year"] for block in entry["annual_blocks"]]


# The quoted rates are compounded equivalents exp(r) - 1 of the applied
# log rate r, which is itself the declared half-shrinkage of the OLS slope.
check(
    "quoted real-growth rates are exp(r) - 1 of the half-shrunk log slope",
    fit["shrinkage"] == 0.5
    and math.isclose(
        fit["applied_log_rate"], fit["log_slope"] * fit["shrinkage"], rel_tol=1e-12
    )
    and all(
        math.isclose(
            math.exp(entry["applied_log_rate"]) - 1,
            entry["shrunk_annual_rate"],
            rel_tol=1e-12,
        )
        for entry in (fit, TEN_BLOCK, PANDEMIC_EXCLUDED)
    ),
)
check(
    "CE-trend scenario applies the fitted rate and zero-real applies none",
    rolling_forecast["default_scenario"] == "ce_trend"
    and math.isclose(
        rolling_forecast["scenarios"]["ce_trend"]["real_growth_rate"],
        fit["shrunk_annual_rate"],
        rel_tol=1e-12,
    )
    and rolling_forecast["scenarios"]["zero_real"]["real_growth_rate"] == 0,
)
applied_rate = rate_literal(fit)
applied_log_rate = rate_literal(fit, "applied_log_rate")
check(
    f"rolling applied real-growth rate {applied_rate} stated as the compounded"
    f" equivalent of the applied log rate {applied_log_rate}",
    has_ordered(
        [
            "compounded annual equivalents",
            f"{applied_rate} percent",
            "applied log rate",
            f"{applied_log_rate} percent",
        ],
        window=140,
        text=ROLLING_CE,
    ),
)
fit_years = block_end_years(fit)
fit_window = f"{fit_years[0]}–{fit_years[-1]}" if len(fit_years) > 1 else "(no blocks)"
check(
    f"rolling fit uses {len(fit_years)} blocks ending {fit_window}",
    len(fit_years) > 1
    and fit_years == sorted(fit_years)
    and has_ordered(
        [f"{count_word(len(fit_years))} nonoverlapping", fit_window],
        window=60,
        text=ROLLING_CE,
    ),
)
check(
    f"rolling applied slope is the declared {fit['shrinkage']} shrinkage",
    has_ordered(
        ["half that estimate", str(fit["shrinkage"]), "shrinkage"],
        window=20,
        text=ROLLING_CE,
    ),
)
excluded_years = sorted(set(fit_years) - set(block_end_years(PANDEMIC_EXCLUDED)))
check(
    "rolling real-growth sensitivities in stated order with their block counts",
    len(excluded_years) == 2
    and has_ordered(
        [
            f"{applied_rate} percent",
            f"{count_word(len(block_end_years(TEN_BLOCK)))} annual",
            f"{rate_literal(TEN_BLOCK)} percent",
            f"{excluded_years[0]} and {excluded_years[1]}",
            f"{count_word(len(block_end_years(PANDEMIC_EXCLUDED)))} blocks",
            f"{rate_literal(PANDEMIC_EXCLUDED)} percent",
        ],
        window=140,
        text=ROLLING_CE,
    ),
)

# Geography: the published/modeled area menu, the retrospective validation
# area count, the stabilization year and the thin-donor support count.
menu_counts: dict[int, set[tuple[int, int]]] = {}
for scenario in rolling_forecast["scenarios"].values():
    for year, record in scenario["years"].items():
        statuses = Counter(
            area.get("anchor_status") for area in record["geography_by_area"].values()
        )
        menu_counts.setdefault(int(year), set()).add(
            (statuses["published_anchor"], statuses["modeled_unanchored"])
        )
menu_years = sorted(menu_counts)
opening_year = menu_years[0]
settled_year = menu_years[1] if len(menu_years) > 1 else opening_year
menu = {year: min(pairs) for year, pairs in menu_counts.items()}
check(
    f"area menus agree across scenarios and settle after {opening_year}",
    len(menu_years) > 1
    and all(len(pairs) == 1 for pairs in menu_counts.values())
    and sum(menu[opening_year]) == sum(menu[settled_year])
    and menu[opening_year] != menu[settled_year]
    and all(menu[year] == menu[settled_year] for year in menu_years[1:]),
)
check(
    f"rolling area menu prose states {menu[opening_year]} in {opening_year}"
    f" and {menu[settled_year]} from {settled_year}",
    has_ordered(
        [
            str(menu[opening_year][0]),
            "published",
            count_word(menu[opening_year][1]),
            "modeled",
            str(opening_year),
            str(menu[settled_year][0]),
            "published",
            count_word(menu[settled_year][1]),
            "modeled",
            str(settled_year),
        ],
        window=40,
        text=ROLLING_ACS,
    ),
)

acs_validation = rolling_forecast["validation"]["acs"]
check(
    f"rolling geographic validation covers {acs_validation['area_count']} anchored areas",
    acs_validation["status"] == "complete"
    and acs_validation["unvalidated"] is False
    and acs_validation["area_count"] == menu[settled_year][0]
    and has_ordered(
        [
            f"{acs_validation['origin_spm_year']}-origin",
            f"{acs_validation['target_spm_year']}-target",
            str(acs_validation["area_count"]),
            "areas",
        ],
        window=60,
        text=ROLLING_ACS,
    ),
)

projected_years = rolling_forecast["scenarios"][rolling_forecast["default_scenario"]][
    "years"
]
horizon = sorted(map(int, projected_years))
first_constant_index_year = next(
    (
        year
        for year in horizon[:-1]
        if all(
            projected_years[str(after)]["rent_indices"]
            == projected_years[str(year)]["rent_indices"]
            for after in horizon
            if after > year
        )
    ),
    None,
)
stabilization = rolling_forecast["assumptions"]["acs"]["relative_index_stabilization"]
check(
    f"relative rent indices first constant in {first_constant_index_year}",
    first_constant_index_year is not None
    and first_constant_index_year > horizon[0]
    and first_constant_index_year == stabilization["first_constant_index_year"]
    and projected_years[str(first_constant_index_year - 1)]["rent_indices"]
    != projected_years[str(first_constant_index_year)]["rent_indices"]
    and has_ordered(
        ["relative indices", "stabilize", str(first_constant_index_year)],
        window=80,
        text=ROLLING_ACS,
    ),
)

thin_counts = {
    sum(
        bool(area.get("thin_support")) for area in record["median_diagnostics"].values()
    )
    for scenario in rolling_forecast["scenarios"].values()
    for record in scenario["years"].values()
    if record["acs_window"]["projected_years"] > 0
}
check(
    f"thin-donor support is one constant count across projected windows: {sorted(thin_counts)}",
    len(thin_counts) == 1,
)
thin_areas = min(thin_counts, default=-1)
check(
    f"rolling thin-donor warnings cover {thin_areas} areas in projected years",
    thin_areas >= 0
    and has_ordered(
        [str(thin_areas), "areas", "thin-donor", "projected"],
        window=30,
        text=ROLLING_ACS,
    ),
)

# In-kind benefits: every figure the section, abstract, evaluation and
# discussion quote re-derives from data/inkind through inkind_figures, and
# each is pinned inside the section that states it.
INKIND_TEXT = section(
    "# Imputing in-kind benefits {#sec-inkind}", "# Projecting thresholds {#sec-projection}"
)
EVALUATION_TEXT = section(
    "## Evaluation against published thresholds {#sec-evaluation}",
    "## Validation of the price comparator",
)
DISCUSSION_TEXT = section("# Discussion {#sec-discussion}", "# Appendix A: replication benchmark")
REPLICATION_TEXT = section(
    "# Replication from public consumption data {#sec-replication}", "# Imputing in-kind benefits {#sec-inkind}"
)
UNCERTAINTY_TEXT = section(
    "## Uncertainty and limitations {#sec-inkind-uncertainty}", "# Projecting thresholds {#sec-projection}"
)
APPENDIX_B_TEXT = section("# Appendix B: reproducibility", "# References")
GROWTH_FIRST, GROWTH_LAST = inkind_se["growth_window"]
GROWTH_TEXT = section(
    f"## Threshold growth, {GROWTH_FIRST}–{GROWTH_LAST}", "## Uncertainty and limitations {#sec-inkind-uncertainty}"
)
README_TEXT = " ".join((REPO / "README.md").read_text().split())
inkind_method = json.loads((DATA / "inkind" / "ce_inkind_replication_2019_2025.json").read_text())[
    "in_kind_methodology"
]
inkind_provenance = json.loads((DATA / "inkind" / "provenance.json").read_text())


def signed(value: float, digits: int = 2) -> str:
    """A signed figure as the prose writes it, with a typographic minus."""
    return f"{value:+.{digits}f}".replace("-", "−")


def dollars(value: float) -> str:
    return f"\\${value:,.0f}"


package_run = inkind["runs"]["package"]
written_run = inkind["runs"]["package_bls_definition"]
written_index_run = inkind["runs"]["fcsuti_bls_definition"]
lift_low, lift_high = inkind["in_kind_lift_range"]
lift_literal = f"{lift_low:.1f} to {lift_high:.1f}"
gap_low, gap_high = package_run["gap_range"]["with_in_kind"]
written_without = written_run["gap_range"]["without_in_kind"]
written_with = written_run["gap_range"]["with_in_kind"]
internet_low, internet_high = inkind["bls_internet_range"]
bls_total = inkind["amounts"]["bls"]["imputed_total"]
our_total = inkind["amounts"]["package"]["imputed_total"]
rise_low, rise_high = inkind["imputed_total_rise_implicate_range"]
rise_gap = {
    name: inkind["pooled_rise"]["bls"][name] - inkind["pooled_rise"]["package"][name]
    for name in inkind["pooled_rise"]["bls"]
}
other_gap = sum(value for name, value in rise_gap.items() if name not in ("rental_assistance", "nslp"))
rent_growth = inkind["rental_assistance_per_renter_growth"]
our_rent_growth = sorted((rent_growth["package"], rent_growth["fcsuti"]))
bls_growth = [inkind["bls"][t]["growth"] for t in TENURES]
stage_changes = [package_run["growth"][t]["stage_change"] for t in TENURES]
deflator = list(inkind["deflator_points"].values())
written_index_gaps = [written_index_run["growth"][t]["less_bls"] for t in TENURES]
bls_shares = [inkind["bls"][t]["imputed_share_beyond_cpi_u"] for t in TENURES]
our_shares = [package_run["growth"][t]["imputed_share_beyond_cpi_u"] for t in TENURES]
renter = package_run["growth"]["renter"]
package_se = inkind_se["runs"]["package"]
level_ratios = package_se["level_ratio_range"]["without_in_kind"]
stage_ses = [package_se["stage_change"][t]["standard_error"] for t in TENURES]
stage_ratios = [
    run["stage_change"][t]["standard_errors_from_zero"] for run in inkind_se["runs"].values() for t in TENURES
]
implicate_shares = [
    run["stage_change"][t]["implicate_variance_share"] for run in inkind_se["runs"].values() for t in TENURES
]
recent = inkind["bls_2024_2025"]["renter"]
rent_2024, rent_2025 = inkind["bls_rental_assistance_per_renter_2024_2025"]

# The section displays the share formula. We evaluate the formula as
# printed against BLS's receipt, so a changed operator or subscript fails
# even when every quoted share stays put.
SHARE_FORMULA_SYMBOLS = {"I_{2022}": "i22", "I_{2025}": "i25", "B_{2022}": "b22", "B_{2025}": "b25", "\\pi": "pi"}


def evaluate_formula(node: ast.AST, names: dict[str, float]) -> float:
    """Arithmetic over the formula's symbols, and nothing else."""
    if isinstance(node, ast.Expression):
        return evaluate_formula(node.body, names)
    if isinstance(node, ast.Name) and node.id in names:
        return names[node.id]
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -evaluate_formula(node.operand, names)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
        left, right = evaluate_formula(node.left, names), evaluate_formula(node.right, names)
        return {ast.Add: left + right, ast.Sub: left - right, ast.Mult: left * right}.get(
            type(node.op), left / right if right else math.nan
        )
    raise ValueError(f"unexpected term in the share formula: {ast.dump(node)}")


def displayed_shares() -> list[float] | None:
    """BLS's imputed shares beyond CPI-U, in percent, from the formula the
    section prints."""
    match = re.search(r"We compute each share as \$([^$]+)\$", INKIND_TEXT)
    if match is None:
        return None
    expression = match.group(1)
    for symbol, name in SHARE_FORMULA_SYMBOLS.items():
        expression = expression.replace(symbol, f" {name} ")
    expression = re.sub(r"\b(pi)\s+(\w)", r"\1*\2", expression)
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        return None
    components = inkind_inputs["components"]
    bls_years = components["bls"]["years"]
    shares = []
    for tenure in TENURES:
        dollars_by_year = components["bls"]["growth_2022_2025"]["by_tenure"][tenure]["imputed_term_dollars"]
        names = {
            "i22": dollars_by_year["2022"],
            "i25": dollars_by_year["2025"],
            "b22": bls_years["2022"]["published_thresholds"][tenure],
            "b25": bls_years["2025"]["published_thresholds"][tenure],
            "pi": components["inputs"]["cpi"]["cpi_u_ratio_2022_2025"],
        }
        try:
            shares.append(100 * evaluate_formula(tree, names))
        except ValueError:
            return None
    return shares


# Method constants the section quotes from the calculator's code rather
# than from a receipt. We read each from spm_calculator/ce_inkind.py at
# this fingerprint (calculator commit 4778dfa); a receipt rebuilt from
# changed code fails the pin until someone rereads them.
INKIND_METHOD_SOURCE = (
    "spm_calculator/ce_inkind.py",
    "c23e6f26ef32328ef0952d90edca9b382e7fa6e5e029d530a7a0beb9e1d10724",
)
INKIND_METHOD_CONSTANTS = (
    "over 179 school days",  # NSLP_SCHOOL_DAYS
    "free rate below 150 percent of the poverty line",  # FREE_LUNCH_POVERTY_RATIO
    "split the income groups at 150 percent of the official poverty line",  # the same ratio, for cells
    "twelve months of USDA's national average monthly food cost",  # 12.0 * cost in the WIC stage
    "includes a woman aged 15 or older",  # n_women_15_plus in _wic_participants
    "midpoint of its three-month reference period",  # 1.5 months in _wic_ebt_complete
    "twelve times the difference",  # 12.0 * benefit in the rental stage
)
replication_receipt = json.loads((DATA / "inkind" / "ce_inkind_replication_2019_2025.json").read_text())


def previous_quarter(quarter: str) -> str:
    year, number = int(quarter[:4]), int(quarter[-1])
    return f"{year - 1}Q4" if number == 1 else f"{year}Q{number - 1}"


# Each quarter in which most paired units' blank replicate weights change,
# with the quarter before it, and the thresholds whose 20-quarter windows
# hold both quarters of at least one such pair.
half_sample_pairs = [(previous_quarter(q), q) for q in sorted(inkind_se["half_sample_changes"])]
half_sample_years = sorted(
    int(year)
    for year, row in current_ce["results"].items()
    if any(before in row["quarters"] and after in row["quarters"] for before, after in half_sample_pairs)
)
inkind_pins = (
    ("in-kind lift range", has_number(lift_literal, text=INKIND_TEXT)),
    ("abstract in-kind lift range", has_number(lift_literal, text=ABSTRACT)),
    ("discussion in-kind lift range", has_number(lift_literal, text=DISCUSSION_TEXT)),
    (
        "replication with benefits exceeds BLS in every cell",
        package_run["cells_above_bls_with_stage"] == len(YEARS) * len(TENURES)
        and gap_low > 0
        and has_number(
            f"thresholds that exceed BLS's for every tenure in every year, by {gap_low:.2f} to "
            f"{gap_high:.2f} percent",
            text=INKIND_TEXT,
        ),
    ),
    (
        "BLS home internet range",
        has_number(f"{dollars(internet_low)} to {dollars(internet_high)} per unit", text=INKIND_TEXT),
    ),
    (
        "written-definition out-of-pocket range",
        written_without[1] < 0
        and has_number(f"trails BLS by {-written_without[1]:.2f} to {-written_without[0]:.2f}", text=INKIND_TEXT),
    ),
    (
        "written-definition range with benefits",
        written_with[0] < 0 < written_with[1]
        and has_number(
            f"{-written_with[0]:.2f} percent below and {written_with[1]:.2f} percent above", text=INKIND_TEXT
        ),
    ),
    (
        "written-definition mean absolute deviation",
        written_run["mean_absolute_gap"]["with_in_kind"] < written_run["mean_absolute_gap"]["without_in_kind"]
        and has_number(
            f"mean absolute deviation falls from {written_run['mean_absolute_gap']['without_in_kind']:.2f} to "
            f"{written_run['mean_absolute_gap']['with_in_kind']:.2f} percent",
            text=INKIND_TEXT,
        ),
    ),
    (
        "BLS and replication imputed totals",
        has_ordered(
            [f"{dollars(bls_total[0])} to {dollars(bls_total[1])}", f"{dollars(our_total[0])} to {dollars(our_total[1])}"],
            window=120,
            text=INKIND_TEXT,
        )
        and bls_total[2] > rise_high
        and has_number("BLS's rise exceeds the rise in each of our implicates", text=INKIND_TEXT),
    ),
    ("implicate rise range", has_number(f"{dollars(rise_low)} to {dollars(rise_high)}", text=INKIND_TEXT)),
    (
        "difference in rises by benefit",
        rise_gap["rental_assistance"] > rise_gap["nslp"] > 0 > other_gap
        and has_ordered(
            [dollars(rise_gap["rental_assistance"]), dollars(rise_gap["nslp"]), dollars(-other_gap)],
            window=120,
            text=INKIND_TEXT,
        ),
    ),
    (
        "rental assistance per renter growth",
        has_number(
            f"rose {rent_growth['bls']:.0f} percent in BLS's band and {our_rent_growth[0]:.0f} to "
            f"{our_rent_growth[1]:.0f} percent in ours",
            text=INKIND_TEXT,
        ),
    ),
    (
        "price and BLS threshold growth",
        has_ordered(
            [
                f"{inkind['cpi_u_growth']:.2f} percent",
                f"{inkind['fcsuti_price_growth']:.2f} percent",
                f"{min(bls_growth):.2f} to {max(bls_growth):.2f}",
            ],
            window=120,
            text=INKIND_TEXT,
        ),
    ),
    (
        "stage changes in tenure order, each within one standard error",
        has_ordered(
            [
                f"{signed(stage_changes[0])} points for owners with mortgages",
                f"{signed(stage_changes[1])} for owners without mortgages",
                f"{signed(stage_changes[2])} for renters",
                "each within one standard error of zero",
            ],
            window=40,
            text=GROWTH_TEXT,
        )
        and all(
            package_se["stage_change"][t]["standard_errors_from_zero"] < 1 for t in TENURES
        ),
    ),
    (
        "replication standard errors relative to BLS's, by tenure",
        has_number(
            f"They run {level_ratios[TENURES[0]][0]:.2f} to {level_ratios[TENURES[0]][1]:.2f} times "
            f"BLS's published ones for owners with mortgages, {level_ratios[TENURES[1]][0]:.2f} to "
            f"{level_ratios[TENURES[1]][1]:.2f} times for owners without mortgages, and "
            f"{level_ratios[TENURES[2]][0]:.2f} to {level_ratios[TENURES[2]][1]:.2f} times for renters",
            text=REPLICATION_TEXT,
        ),
    ),
    (
        "standard errors of the stage change",
        has_number(f"the CE's {REPLICATES} replicate weights", text=UNCERTAINTY_TEXT)
        and has_number(
            f"For the benefits' change to {GROWTH_FIRST}–{GROWTH_LAST} growth, we estimate standard errors of "
            f"{stage_ses[0]:.2f} points for owners with mortgages, "
            f"{stage_ses[1]:.2f} for owners without mortgages, and {stage_ses[2]:.2f} for renters",
            text=UNCERTAINTY_TEXT,
        ),
    ),
    (
        "every stage change within three-quarters of a standard error",
        0.5 < max(stage_ratios) < 0.75
        and has_number(
            "Under either price index, every change lies within three-quarters of a standard error of zero",
            text=UNCERTAINTY_TEXT,
        ),
    ),
    (
        "implicate share of the stage change's variance",
        has_number(
            f"{100 * min(implicate_shares):.0f} to {100 * max(implicate_shares):.0f} percent of each change's variance",
            text=UNCERTAINTY_TEXT,
        ),
    ),
    (
        "half-sample pattern changes",
        bool(half_sample_years)
        and half_sample_years == list(range(half_sample_years[0], half_sample_years[-1] + 1))
        and all(share < 0.5 for share in inkind_se["half_sample_changes"].values())
        and re.findall(r"\b(\d{4}Q[1-4]) and (\d{4}Q[1-4])\b", UNCERTAINTY_TEXT) == half_sample_pairs
        and has_ordered(
            ["For most units"]
            + [f"{before} and {after}" for before, after in half_sample_pairs]
            + [f"Replicates for the {half_sample_years[0]}–{half_sample_years[-1]} thresholds"],
            window=200,
            text=UNCERTAINTY_TEXT,
        ),
    ),
    (
        "discussion stage-change range",
        has_number(f"{signed(min(stage_changes))} to {signed(max(stage_changes))} points", text=DISCUSSION_TEXT),
    ),
    (
        "BLS's imputed benefits rise faster than ours",
        bls_total[2] > our_total[2]
        and has_number("while BLS's imputed benefits rise faster than ours", text=DISCUSSION_TEXT)
        and "BLS's imputed benefits grow faster than ours over those years" in ABSTRACT,
    ),
    (
        "deflator effect exceeds the stage in every tenure",
        has_number(
            f"growth rises by {min(deflator):.1f} to {max(deflator):.1f} points, more in every tenure than "
            "the benefits move it",
            text=INKIND_TEXT,
        )
        and all(d > abs(c) for d, c in zip(deflator, stage_changes)),
    ),
    (
        "written definitions with BLS's index come within 0.8 points",
        max(abs(g) for g in written_index_gaps) < 0.8 and has_number("within 0.8 points", text=INKIND_TEXT),
    ),
    (
        "imputed shares of growth beyond CPI-U",
        has_ordered(
            [
                f"{bls_shares[0]:.1f} percent of BLS's threshold growth beyond CPI-U for owners with "
                f"mortgages, against {our_shares[0]:.1f} percent of ours",
                f"{bls_shares[1]:.1f} against {our_shares[1]:.1f} percent for owners without mortgages",
                f"{bls_shares[2]:.1f} against {our_shares[2]:.1f} percent for renters",
            ],
            window=40,
            text=INKIND_TEXT,
        ),
    ),
    (
        "displayed share formula reproduces BLS's shares",
        (shares := displayed_shares()) is not None
        and all(math.isclose(a, b, rel_tol=1e-9) for a, b in zip(shares, bls_shares, strict=True)),
    ),
    (
        "renter shortfall with imputed terms removed",
        has_number(
            f"renter shortfall narrows from {-renter['less_bls']:.2f} to "
            f"{-renter['less_bls_without_imputed_terms']:.2f} points",
            text=INKIND_TEXT,
        )
        and renter["less_bls"] < renter["less_bls_without_imputed_terms"] < 0,
    ),
    (
        "BLS 2024-2025 renter split",
        has_ordered(
            [f"{recent['imputed_points']:.2f}", f"{recent['growth']:.2f}", f"{recent['rental_assistance_points']:.2f}"],
            window=120,
            text=INKIND_TEXT,
        )
        and has_number(f"{dollars(rent_2024)} to {dollars(rent_2025)}", text=INKIND_TEXT),
    ),
    (
        "replication 2024-2025 renter growth with and without benefits",
        has_ordered(
            [f"{recent['replication_with_stage']:.2f} percent", f"{recent['replication_without_stage']:.2f} percent"],
            window=60,
            text=INKIND_TEXT,
        ),
    ),
    (
        "evaluation section cites BLS's imputed renter points and our change",
        has_number(f"{recent['imputed_points']:.2f} points", text=EVALUATION_TEXT)
        and has_number(
            f"{signed(recent['replication_with_stage'] - recent['replication_without_stage'])} points",
            text=EVALUATION_TEXT,
        ),
    ),
    (
        "abstract stage changes under one point per tenure",
        max(abs(change) for change in stage_changes) < 1
        and "growth by less than one point per tenure" in ABSTRACT,
    ),
    (
        "abstract rental assistance share of the difference",
        abs(rise_gap["rental_assistance"] / sum(rise_gap.values()) - 2 / 3) < 0.05
        and "rental assistance accounts for about two-thirds of the difference" in ABSTRACT,
    ),
    (
        "BLS identity tolerance",
        has_number(
            f"within \\${BLS_IDENTITY_TOLERANCE_DOLLARS:.5f} in every year from {YEARS[0]} to {YEARS[-1]}",
            text=INKIND_TEXT,
        ),
    ),
    (
        "evaluation section's BLS growth rates for 2024-2025",
        has_ordered(
            [
                f"renter growth of {inkind['bls_2024_2025']['renter']['growth']:.2f} percent",
                f"{inkind['bls_2024_2025'][TENURES[0]]['growth']:.2f}",
                f"{inkind['bls_2024_2025'][TENURES[1]]['growth']:.2f} percent",
            ],
            window=80,
            text=EVALUATION_TEXT,
        ),
    ),
    (
        "implicate, matching-neighbor and cell-donor counts",
        has_number(f"We draw {count_word(inkind_method['implicates'])} implicates", text=INKIND_TEXT)
        and has_number(f"one of the {count_word(inkind_method['pmm_neighbors'])} recipients", text=INKIND_TEXT)
        and has_number(f"fewer than {count_word(inkind_method['min_cell_donors'])} donors", text=INKIND_TEXT)
        and inkind_method["parameter_draws"] is True,
    ),
    (
        "method constants read from fingerprinted calculator code",
        replication_receipt["code_sha256"].get(INKIND_METHOD_SOURCE[0]) == INKIND_METHOD_SOURCE[1]
        and all(has_number(constant, text=INKIND_TEXT) for constant in INKIND_METHOD_CONSTANTS),
    ),
    (
        "appendix names the recorded calculator commits",
        all(
            f"`{record['calculator_commit']}`" in APPENDIX_B_TEXT
            for record in inkind_provenance["artifacts"].values()
        ),
    ),
    (
        "appendix counts the receipts",
        has_number(
            f"we keep {count_word(len(inkind_provenance['artifacts']))} receipts from spm-calculator",
            text=APPENDIX_B_TEXT,
        ),
    ),
    (
        "README counts the receipts and names the commits",
        has_number(
            f"uses {count_word(len(inkind_provenance['artifacts']))} receipts from spm-calculator",
            text=README_TEXT,
        )
        and all(
            f"`{record['calculator_commit']}`" in README_TEXT
            for record in inkind_provenance["artifacts"].values()
        ),
    ),
)
for label, ok in inkind_pins:
    check(f"in-kind prose: {label}", ok)

if failures:
    print("PAPER DRIFT CHECK FAILED:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print(
    f"paper drift check passed ({len(EXPECTED_TABLES)} tables, {len(listed)} frozen + {len(current_listed)} retrospective + {len(ROLLING_FILES)} rolling + {len(INKIND_FILES)} in-kind artifacts, prose pins OK)"
)

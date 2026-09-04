# Nowcasting Supplemental Poverty Measure thresholds

Working paper. Quantifies the July 17, 2026 BLS threshold correction,
documents a replication of the BLS threshold methodology from public CE
microdata, backtests threshold-projection rules, and commits to a
pre-registered nowcast of the unpublished 2025 thresholds — graded
against BLS's actual publication (~September 2026) in a planned
revision.

## Build

```bash
quarto render   # runs scripts/check_paper.py pre-render, then HTML + PDF to _output/
```

The pre-render check (`scripts/check_paper.py`) regenerates every
table from `data/`, enforces allowlists of generated tables, QMD
includes, and checksummed artifacts, verifies `data/SHA256SUMS`, and
re-derives the registered prose figures at numeric-token boundaries;
the render fails if any registered figure, table, or artifact drifts.
Figures quoted from external publications are bound to citations,
not artifacts. `data/PROVENANCE.md` names the generator, inputs, and
source of every artifact.

## Clean-room build

Tested on 2026-09-04 with Python 3.14.6, Quarto 1.9.36, and TeX Live
2026 (LuaHBTeX). The check and the table generators use only the
Python standard library and need a writable checkout.

```bash
git clone https://github.com/PolicyEngine/spm-threshold-paper.git
cd spm-threshold-paper
git checkout <full commit SHA of the revision you are checking>
python3 scripts/check_paper.py      # guard only; no Quarto needed
quarto render --to html             # HTML; add --to pdf for the PDF (needs TeX)
```

Rendered output lands in `_output/paper/`. The published site is a
static deploy of that directory.

## Pre-commitment evidence

- `data/SHA256SUMS.precommit` — the artifact manifest as of 2026-08-07,
  before BLS published the 2025 thresholds; `SHA256SUMS.precommit.ots`
  is its completed OpenTimestamps proof (Bitcoin block 961505, mined
  2026-08-07 23:18 UTC). Verify with
  `ots verify -f data/SHA256SUMS.precommit data/SHA256SUMS.precommit.ots`.
- `data/COMMITMENT-MANIFEST.txt` — both nowcast vintages (tags
  `v1.0-original-nowcast`, `v1.1-amended-nowcast`), their commits and
  artifact hashes; stamped as `COMMITMENT-MANIFEST.txt.ots`.
- Internet Archive capture of the page, 2026-08-07:
  <https://web.archive.org/web/20260807211521/https://spm-threshold-paper.vercel.app/>

## Companion code

- spm-calculator PR #32 (0.4.0 on merge): corrected/published/legacy threshold series
  with provenance, CE replication, benchmark, backtest, nowcast, and
  the weekly BLS drift-watch workflow.
- policyengine-us #9081: adopts the corrected series in the US
  microsimulation model.

# Nowcasting Supplemental Poverty Measure thresholds

Working paper. Quantifies the July 17, 2026 BLS threshold correction,
documents a replication of the BLS threshold methodology from public CE
microdata, backtests threshold-projection rules, and commits to a
pre-registered nowcast of the unpublished 2025 thresholds — graded
against BLS's actual publication (~September 2026) in a planned
revision.

## Build

```bash
uv run python scripts/build_tables.py   # regenerate tables from data/
quarto render paper/index.qmd           # HTML + PDF to _output/
```

Every numeric table is generated from the artifacts in `data/`
(SHA-256 sums in `data/SHA256SUMS`), which are produced by the scripts
in [PolicyEngine/spm-calculator](https://github.com/PolicyEngine/spm-calculator)
(v0.4.0, PR #32). The prose cannot drift from the data without the
build failing.

## Companion code

- spm-calculator 0.4.0: corrected/published/legacy threshold series
  with provenance, CE replication, benchmark, backtest, nowcast, and
  the weekly BLS drift-watch workflow.
- policyengine-us #9081: adopts the corrected series in the US
  microsimulation model.

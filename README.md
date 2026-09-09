# Calculating and projecting Supplemental Poverty Measure thresholds

Working paper on national SPM threshold estimation from public Consumer
Expenditure Survey microdata, family and geographic adjustments, and
projection from consumption and price growth. The manuscript presents
current-method replication and sample sensitivities, retrospective
comparisons, and a separately preserved pre-committed 2025 validation.
It also constructs conditional forecasts through 2035 by advancing the
CE and ACS windows with explicit price, real-spending, and rent assumptions.

The current six-year results use revised inputs and overlapping CE
windows. They are separate from the single prospective validation year.
Method limitations and the forecast amendment history are reported in
the manuscript. The repository preserves source artifacts, method
versions, and forecast commitment evidence.

## Build and verify

```bash
python3 -B scripts/check_paper.py
python3 -B -m unittest discover -s tests -v
quarto render --to html
quarto render --to pdf
```

The guard and table generators use the Python standard library. Quarto
1.9.36 and TeX Live 2026 render the HTML and PDF to `_output/paper/`.
Clone with full tag history and check out the exact revision to reproduce
it. The guard first checks artifact hashes and frozen Git identities,
then generates tables and evaluation JSON in temporary storage and
compares every output byte with the checkout, including archived tables
that the manuscript no longer includes. It never repairs or
restores source artifacts. The regression tests verify that failed checks
leave source bytes unchanged.

## Preserved forecast evidence

The tags `v1.0-original-nowcast` and `v1.1-amended-nowcast`, forecast
bytes, and all original OpenTimestamps manifest/proof pairs are preserved.
Two hashes in `data/COMMITMENT-MANIFEST.txt` were incorrect; the dated
`data/COMMITMENT-AMENDMENT-2026-09-08.txt` records the exact tag hashes and
the original manifest digest. The original proof does not cover that
amendment. This revision verifies retained proof bytes and Git identities;
it does not independently reverify blockchain attestations.

`data/SHA256SUMS` continues to cover only the frozen artifacts. New inputs
have their own `data/current/SHA256SUMS`; they do not replace the frozen
forecast or become a new prospective commitment. `data/PROVENANCE.md`
describes both collections and the original implementation pin.

## Companion implementation

The companion spm-calculator provides a portable artifact, standalone
unit calculations, CE research replication, rolling projections, and
PolicyEngine, Microcosm, and native Axiom adapters. The rolling projection
pins the 1.0.0 release candidate at commit
`78bae15f76152c6076dd909a09f6b63dc2ec8c34`, with content digest
`3d86d5c4c0423480e6b69b75d222ffa4a7a2639e4094df5ba2504af01be17173`.
The paper consumes the same projection bytes as the calculator.

The 2019–2025 retrospective experiment retains its separate development
version 0.5.0 pin at `0d7fa0d77b0a88064ab7b9fe70557309b5f7901f`.
These source identities document reproducibility; they do not certify
publication, deployment, or a population-model migration.

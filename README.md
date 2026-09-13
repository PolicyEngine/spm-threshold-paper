# Calculating and projecting Supplemental Poverty Measure thresholds

[Read the paper](https://spm-threshold-paper.vercel.app/) ·
[Download the PDF](https://spm-threshold-paper.vercel.app/index.pdf) ·
[Manuscript source](paper/index.qmd)

The Bureau of Labor Statistics calculates Supplemental Poverty Measure (SPM)
thresholds from spending on basic needs. The U.S. Census Bureau adjusts them
for family composition and local housing costs. We reconstruct national
thresholds from public Consumer Expenditure (CE) Survey data and compare four
projection rules. We evaluate retrospective projections and a pre-committed
2025 nowcast, then project thresholds through 2035 by advancing the CE and
American Community Survey (ACS) windows. We specify prices, real spending,
and rents for the future scenarios and evaluate prospective accuracy for
2025 only.

## Build and verify

```bash
python3 -B scripts/check_paper.py
python3 -B -m unittest discover -s tests -v
quarto render --to html
quarto render --to pdf
```

The guard and table generators use the Python standard library. Quarto
1.9.36 and TeX Live 2026 render the HTML and PDF to `_output/paper/`.
Clone with full tag history and check out the desired source commit.
The guard checks input hashes and forecast registrations, generates tables
and evaluation JSON in temporary storage, and compares outputs with the
recorded files. The tests check that input corruption fails verification
without changing source bytes.

The [experiment replay guide](docs/reproducing-experiments.md) supplies
commands, source links, and input requirements for the CE and ACS estimators.
The [data provenance](data/PROVENANCE.md) identifies each experimental
collection. The [forecast record](docs/forecast-record.md) provides the
registration evidence and supporting evaluations. These files distinguish
table verification from replication of the underlying survey estimates.

## Companion calculator

[SPM Calculator](https://github.com/PolicyEngine/spm-calculator) provides
standalone unit calculations, CE replication, rolling forecasts, and adapters
for PolicyEngine, Microcosm, and the Axiom rules engine. The paper and calculator
consume the same rolling projection artifact: version 1.0.0 release candidate
at commit `78bae15f76152c6076dd909a09f6b63dc2ec8c34`, with content digest
`3d86d5c4c0423480e6b69b75d222ffa4a7a2639e4094df5ba2504af01be17173`.

The 2019–2025 retrospective experiment uses a separate implementation:
version 0.5.0 at commit
`0d7fa0d77b0a88064ab7b9fe70557309b5f7901f`.

## Separate 2025 poverty-rate prediction

The [September 11 prediction](data/predictions/2025-spm-poverty-rates-2026-09-11.json)
predicts a 2025 SPM poverty rate of 13.2 percent overall, 14.3 percent
for children, and 14.6 percent for people 65 and over. The registration
precedes the Census release scheduled for September 15, 2026. It adds
the modeled 2024-to-2025 change to Census's
2024 rate. These development estimates remain provisional pending a
comparison on the qualified model and population release. The threshold-method
results do not depend on them. The prediction's checksum and timestamp proof
accompany the file; any subsequent estimate receives its own dated record.

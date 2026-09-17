# Grading the 2025 SPM poverty prediction

PolicyEngine registered a prediction of 2025 Supplemental Poverty Measure (SPM) poverty rates on September 11, 2026
([`data/predictions/2025-spm-poverty-rates-2026-09-11.json`](../../data/predictions/2025-spm-poverty-rates-2026-09-11.json)).
The Census Bureau published the rates on September 15 in
[*Poverty in the United States: 2025*](https://www.census.gov/library/publications/2026/demo/p60-290.html) (P60-290).
The grade is in
[`data/predictions/2025-spm-poverty-rates-2026-09-11.grade-2026-09-17.json`](../../data/predictions/2025-spm-poverty-rates-2026-09-11.grade-2026-09-17.json).
This directory holds the code and results that take the misses apart.

## The grade

Changes from 2024 to 2025, in percentage points. Printed changes are from
[Table 4](https://www2.census.gov/programs-surveys/demo/tables/p60/290/table_4_spm_person.xlsx); changes to two
decimals are from
[Table 5](https://www2.census.gov/programs-surveys/demo/tables/p60/290/table_5_spm_program_effect_rates.xlsx).

| Group | Registered change | Census, printed | Census, two decimals | Miss, two decimals |
| --- | ---: | ---: | ---: | ---: |
| All people | +0.22 | +0.1 | +0.07 | +0.15 |
| Under 18 | +0.86 | −0.1 | −0.06 | +0.92 |
| 65 and over | −0.52 | +0.2 | +0.24 | −0.76 |

Table 4 marks none of the three Census changes as statistically different from zero at the 90 percent level.

The registered file promised a dated amendment if a rerun on the shipping runtime moved any modeled change by 0.05
points or more. The rerun (policyengine-us 2.2.1, policyengine-core 3.32.5, spm-calculator 1.0.0, the same population
file) reproduces all three changes to within 0.000001 points. No amendment is required.

## Threshold effect and resource effect

`decompose.py` splits each change in two:

- **threshold effect**: the 2025 rate minus the 2025 rate with thresholds held at their 2024 values plus CPI-U
  (2.63 percent, the growth of the official-measure threshold in P60-290 Table 10)
- **resource effect**: that constant-real-threshold 2025 rate minus the 2024 rate

On the model side, `run_decomp.py` runs the population three times: 2024, 2025, and 2025 with a reform that replaces
`spm_unit_spm_threshold` by the same variable scaled by housing tenure, so that the national two-adult-two-child
threshold equals the corrected 2024 BLS value times 32,649/31,812. On the Census side, the constant-real-threshold
2025 rate is the recomputation on the 2026 CPS ASEC public-use file in
[`analysis/asec-2026-anchored-thresholds`](../asec-2026-anchored-thresholds), which applies the same scaling.

| Group | Model change | = threshold | + resources | Census change | = threshold | + resources |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| All people | +0.22 | +0.70 | −0.49 | +0.07 | +0.80 | −0.73 |
| Under 18 | +0.86 | +1.40 | −0.54 | −0.06 | +1.09 | −1.15 |
| 18 to 64 | +0.20 | +0.57 | −0.37 | +0.05 | +0.73 | −0.68 |
| 65 and over | −0.52 | +0.27 | −0.79 | +0.24 | +0.71 | −0.47 |

Results: [`results/model_decomposition.json`](results/model_decomposition.json). Per-run metadata (dataset hash,
runtime, memory) is in [`results/runs`](results/runs). The `official_pct` key in those files duplicates `spm_pct`:
policyengine-us defines `in_poverty` from `poverty_gap`, which uses the SPM threshold, so it is not an
official-measure series.

## The senior deduction

`run_senior_deduction.py` adds a 2025 run with `gov.irs.deductions.senior_deduction.amount` set to zero, and
`senior_deduction.py` compares it with the 2025 baseline. The deduction accounts for 0.012 points of the modeled
0.52-point fall in poverty among people 65 and over (about 7,700 people). It lowers income tax for 44 percent of
people 65 and over, and for 8 percent of those with resources below 125 percent of their threshold.

The same script computes three ways of anchoring the modeled change to the Census 2024 rate (additive, as registered;
multiplicative; and a threshold scale solved on 2024). All three give 13.2 percent for all people; they range from
14.0 to 14.3 for children and from 14.4 to 14.6 for people 65 and over.

Results: [`results/senior_deduction.json`](results/senior_deduction.json).

## Resource growth near the line

`near_line_growth.py` takes the people whose 2024 resources were between 75 and 150 percent of their 2024 threshold
in the model and computes the weighted median growth of their SPM unit's resources to 2025: 4.61 percent for all
people, 3.74 percent for children, 7.74 percent for people 65 and over.

Results: [`results/near_line_growth.json`](results/near_line_growth.json).

## Aging the raw survey file

`raw_aging.py` asks what a simpler forecast would have said. It takes the
[2025 CPS ASEC public-use file](https://www2.census.gov/programs-surveys/cps/datasets/2025/march/asecpub25csv.zip)
(calendar year 2024), replicates the published 2024 rates, re-bases the thresholds to the corrected 2024 BLS values,
moves them to the published 2025 values by tenure, and grows every unit's resources by one common factor.

- The threshold effect in the raw file is +0.78 points for all people, +1.04 for children, and +0.82 for people 65
  and over.
- The common resource growth that reproduces each published 2025 rate is 4.93 percent for all people, 5.47 percent
  for children, and 4.05 percent for people 65 and over.
- With the model's all-people median growth (4.61 percent) applied to everyone, the raw file gives 13.19, 13.69 and
  15.23 percent: errors of +0.08, +0.29 and −0.14 points, against +0.09, +0.90 and −0.77 for the registered
  prediction.

This check was run after the release, and the growth rate comes from the model, so it is a diagnostic and not a
second forecast.

Results: [`results/raw_aging.json`](results/raw_aging.json).

## Reproducing

```bash
uv venv && uv pip install "policyengine[models]==6.0.0" pandas
PY=.venv/bin/python ./run_all.sh arrays        # six population runs, about 4.5 minutes and up to 63 GB each
.venv/bin/python decompose.py
.venv/bin/python near_line_growth.py arrays
.venv/bin/python senior_deduction.py arrays/senior
.venv/bin/python raw_aging.py <dir-containing-pppub25.csv>
```

`policyengine[models]==6.0.0` pins policyengine-us 2.2.1, policyengine-core 3.32.5 and spm-calculator 1.0.0. The
population file is downloaded from Hugging Face on first use; its SHA-256 is recorded in each run's metadata.
`decompose.py` runs from the committed metadata without the population runs.

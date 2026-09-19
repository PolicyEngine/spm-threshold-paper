# SPM uprating and housing validation

This retrospective diagnostic measures how two PolicyEngine-US changes affect
the Supplemental Poverty Measure (SPM): [per-capita uprating of dollar inputs (#9526)](https://github.com/PolicyEngine/policyengine-us/pull/9526)
and [closer growth-series mappings (#9527)](https://github.com/PolicyEngine/policyengine-us/pull/9527).
It also replays the housing-cap calculation against the saved September 15
validation outputs.

The registered September 11 poverty forecast and its September 17 grade remain
unchanged. The calculations here are development tests on an explicitly
uncertified model/data combination. They do not constitute another forecast.

## Results

The two uprating changes raise modeled 2025 poverty by 0.121 percentage points
overall, 0.170 points for children and 0.051 points for people 65 and over.
Every recorded 2024 age-group summary remains exactly unchanged.

| Group | Annual change before fixes | Annual change after fixes | Census annual change |
|---|---:|---:|---:|
| All people | +0.164 pp | +0.286 pp | +0.07 pp |
| Under 18 | +0.857 pp | +1.026 pp | −0.06 pp |
| 65 and over | −0.729 pp | −0.678 pp | +0.24 pp |

The national and child point estimates move farther from the observed changes;
the senior estimate moves closer but still has the opposite sign. These are
retrospective comparisons for one year. Census does not identify any of these
three annual changes as statistically different from zero at the 90 percent
level. The observed changes come from Tables 4 and 5 of
[Poverty in the United States: 2025](https://www.census.gov/library/publications/2026/demo/p60-290.html),
as recorded in the [September 17 grade](https://github.com/PolicyEngine/spm-threshold-paper/blob/a79c03adbe8ec2ef432a7652f6d7123d127af24e/data/predictions/2025-spm-poverty-rates-2026-09-11.grade-2026-09-17.json).

The corrections reduce the 2025 person-weighted means of employment income and
Social Security by about 0.920 percent and unemployment compensation by
2.847 percent. These are effects of the two fixes relative to the before
runtime, not observed income growth. The resulting poverty changes show that
the accounting corrections do not resolve the age-specific prediction errors.

After the fixes, the threshold contribution is +1.338 percentage points for
children, offset by a −0.312-point change with national threshold bases held
constant in real terms. For seniors, the corresponding contributions are
+0.244 and −0.922 points. The latter remains a useful diagnostic target, but
it includes more than resource growth and does not identify a cause.

The population grows by about 0.928 percent in each broad age group, leaving
age shares essentially unchanged between 2024 and 2025. Age-specific population
growth and benefit-recipient counts remain candidates for further investigation;
this experiment does not identify them as the cause of the remaining errors.
The income-component means describe each person's own income. Investigating
children's exposure to their parents' income would require SPM-unit components
mapped to children, particularly for units near the poverty threshold.

The [comparison tables](controlled-comparison.md) report the age-specific
2024 and 2025 rates, annual changes, threshold contributions and residuals.
The [machine-readable comparison](controlled-comparison.json) includes the
controlled differences and validation checks. The six files in [results/](results/)
retain all aggregate statistics from the full local run files, with hashes of
the omitted repeated geographic metadata.

## Housing replay

The successor reference calculation matches all 16 saved cases exactly at both
the native SPM-unit and person levels. Each case contains 59,900 SPM units and
166,321 people. The recalculated housing portion also matches the saved model
output. The [receipt](housing-model-contract-replay.json) binds the input files,
calculator installation and replay source.

The old reference omitted household subsidy allocation. It differs from the
saved model on 20 native units in 2024, 18 in 2025 and 16 in each 2026 scenario.
The successor includes household member shares and the model's intermediate
float32 storage. It reproduces the declared model contract without changing
the original outputs or acceptance records.

Census documentation supports allocating a household subsidy across its SPM
units by member share. The model's A4 assumption pools tenant contributions
only from units with positive original program awards before allocating the
total to every household unit. That proxy has not been established as equivalent
to Census's household-income estimator. Passing this replay does not resolve
that scientific limitation, replace the original `NOT_REQUALIFIED` verdict,
or establish full population qualification. The [adjudication](housing-cap-adjudication.md)
gives the primary sources and arithmetic fixtures.

## Controlled uprating comparison

| Arm | Country source | Package metadata |
|---|---|---|
| Before | `238321d3b9ff44d2b6f3cbe378040be263221d47` | 2.6.8 |
| After | `44001a4c24ae5d1bce9179e2bb285b41cae6a272` | 2.6.9 plus the #9527 source change |

The intervening commits contain #9526, its version bump and #9527. Later model
changes are excluded. Both arms use the same sparse population, Core 3.32.5,
calculator 1.0.0, microdf-python 1.3.0 and remaining dependencies. The
[before](before-source-verification.json) and [after](after-source-verification.json)
receipts compare installed package files with the exact Git trees.

For each arm, `run_cell.py` runs 2024, 2025 and a 2025 reform that scales the
national thresholds by housing tenure to corrected 2024 BLS values times
32,649/31,812. It retains the model's 2025 geography and composition. The normal
2025 run uses the published BLS national bases recorded in the calculator
receipt. All rates, counts and distribution summaries use person-mapped
MicroSeries with automatic weighting from household weights.

For each age group:

```text
Annual change = rate(2025) - rate(2024)
Threshold contribution = rate(2025) - rate(2025 with anchored national bases)
Residual = rate(2025 with anchored national bases) - rate(2024)
Joint effect of the uprating fixes = annual change(after) - annual change(before)
```

The residual is the **change with national threshold bases held constant in
real terms**. It includes resources, geographic adjustments, population
composition and weights. The decomposition does not identify a causal resource
effect; it evaluates the threshold contribution on 2025 resources. The
comparison also does not separate the individual effects of #9526 and #9527.

The before arm already includes other changes made since the forecast's 2.2.1
runtime. Comparisons with that historical runtime therefore answer a different
question from the controlled joint effect reported here.

## Runtime and data scope

Population SHA-256:
`6496cc4393d4d3c6574f76eca231de5898c803b9067645591fd5c4d3e65aee84`.
The September 15 release republished the September 9 population with identical
bytes; this analysis does not build or recalibrate a population.

The released `policyengine` 6.0.0 wrapper still pins country 2.2.1. Its import
check rejects these 2.6.x country versions as outside the data certificate's
compatible range. The experiment preserves that guard and invokes the country
model through an explicit development flag. Every result records
`bundle_certified=false`; the presence of wrapper 6.0.0 in the environment does
not certify these calculations.

See [reproduction commands](REPRODUCING.md), the [initial plan](PLAN.md), and
the lightweight tests. Population runs execute sequentially; CI runs the
arithmetic, weighting and integrity fixtures without loading population data.

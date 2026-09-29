# Uprating by source

The registered forecast is the model's change between 2024 and 2025 on the same 2024 population. The model carries
each record to 2025 by multiplying its dollar inputs by the growth of an uprating index. This directory tests which of
those indices drove the misses for children and for people 65 and over, and whether growing wages by income group
would have helped.

Runtime: `policyengine[us]==6.0.0` (policyengine-us 2.2.1, policyengine-core 3.32.5, spm-calculator 1.0.0) and the
population release `populace-us-2024-spm-20260909`, as in the grade. The 2024 and 2025 baseline runs reproduce the
registered changes (+0.22, +0.86, −0.52).

Census marks none of its three changes as statistically different from zero at the 90 percent level, so these runs
show which assumptions matter; they do not pin down the right ones.

## Per-record growth in the model

For Microsimulation, policyengine-us fills 2025 by extending the 2024 dataset: `extend_single_year_dataset` in
`policyengine_us/data/economic_assumptions.py` multiplies each column by the ratio of its uprating parameter in the two
years. The indices for the sources that matter near the line, with the growth measured in the runs
(`results/near_line_sources-baseline.json`, `own_growth_pct`):

| Source | Growth, 2024 to 2025 | Index |
| --- | ---: | --- |
| Wages | 4.94% | `calibration.gov.irs.soi.employment_income`, carried forward with CBO employment income |
| Self-employment | −5.76% | `calibration.gov.irs.soi.self_employment_income`, carried forward with CBO net business income |
| Social Security (retirement, disability, survivors, dependents) | 8.31% | `calibration.gov.irs.soi.social_security`, carried forward with `calibration.gov.cbo.social_security`, whose parameter file labels 2024 as SSA actual and 2025 as a CBO February 2026 projection |
| Pensions and retirement distributions | 19.47% | `calibration.gov.irs.soi.taxable_pension_income` and `tax_exempt_pension_income`, both carried forward with CBO taxable pension income |
| Weights | 0.93% | Census total population |

We could not confirm the Social Security label against SSA's tables. If both years are CBO fiscal-year outlays,
2025 would also include the Social Security Fairness Act's retroactive payments.

## The survey

`asec/survey_growth.py` and `asec/wage_deciles.py` compare the 2025 and 2026 CPS ASEC public-use person files
(calendar 2024 and 2025). They are cross-sections, so per-recipient growth includes changes in who receives the
income. Results: [`results/survey_growth.json`](results/survey_growth.json),
[`results/wage_deciles.json`](results/wage_deciles.json).

- **Population controls changed.** The weighted population 65 and over rises 6.0% between the files while the total
  rises 0.3%, so recipient counts are not usable. Within 65 and over, the share receiving Social Security rose from
  80.2% to 81.2%.
- **Social Security per recipient:** mean +3.9%, median +4.0%. Holding the 2024 recipient age mix: +3.45% for all
  recipients and +4.04% for recipients 66 and over (the all-ages figure is pulled down by small under-50 bands). The
  2025 cost-of-living adjustment was 2.5%.
- **Wages by wage level:** mean wage within each wage decile of earners 16 and over grew 4.1% to 5.3%, with no
  gradient. Among full-year, full-time workers the bottom three deciles grew 5.0% to 5.2% and deciles four to nine
  3.4% to 4.1%.
- **Wages by family income:** ranking earners by their SPM unit's resources over its threshold, mean wage growth by
  decile was 6.6, 4.9, 5.7, 5.6, 4.3, 4.7, 6.1, 3.0, 3.5 and 5.3 percent (bottom decile: resources below about 1.2
  times the threshold), against 4.8% for all earners. Household-bootstrap standard errors are 1.3 to 2.5 points per
  decile, and the bottom decile's 1.8-point excess has a standard error of 2.1, so the pattern is not distinguishable
  from sampling error. Each year's deciles are its own, and the ranking uses resources that include wages, so treat
  it as a lead.
- **Self-employment (SEMP_VAL):** mean over nonzero values, losses included, +14.6%; positive values only, mean +13.1%
  and median +8.7%.
- **Pensions and annuities, 65 and over:** per recipient, mean +6.6%, median +3.7%. Retirement distributions: mean
  +4.7%, median unchanged.
- **A composition change:** the share of children in SPM units with a noncitizen member fell from 17.9% to 16.4%.
  At 2024 poverty rates (24.7% against 10.9%) that shift alone lowers child poverty by about 0.21 points. No uprating
  index reproduces it, and survey nonresponse could produce it.

## Near-line resource growth by source

`near_line_sources.py` takes people whose 2024 SPM resources were 75 to 150 percent of their threshold, the same group
as `../near_line_growth.py`, and splits the weighted mean growth of their SPM unit's resources into contributions
from each source (change in the source over 2024 resources). Contributions add to the mean.

| Baseline | Under 18 | 65 and over |
| --- | ---: | ---: |
| Mean resource growth | 3.67% | 8.36% |
| Wages | +3.71 pp | +1.60 pp |
| Self-employment | −0.52 pp | −0.48 pp |
| Social Security | +0.22 pp | +5.68 pp |
| Pensions and retirement distributions | +0.17 pp | +2.56 pp |
| Medical out-of-pocket spending | −0.27 pp | −1.25 pp |

Results: `results/near_line_sources-<variant>.json`.

## Variants

`run_sources.py` replaces the named 2025 inputs with their 2024 values times a different factor, before anything that
depends on them is computed, and asserts that the replacement took. Each variant's metadata records the input totals
before and after (`results/sources-meta-2025-<variant>.json`).

| Variant | Replacement |
| --- | --- |
| `ss_cola` | Social Security grows with `gov.ssa.uprating` (2.49%, the COLA) |
| `ss_cola_pension_cpi` | `ss_cola`, and pensions and retirement distributions grow with CPI-U, January over January (3.00%) |
| `wages_by_decile` | wages grow by the survey's growth for the earner's 2024 wage decile |
| `se_like_wages` | self-employment grows with the wage index (4.94%) |
| `all_three` | `ss_cola_pension_cpi` and `se_like_wages` |
| `all_three_cpi_avg` | `all_three`, with pensions at CPI-U annual-average growth (2.63%, the official poverty threshold's growth) |
| `all_three_ss_survey` | `all_three_cpi_avg`, with Social Security at the survey's age-adjusted per-recipient growth (3.45%) |
| `all_three_ss_66plus` | `all_three_cpi_avg`, with Social Security at the survey's age-adjusted growth for recipients 66 and over (4.04%) |
| `wages_by_family_decile` | wages grow by the survey's growth for the earner's 2024 decile of SPM resources over threshold |
| `all_four` | `all_three_cpi_avg` and `wages_by_family_decile` |

Modeled change from 2024, percentage points ([`results/variant_comparison.json`](results/variant_comparison.json)):

| Variant | All people | Under 18 | 65 and over |
| --- | ---: | ---: | ---: |
| Census | +0.07 | −0.06 | +0.24 |
| Baseline (registered) | +0.22 | +0.86 | −0.52 |
| `wages_by_decile` | +0.24 | +0.85 | −0.52 |
| `wages_by_family_decile` | +0.09 | +0.71 | −0.59 |
| `ss_cola` | +0.40 | +0.93 | +0.01 |
| `ss_cola_pension_cpi` | +0.47 | +0.98 | +0.21 |
| `se_like_wages` | +0.01 | +0.47 | −0.59 |
| `all_three` | +0.25 | +0.57 | +0.15 |
| `all_three_cpi_avg` | +0.25 | +0.57 | +0.15 |
| `all_three_ss_survey` | +0.20 | +0.56 | +0.05 |
| `all_three_ss_66plus` | +0.17 | +0.53 | −0.02 |
| `all_four` | +0.10 | +0.42 | +0.06 |

## Threshold and resource effects by variant

`split_variants.py` splits each variant's change the way `../decompose.py` splits the baseline, on the variant run
itself: the threshold effect is the 2025 rate minus the 2025 rate with thresholds anchored to 2024 plus CPI-U, and
the resource effect is the rest. The threshold effect counts people whose 2025 resources fall between the anchored
threshold and the actual one, just below the 2025 line. The split depends on order: a source that moves people into
that band shows up in the threshold term. Results: [`results/variant_split.json`](results/variant_split.json).

| Run | Under 18: threshold | Under 18: resources | 65 and over: threshold | 65 and over: resources |
| --- | ---: | ---: | ---: | ---: |
| Survey (Census) | +1.09 | −1.15 | +0.71 | −0.47 |
| Baseline | +1.40 | −0.54 | +0.27 | −0.79 |
| `se_like_wages` | +1.23 | −0.76 | +0.32 | −0.91 |
| `all_three_cpi_avg` | +1.16 | −0.59 | +0.38 | −0.23 |
| `all_three_ss_66plus` | +1.13 | −0.60 | +0.41 | −0.43 |
| `wages_by_family_decile` | +1.52 | −0.80 | +0.26 | −0.85 |
| `all_four` | +1.36 | −0.93 | +0.35 | −0.29 |

## Reading

- **Three sources.** Social Security and pensions grow per record at aggregate rates, which carry growth in the number
  and mix of recipients that a static population does not have, and self-employment falls with CBO's projection of
  aggregate business income while the survey shows it rising. Changing all three (`all_three_cpi_avg`,
  `all_three_ss_66plus`) takes the child miss from 0.92 to 0.59–0.63 points, about a third, and the senior miss from
  0.76 to 0.09–0.26 points, depending on the Social Security rate. Social Security and pensions alone give +0.21 for
  people 65 and over; self-employment alone gives +0.47 for children.
- **Seniors.** At the survey's 4.04% for recipients 66 and over, the senior resource effect matches the survey
  (−0.43 against −0.47) and the remaining gap is on the threshold side: the model has fewer seniors just below the
  line in every variant (threshold effect 0.26 to 0.41 against 0.71). At the 2.5% COLA the senior change is closer to
  Census only because resource growth is then too slow and offsets the threshold gap.
- **Wages by income group.** Growing wages by wage decile changes nothing: wages grew at about the same rate at every
  wage level. Growing them by decile of family resources over need moves the child change to +0.71 alone and to
  +0.42 with the three source changes (`all_four`), but that schedule is within sampling error (see above), so it
  shows the size a family-income gradient could have, not that there was one.
- **The split is order-dependent.** The child threshold gap (1.40 against 1.09 in the baseline) shrinks to 1.13–1.23
  when self-employment grows with wages and grows to 1.52 when wages grow by family resources. Read the totals first.
- **All people.** The three source changes leave the all-people change 0.10 to 0.18 points above Census, about where
  the registered forecast was: its close all-people result owed something to offsetting errors.
- **What remains for children** (about 0.6 points with the three source changes) is not explained by these sources.
  The fall in the share of children living with a noncitizen, worth about 0.2 points at 2024 rates, is one candidate
  that no uprating index can reproduce; survey nonresponse could produce it too.

The replacement rates are reference rates, not estimates of the right growth for each record.

## Reproducing

```bash
uv venv --python 3.13 && VIRTUAL_ENV=.venv uv pip install "policyengine[us]==6.0.0"
PY=.venv/bin/python ./run_uprating.sh uprating-runs   # twelve population runs, about 5-13 minutes and 50-60 GB each
cd asec && ../.venv/bin/python survey_growth.py && ../.venv/bin/python wage_deciles.py   # needs pppub25.csv, pppub26.csv
```

The scripts write their JSON to the working directory (`uprating-runs/` and `asec/`); the committed copies are in
`results/`. Survey files:
[asecpub25csv.zip](https://www2.census.gov/programs-surveys/cps/datasets/2025/march/asecpub25csv.zip),
[asecpub26csv.zip](https://www2.census.gov/programs-surveys/cps/datasets/2026/march/asecpub26csv.zip).

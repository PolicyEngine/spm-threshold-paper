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
- **Social Security per recipient:** mean +3.9%, median +4.0%; +3.45% holding the 2024 recipient age mix. The 2025
  cost-of-living adjustment was 2.5%.
- **Wages by wage level:** mean wage within each wage decile of earners 16 and over grew 4.1% to 5.3%, with no
  gradient. Among full-year, full-time workers the bottom three deciles grew 5.0% to 5.2% and deciles four to nine
  3.4% to 4.1%.
- **Wages by family income:** ranking earners by their SPM unit's resources over its threshold, mean wages grew 6.6% in
  the bottom decile (resources below about 1.2 times the threshold), 4.9% to 5.7% in deciles two to four, and 3.0% to
  3.5% in deciles eight and nine. Each year's deciles are its own, so this compares distributions, not the same people.
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
| `all_four` | +1.36 | −0.93 | +0.35 | −0.29 |

## Reading

- **Wages by income group.** Growing wages by the survey's growth in each wage decile changes nothing: wages grew at
  about the same rate at every wage level. In the survey, mean wages grew faster for earners in families with
  low resources relative to need; growing wages by decile of that ratio takes the child change from +0.86 to +0.71.
- **Seniors.** Social Security and pensions grow per record at aggregate rates, which carry growth in the number and
  mix of recipients that a static population does not have. Replacing those rates takes the senior change from −0.52
  to between +0.05 and +0.15, depending on the Social Security rate (the survey's 3.45% or the 2.5% COLA), against
  Census's +0.24. The remaining gap is on the threshold side: the model has fewer seniors just below the line in
  every variant (threshold effect 0.26 to 0.39 against 0.71), partly offset by resource growth.
- **Self-employment.** CBO projects aggregate business income to fall 5.8% in 2025; applied to every self-employed
  record, that cuts near-line children's resources while the survey shows self-employment income rising. Growing it
  with wages takes the child change from +0.86 to +0.47. Most of the child threshold gap in the baseline (1.40 against
  1.09) comes from this: it falls to 1.23 in `se_like_wages` and 1.16 in `all_three_cpi_avg`.
- **All four together.** +0.10 for all people, +0.42 for children and +0.06 for people 65 and over, against Census's
  +0.07, −0.06 and +0.24: the all-people change within 0.03 points, the child miss halved, the senior miss cut from
  0.76 to 0.18 points.
- **What remains for children** (about 0.5 points) is not explained by these sources. The fall in the share of
  children living with a noncitizen, worth about 0.2 points at 2024 rates, is one candidate that no uprating index
  can reproduce.

The replacement rates are reference rates, not estimates of the right growth for each record.

## Reproducing

```bash
uv venv --python 3.13 && VIRTUAL_ENV=.venv uv pip install "policyengine[us]==6.0.0"
PY=.venv/bin/python ./run_uprating.sh uprating-runs   # eleven population runs, about 5-10 minutes and 50-60 GB each
cd asec && ../.venv/bin/python survey_growth.py && ../.venv/bin/python wage_deciles.py   # needs pppub25.csv, pppub26.csv
```

The scripts write their JSON to the working directory (`uprating-runs/` and `asec/`); the committed copies are in
`results/`. Survey files:
[asecpub25csv.zip](https://www2.census.gov/programs-surveys/cps/datasets/2025/march/asecpub25csv.zip),
[asecpub26csv.zip](https://www2.census.gov/programs-surveys/cps/datasets/2026/march/asecpub26csv.zip).

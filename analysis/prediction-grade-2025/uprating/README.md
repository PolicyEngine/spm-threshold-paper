# Uprating by source

The registered forecast is the model's change between 2024 and 2025 on the same 2024 population. The model carries
each record to 2025 by multiplying its dollar inputs by the growth of an uprating index. This directory tests which of
those indices caused the misses for children and for people 65 and over.

Runtime: `policyengine[us]==6.0.0` (policyengine-us 2.2.1, policyengine-core 3.32.5, spm-calculator 1.0.0) and the
population release `populace-us-2024-spm-20260909`, as in the grade. The 2024 and 2025 baseline runs reproduce the
registered changes (+0.22, +0.86, −0.52).

## Per-record growth in the model

policyengine-core multiplies an input by the ratio of its uprating index in the two years
(`policyengine_core/simulations/simulation.py`), and policyengine-us extends the single-year dataset the same way
(`policyengine_us/data/economic_assumptions.py`). The indices for the sources that matter near the line, and the
growth measured in the runs (`results/near_line_sources-baseline.json`, "own_growth_pct"):

| Source | Growth, 2024 to 2025 | Index |
| --- | ---: | --- |
| Wages | 4.94% | `calibration.gov.irs.soi.employment_income`, carried forward with CBO employment income |
| Self-employment | −5.76% | `calibration.gov.irs.soi.self_employment_income`, carried forward with CBO net business income |
| Social Security (retirement, disability, survivors, dependents) | 8.31% | `calibration.gov.irs.soi.social_security`, carried forward with `calibration.gov.cbo.social_security` (SSA benefit payments for 2024, CBO February 2026 projection for 2025) |
| Pensions and retirement distributions | 19.47% | `calibration.gov.irs.soi.taxable_pension_income` and `tax_exempt_pension_income`, carried forward with CBO taxable pension income |
| Weights | 0.93% | Census total population |

## The survey

`asec/survey_growth.py` and `asec/wage_deciles.py` compare the 2025 and 2026 CPS ASEC public-use person files
(calendar 2024 and 2025). They are cross-sections, so per-recipient growth includes changes in who receives the
income. Results: [`results/survey_growth.json`](results/survey_growth.json),
[`results/wage_deciles.json`](results/wage_deciles.json).

- Social Security per recipient: mean +3.9%, median +4.0%; recipients +4.7%. The 2025 cost-of-living adjustment was
  2.5%.
- Wages per earner: mean +4.8%. Mean wage within each wage decile of earners 16 and over: +4.1% to +5.3%, with no
  gradient by level. Among full-year, full-time workers the bottom three deciles grew 5.0% to 5.2% and deciles
  four to nine 3.4% to 4.1%.
- Self-employment per recipient: +14.6%.
- Pensions and annuities per recipient 65 and over: mean +6.6%, median +3.7%.

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
| `ss_cola` | Social Security inputs grow with `gov.ssa.uprating` (2.49%, the COLA) |
| `ss_cola_pension_cpi` | as `ss_cola`, and pension and retirement-distribution inputs grow with CPI-U (3.00%) |
| `wages_by_decile` | wages grow by the survey's growth of mean wages in the earner's 2024 wage decile |
| `se_like_wages` | self-employment inputs grow with the wage index (4.94%) |
| `all_three` | `ss_cola_pension_cpi` and `se_like_wages` together |

Modeled change from 2024, percentage points ([`results/variant_comparison.json`](results/variant_comparison.json)):

| Variant | All people | Under 18 | 65 and over |
| --- | ---: | ---: | ---: |
| Census | +0.07 | −0.06 | +0.24 |
| Baseline (registered) | +0.22 | +0.86 | −0.52 |
| `wages_by_decile` | +0.24 | +0.85 | −0.52 |
| `ss_cola` | +0.40 | +0.93 | +0.01 |
| `ss_cola_pension_cpi` | +0.47 | +0.98 | +0.21 |
| `se_like_wages` | +0.01 | +0.47 | −0.59 |
| `all_three` | +0.25 | +0.57 | +0.15 |

## Reading

- Growing wages by the survey's growth in each wage decile changes nothing, because wages grew at about the same
  rate throughout the distribution in 2025.
- Social Security and pensions grow per record at aggregate rates, which include growth in the number of recipients.
  The static population carries that growth only through the 0.93% weight growth, so each record's benefit rises
  too fast. Replacing both rates removes nearly all of the miss for people 65 and over.
- Self-employment income falls per record with CBO's projection of aggregate business income, while it rose per
  recipient in the survey. Growing it with wages removes about 0.4 points of the child miss.
- With all three replacements the child miss is still about 0.6 points. The threshold effect for children, 1.40 points
  in the model against 1.09 in the survey, accounts for about half of it: the model has more children just above the
  line.
- The all-people forecast came close partly because the child and senior errors offset. With all three replacements
  the all-people change is +0.25.

These runs diagnose the forecast after the fact. The replacement rates are reference rates, not estimates of the right
growth for each record.

## Reproducing

```bash
uv venv --python 3.13 && uv pip install "policyengine[us]==6.0.0"
PY=.venv/bin/python ./run_uprating.sh uprating-runs   # seven population runs, about 5 minutes and 50-60 GB each
cd asec && ../.venv/bin/python survey_growth.py && ../.venv/bin/python wage_deciles.py   # needs pppub25.csv, pppub26.csv
```

Survey files: [asecpub25csv.zip](https://www2.census.gov/programs-surveys/cps/datasets/2025/march/asecpub25csv.zip),
[asecpub26csv.zip](https://www2.census.gov/programs-surveys/cps/datasets/2026/march/asecpub26csv.zip).

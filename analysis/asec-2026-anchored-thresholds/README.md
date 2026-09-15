# 2025 SPM poverty with thresholds anchored to 2024

Computed September 15, 2026, the day Census released *Poverty in the United States: 2025* (P60-290), from the 2026 CPS ASEC public-use person file (`asecpub26csv.zip`, `pppub26.csv`, posted at www2.census.gov/programs-surveys/cps/datasets/2026/march/).

## Replication

Person weight `MARSUPWT`. SPM poverty (`SPM_POOR`): 13.11 percent of all people, 13.39 percent of children, 12.28 percent of people 18 to 64, 15.38 percent of people 65 and over; 44,390 thousand people and 9,653 thousand children below the threshold. Published (Table 8): 13.1 / 13.4 / 12.3 / 15.4; 44,390 and 9,657 thousand. Official poverty (`PERLIS` = 1 within `POV_UNIV` = 1): 10.20 / 13.41 / 9.20 / 9.77 against 10.2 / 13.4 / 9.2 / 9.8.

## Anchoring

Each unit's `SPM_POVTHRESHOLD` is scaled by tenure so that the national two-adult, two-child base equals its 2024 value (BLS corrected series: owners with a mortgage 39,231; owners without 32,879; renters 39,220) times the CPI-U ratio Census used for the 2025 official thresholds (32,649 / 31,812 = 1.02631). Tenure codes were verified from the implied 2025 bases (`SPM_POVTHRESHOLD / (SPM_EQUIVSCALE × SPM_GEOADJ)`): 1 = 41,323, 2 = 34,326, 3 = 41,701. The equivalence scale and geographic adjustment stay at their published 2025 values. A person is poor when `SPM_RESOURCES` is below the anchored threshold.

| SPM poverty rate, percent | 2024 (re-based, P60-290) | 2025 published | 2025 at 2024 thresholds × CPI-U | 2025 at 2024 thresholds × C-CPI-U |
| --- | ---: | ---: | ---: | ---: |
| All people | 13.0 | 13.11 | 12.31 | 12.29 |
| Under 18 | 13.5 | 13.39 | 12.31 | 12.30 |
| 18 to 64 | 12.2 | 12.28 | 11.55 | 11.53 |
| 65 and over | 15.1 | 15.38 | 14.66 | 14.62 |

Threshold growth beyond CPI-U adds 0.80 points for all people, 1.08 for children, 0.73 for people 18 to 64 and 0.72 for people 65 and over. By tenure: renters 23.96 published against 22.13 anchored, owners without a mortgage 11.89 against 11.49, owners with a mortgage 6.00 against 5.67.

The chained variant uses C-CPI-U (`SUUR0000SA0`) annual means, 174.372 for 2024 and 178.697 for 2025 (eleven months; October 2025 was not published), a ratio of 1.02480; recent C-CPI-U values are interim.

## Files

- `replicate_and_anchor.py`: run in a directory containing `pppub26.csv`; optional argument is the price factor (default 32649/31812).
- `anchored_results.json`, `anchored_results_chained.json`: outputs.
- `bls_ccpi.json`: BLS API response for `SUUR0000SA0` and `CUUR0000SA0`, 2024 to 2025.

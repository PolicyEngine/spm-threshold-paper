# Forecast registration and evaluation record

## Forecast chronology

The 2025 commitment used a price calculation that combined CPI components
with different index bases. We corrected the calculation before BLS published the outcome, and the
equal blend remained the primary forecast.
The correction changed the retrospective ranking, placing the consumption
growth rule first. The evaluation retained every component rule.

The correction moved estimates by 0.1 to 0.3 percent. In tenure order, the
original and amended forecasts were:

| Tenure | Original forecast | Amended forecast |
|---|---:|---:|
| Owners with mortgages | $41,099.57 | $41,036.34 |
| Owners without mortgages | $34,250.70 | $34,135.99 |
| Renters | $40,791.72 | $40,755.98 |

The original and amended values, corrected 2024 base, and evaluation rules
remain fixed in the repository. The preregistration records the forecast
values and evaluation rules before the outcome ([Nosek et al., 2018](https://doi.org/10.1073/pnas.1708274114)).

The [August 7, 2026 archived page](https://web.archive.org/web/20260807211521/https://spm-threshold-paper.vercel.app/)
and retained OpenTimestamps evidence precede the August 24 publication.
The repository preserves the original forecast tags, manifests, and proof
files. A September 8 amendment corrects two hashes in a secondary manifest;
the original timestamp does not cover that amendment. The verification
script checks retained bytes and Git identities without independently
reverifying blockchain attestations.

## Evaluation record

The original blend scored 0.98 percent mean absolute error, compared with
1.17 percent for the amended primary blend. The complete historical
evaluation, including the superseded original blend, remains in
[`paper/tables/evaluation.md`](../paper/tables/evaluation.md). The generator also produces the primary four-rule table at
[`paper/tables/evaluation_main.md`](../paper/tables/evaluation_main.md).
The underlying evaluation artifact is
[`data/evaluation_2025.json`](../data/evaluation_2025.json), and the
forecast inputs and preserved commitment evidence remain in the
[`data/`](../data/) artifacts.

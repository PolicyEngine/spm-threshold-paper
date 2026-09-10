# Reproducing the scientific experiments

The paper contains two distinct research implementations. Use separate
checkouts; the 1.0 source does not contain the historical projection API
used by the 2019–2025 retrospective experiment. Rebuilding the paper's
tables from saved outputs is a separate, inexpensive verification described
in the [README](../README.md).

## Retrospective CE replication and one-year comparisons

The complete experiment uses development version 0.5.0 at
[`0d7fa0d77b0a88064ab7b9fe70557309b5f7901f`](https://github.com/PolicyEngine/spm-calculator/tree/0d7fa0d77b0a88064ab7b9fe70557309b5f7901f).
Its [executable replay script](https://github.com/PolicyEngine/spm-calculator/blob/0d7fa0d77b0a88064ab7b9fe70557309b5f7901f/scripts/replicate_current_ce.py)
imports the CE estimator, price-index helpers, equivalence scale, and the
`forecast` and `projection` modules present at that revision. It recomputes
the seven CE windows, sample sensitivities, and six one-year comparisons.
The similarly named script in 1.0 deliberately omits the archived projection
evaluation, so it is not a substitute for this replay.

In a fresh calculator checkout at that commit:

```sh
uv venv --python 3.14.4
uv pip install -e . "numpy==2.5.3" "pandas==3.0.5"
uv run --no-project python -B scripts/replicate_current_ce.py --help
uv run --no-project python -B scripts/replicate_current_ce.py \
  --cache-dir /absolute/path/to/ce-pumd \
  --cpi-input spm_calculator/data/bls/cpi_annual.json \
  --output benchmark_output/ce-retrospective-replay.json
```

The Python, NumPy, and pandas versions above are those recorded in the
[experiment receipt](../data/current/ce_replication_2019_2025.json).
The receipt identifies eleven CE Interview archives (`intrvw14.zip` through
`intrvw24.zip`), 44 selected quarter members, archive URLs and hashes, the
CPI input hash, and the published comparison-series hash. The archives
total 714,430,947 bytes and remain outside Git. The last archive includes
the terminal 2025Q1 collection file. The script refuses to download a
missing CE archive and does not call the CPI API.

Use a new output path. The replay records its execution date, Git head and
runtime; those metadata will differ from the saved receipt. Compare the
scientific results and source/code fingerprints rather than replacing the
historical receipt or asserting that a new execution has the old timestamp.
The receipt's starting Git head predates the commit containing the executed
code; the paper's provenance identifies the latter by file hashes.

## Conditional rolling CE and ACS projection

This experiment uses the 1.0.0 release candidate at
[`78bae15f76152c6076dd909a09f6b63dc2ec8c34`](https://github.com/PolicyEngine/spm-calculator/tree/78bae15f76152c6076dd909a09f6b63dc2ec8c34).
The executable source entry points are:

- [CE rolling builder](https://github.com/PolicyEngine/spm-calculator/blob/78bae15f76152c6076dd909a09f6b63dc2ec8c34/scripts/build_ce_forecast.py), using `ce_forecast`, `ce_threshold`, and `forecast_inputs`.
- [ACS rolling builder](https://github.com/PolicyEngine/spm-calculator/blob/78bae15f76152c6076dd909a09f6b63dc2ec8c34/scripts/build_acs_forecast.py), using `acs_forecast`, `acs_forecast_sources`, and `forecast_inputs`.
- [Portable artifact assembler](https://github.com/PolicyEngine/spm-calculator/blob/78bae15f76152c6076dd909a09f6b63dc2ec8c34/scripts/build_rolling_forecast.py), using the checked component outputs and source/code identities.

The source declares Python 3.9 or newer and dependencies in its
`pyproject.toml`. A Python 3.14 environment can be prepared with
`uv venv --python 3.14.4` and `uv pip install -e .`. These commands use
the source checkout; no published 1.0 package, PolicyEngine population,
Microcosm dataset, Axiom service, or Census API key is required. The rolling
component receipts do not supply a complete locked Python environment;
record the resolved runtime and package versions when re-estimating.

With the recorded raw inputs cached, these commands re-estimate and compare
the scientific component bytes without overwriting them:

```sh
uv run --no-project python -B scripts/build_ce_forecast.py \
  --cache-dir /absolute/path/to/ce-pumd \
  --cpi-input spm_calculator/data/bls/cpi_annual.json \
  --information-date 2026-09-09 \
  --output spm_calculator/data/current/ce_rolling_forecast.json --check
uv run --no-project python -B scripts/build_acs_forecast.py \
  --cache-dir /absolute/path/to/acs-pums \
  --information-date 2026-09-09 \
  --output spm_calculator/data/current/acs_rolling_forecast.json --check
uv run --no-project python -B scripts/build_rolling_forecast.py --check
```

The CE command re-estimates the projected windows and all 21 retrospective
origin/target folds. The ACS command re-estimates the geographic windows,
rent sensitivity, historical residual areas, and 341-area comparison.
The final assembly command is inexpensive: it uses saved component outputs,
validates their identities, and rebuilds the portable artifact. Running
only that last command does not constitute a new raw-microdata replication.

ACS requires five archives in the cache: `2021/csv_hus.zip`,
`2022/csv_hus.zip`, `2022/csv_h_update_puma.zip`, `2023/csv_hus.zip`, and
`2024/csv_hus.zip`. The pinned
[current source bundle](https://github.com/PolicyEngine/spm-calculator/blob/78bae15f76152c6076dd909a09f6b63dc2ec8c34/spm_calculator/data/current/acs_forecast_inputs.json)
and [2021 source bundle](https://github.com/PolicyEngine/spm-calculator/blob/78bae15f76152c6076dd909a09f6b63dc2ec8c34/spm_calculator/data/current/acs_2021_source_inputs.json)
provide exact URLs, hashes, compact geography allocations, topcoding inputs
and source-vintage information. The package also retains published anchors,
the CPI receipt, CBO price inputs, and the fixed 2025 geographic prediction.

The ACS loader verifies raw-archive hashes even when it can reuse a verified
normalized-record cache. To require fresh raw parsing, use a separate cache
containing the five raw archives without previously generated `normalized/`
products. Do not delete a shared cache or call a normalized-cache replay a
new raw parse. The recorded September 9 code-identity adaptation preserves
its earlier parse evidence; it does not claim another raw-data execution.

## Source access and interpretation

The raw inputs are public BLS and Census downloads, but these builders are
offline and do not acquire missing files. Obtain the exact archive bytes
listed in the receipts before execution. Public URLs can be revised or
temporarily blocked; a changed download is a different input vintage,
even if its filename is the same. BLS pages returned command-line HTTP 403
during the September 10 editorial check while remaining readable through
web retrieval. This check did not redownload the large raw archives or
re-estimate the scientific components.

The paper and calculator archive their scientific outputs and fingerprints;
they do not distribute the raw CE/ACS archives in Git. Exact historical
source availability is not reconstructed. Re-execution does not create a
new pre-publication forecast commitment. The separate historical poverty
sensitivity lacks immutable model and population identities and therefore
does not have an established exact replay recipe.

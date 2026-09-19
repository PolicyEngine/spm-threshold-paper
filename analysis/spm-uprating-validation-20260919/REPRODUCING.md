# Reproducing the September 19 diagnostics

Run these commands from the paper repository root in a dedicated checkout.
The full population runs require roughly 45–65 GB of memory each. Run them
sequentially. The lightweight fixture tests do not load a country model or data.

## Environment and inputs

```sh
uv venv --python 3.13.9 .venv
uv pip install --python .venv/bin/python \
  -r analysis/spm-uprating-validation-20260919/runtime-requirements.txt
```

The requirements preserve the September 15 environment, initially including
country 2.2.1. The commands below replace only that country package with each
specified source snapshot. They retain Core 3.32.5, calculator 1.0.0,
microdf-python 1.3.0, and all other runtime dependencies.

Set these task-specific paths. The country repository must contain both full
revisions below. The data file must have SHA-256
`6496cc4393d4d3c6574f76eca231de5898c803b9067645591fd5c4d3e65aee84`:

```sh
SPM_MODEL_REPO=/absolute/path/to/policyengine-us
SPM_DATASET=/absolute/path/to/populace_us_2024.h5
SPM_RUN_ROOT=/absolute/path/to/new-empty-run-directory
SPM_ANALYSIS=analysis/spm-uprating-validation-20260919
mkdir -p "$SPM_RUN_ROOT/results" "$SPM_RUN_ROOT/logs"
```

The data file is the sparse population used in the registered forecast and
republished with identical bytes on September 15. Do not substitute another
release. `run_cell.py` hashes it before loading.

## Controlled country-model regression

The released wrapper rejects these country versions because they fall outside
the data certificate's compatible range. The explicit development flag below
uses the country-model test interface. It does not alter a certificate, expand
its range, or assert that this combination is a certified bundle.

```sh
set -e
for stage in before after; do
  case "$stage" in
    before)
      spm_revision=238321d3b9ff44d2b6f3cbe378040be263221d47
      spm_version=2.6.8
      ;;
    after)
      spm_revision=44001a4c24ae5d1bce9179e2bb285b41cae6a272
      spm_version=2.6.9
      ;;
  esac
  mkdir -p "$SPM_RUN_ROOT/source-$stage"
  git -C "$SPM_MODEL_REPO" archive "$spm_revision" |
    tar -x -C "$SPM_RUN_ROOT/source-$stage"
  uv pip install --python .venv/bin/python --no-deps \
    "$SPM_RUN_ROOT/source-$stage"
  uv run --no-project --python .venv/bin/python python \
    "$SPM_ANALYSIS/verify_runtime.py" \
    --repository "$SPM_MODEL_REPO" --revision "$spm_revision" \
    --runner "$SPM_ANALYSIS/run_cell.py" \
    --expected-runner-sha256 dbcd662a55b9c74c7a5d6fb8f8bcb53c1c25beb737a2edc2f776bf7e91dfe0b4 \
    --output "$SPM_RUN_ROOT/$stage-source-verification.json"
  uv pip freeze --python .venv/bin/python > "$SPM_RUN_ROOT/$stage-packages.txt"
  for cell in 2024:baseline 2025:baseline 2025:anchored_2024_cpi; do
    PYTHONHASHSEED=0 uv run --no-project --python .venv/bin/python python \
      "$SPM_ANALYSIS/run_cell.py" \
      --year "${cell%:*}" --variant "${cell#*:}" \
      --dataset "$SPM_DATASET" --runtime-label "$stage-uprating" \
      --country-source-sha "$spm_revision" --development-country-model \
      --expected-model-version "$spm_version" \
      --component employment_income --component social_security \
      --component unemployment_compensation \
      --component spm_unit_capped_housing_subsidy \
      --output "$SPM_RUN_ROOT/results/$stage-${cell%:*}-${cell#*:}.json" \
      > "$SPM_RUN_ROOT/logs/$stage-${cell%:*}-${cell#*:}.log" 2>&1
  done
done
uv run --no-project --python .venv/bin/python python \
  "$SPM_ANALYSIS/summarize_results.py" \
  --results-dir "$SPM_RUN_ROOT/results" \
  --output "$SPM_RUN_ROOT/controlled-comparison.json"
```

The after revision follows #9527 but precedes its version-bump commit. Its
package metadata therefore says 2.6.9; the full source SHA identifies the
mapping fix. The two trees differ only by #9526, a release-version commit, and
#9527. They exclude later model changes.

`verify_runtime.py` compares every tracked regular package file in the chosen
Git revision with the installed package. Its receipt supplements the runner's
declared revision. `summarize_results.py` requires all six cells, matched runtime
and population inputs, consistent counts, and an effective threshold reform.

## Aggregate publication copies

The full cell files contain large repeated geographic calculator metadata.
`compact_cell.py SOURCE DESTINATION` preserves all aggregate statistics and
records the full source-file hash plus hashes of each omitted metadata block.
The abbreviated provenance is not a complete calculator receipt. Keep the
full files for geographic audit. The summarizer can also consume the six
committed compact copies in `results/`.

## Housing replay and lightweight tests

The housing replay requires the trusted local September 15 checkpoint tree and
its frozen runtime with calculator 1.0.0. It authenticates checkpoint files and
the installed calculator against the original wheel. It does not load the H5
or run a country model:

```sh
uv run --no-project --python /path/to/frozen/runtime-env/bin/python python \
  "$SPM_ANALYSIS/housing_replay.py" \
  --artifacts-root /path/to/requalification-registry-20260915 \
  --output /path/to/new-housing-model-contract-replay.json
uv run --no-project --python .venv/bin/python python -m pytest \
  tests/test_spm_uprating_validation.py tests/test_spm_uprating_summary.py \
  "$SPM_ANALYSIS/test_housing_replay.py" -q
```

The original replay and acceptance receipts remain unchanged. The successor
checks the stated country-model contract under the A4 tenant-payment assumption;
it does not establish Census parity or full population qualification.

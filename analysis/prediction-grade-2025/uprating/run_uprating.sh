#!/bin/bash
# Eleven population runs, one process each (about 5-10 minutes and 50-60 GB of memory per run), then the summaries.
# The 2024 baseline must run first: wages_by_family_decile and all_four read its arrays.
# usage: PY=/path/to/python ./run_uprating.sh <output-dir>
set -euo pipefail
PY="${PY:-python}"; OUT="${1:-uprating-runs}"; HERE="$(cd "$(dirname "$0")" && pwd)"
VARIANTS="baseline ss_cola ss_cola_pension_cpi wages_by_decile se_like_wages all_three wages_by_family_decile all_three_cpi_avg all_three_ss_survey all_four"
mkdir -p "$OUT"; cd "$OUT"
"$PY" "$HERE/run_sources.py" 2024 baseline > log-2024-baseline.txt 2>&1
for v in $VARIANTS; do "$PY" "$HERE/run_sources.py" 2025 "$v" > "log-2025-$v.txt" 2>&1; done
"$PY" "$HERE/compare_variants.py"
"$PY" "$HERE/split_variants.py"
for v in $VARIANTS; do "$PY" "$HERE/near_line_sources.py" "$v" > "near-line-$v.txt"; done

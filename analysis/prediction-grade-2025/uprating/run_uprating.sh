#!/bin/bash
# Seven population runs, one process each (about 5 minutes and 50-60 GB of memory per run), then the summaries.
# usage: PY=/path/to/python ./run_uprating.sh <output-dir>
set -euo pipefail
PY="${PY:-python}"; OUT="${1:-uprating-runs}"; HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$OUT"; cd "$OUT"
for spec in "2024 baseline" "2025 baseline" "2025 ss_cola" "2025 ss_cola_pension_cpi" "2025 wages_by_decile" \
            "2025 se_like_wages" "2025 all_three"; do
  set -- $spec; "$PY" "$HERE/run_sources.py" "$1" "$2" > "log-$1-$2.txt" 2>&1
done
"$PY" "$HERE/compare_variants.py"
for v in baseline ss_cola ss_cola_pension_cpi wages_by_decile se_like_wages all_three; do
  "$PY" "$HERE/near_line_sources.py" "$v" > "near-line-$v.txt"
done

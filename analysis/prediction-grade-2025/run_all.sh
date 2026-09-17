#!/bin/bash
# Four population runs, one process each (about 4.5 minutes and up to 63 GB of memory per run).
# usage: PY=/path/to/python ./run_all.sh <output-dir>
set -euo pipefail
PY="${PY:-python}"; OUT="${1:-arrays}"; HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$OUT"; cd "$OUT"
for spec in "2024 baseline" "2025 baseline" "2025 anchored_2024_cpi"; do
  set -- $spec; "$PY" "$HERE/run_decomp.py" "$1" "$2" > "log-$1-$2.txt" 2>&1
done
mkdir -p senior; cd senior
for spec in "2024 baseline" "2025 baseline" "2025 no_senior_deduction"; do
  set -- $spec; "$PY" "$HERE/run_senior_deduction.py" "$1" "$2" > "log-$1-$2.txt" 2>&1
done

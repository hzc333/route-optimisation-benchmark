#!/usr/bin/env bash
# Full Phase 0 run: environment snapshot, strict-priority experiments, then
# every benchmark config (~4 h on 4 P-cores), then plots. Resumable: finished
# benchmark runs are skipped on restart.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=./.venv/Scripts/python
[ -x "$PY" ] || PY=./.venv/bin/python

$PY environments/record_env.py > /dev/null
$PY -W ignore -m experiments.run_priority_tests
for c in smoke solomon solomon_60s x hg1000; do
  $PY -W ignore -m experiments.run_benchmark "experiments/configs/$c.yaml"
done
$PY -m experiments.report
echo CHAIN_DONE

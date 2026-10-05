#!/usr/bin/env bash
# Fair tuning experiment (OR-Tools vs PyVRP, equal budget), see tuning.py.
# Same power guards as run_all.sh; resumable.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=./.venv/Scripts/python
[ -x "$PY" ] || PY=./.venv/bin/python
CHECK="$PY -m experiments.standby_check"
now() { date +%Y-%m-%dT%H:%M:%S; }

run_guarded() {  # run configs, then redo runs that hit standby/battery
  local start=$(now)
  for round in 1 2 3; do
    for c in "$@"; do
      $CHECK wait-ac
      $PY -W ignore -m experiments.run_benchmark "experiments/configs/$c.yaml"
    done
    N=$($CHECK runs --since "$start" --delete "$@" | tail -1)
    echo "round $round: $N runs hit standby/battery and were deleted"
    [ "$N" = "0" ] && break
  done
}

$PY -m experiments.tuning sample
run_guarded tune_train
$PY -m experiments.tuning select
run_guarded tune_test_solomon tune_test_x tune_test_hg
$PY -m experiments.tuning compare
echo TUNING_DONE

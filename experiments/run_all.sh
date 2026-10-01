#!/usr/bin/env bash
# Full Phase 0 run: environment snapshot, strict-priority experiments, then
# every benchmark config, then plots. Resumable: finished benchmark runs are
# skipped on restart.
#
# Power guards (plan §3): every phase waits for AC power; a priority pass that
# overlapped Windows standby or battery is repeated; benchmark runs that did
# are deleted by standby_check and redone by a further resume pass.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=./.venv/Scripts/python
[ -x "$PY" ] || PY=./.venv/bin/python
CHECK="$PY -m experiments.standby_check"
CONFIGS="smoke solomon solomon_tf_cold solomon_60s x hg1000 hg1000_fleet"
now() { date +%Y-%m-%dT%H:%M:%S; }

START=$(now)
echo "chain start $START"
$CHECK wait-ac
$PY environments/record_env.py > /dev/null

# Timefold: 2 s JIT warm-up per JVM in the (2 s) priority runs.
for attempt in 1 2 3; do
  $CHECK wait-ac
  T=$(now)
  ROB_TIMEFOLD_WARMUP_S=2 $PY -W ignore -m experiments.run_priority_tests
  if [ "$($CHECK window --since "$T")" = "0" ]; then break; fi
  echo "priority pass $attempt overlapped standby/battery: repeating"
done

for round in 1 2 3; do
  for c in $CONFIGS; do
    $CHECK wait-ac
    $PY -W ignore -m experiments.run_benchmark "experiments/configs/$c.yaml"
  done
  N=$($CHECK runs --since "$START" --delete $CONFIGS | tail -1)
  echo "round $round: $N runs hit standby/battery and were deleted"
  [ "$N" = "0" ] && break
done

$PY environments/record_env.py > /dev/null
$PY -m experiments.report
echo CHAIN_DONE

@echo off
rem Final Voi batch (empty PyVRP start, v3 stage rule, committed-leg snapshot).
cd /d %~dp0..
set PY=.venv\Scripts\python.exe -u
echo === V3 re-planning ===
%PY% -m rich.dynamic
echo === main final ===
%PY% -m rich.run_experiment --tag _final --arms pyvrp:weighted,pyvrp_nosoft:weighted,pyvrp:sequential,pyvrp:sequential_full,pyvrp:sequential_full_v2,pyvrp:sequential_full_v1,pyvrp_nosoft:sequential_full,ortools:weighted,ortools:sequential,ortools:sequential_full
echo === V2 budget and scale (PyVRP rerun) ===
%PY% -m rich.run_experiment --sizes S M L --instances 3 --budgets 15 60 240 --seeds 2 --arms pyvrp:sequential_full,pyvrp:weighted,ortools:sequential_full --tag _scale
echo === V4 robustness (PyVRP rerun) ===
%PY% -m rich.robust
echo VOI_FOLLOWUPS2_DONE

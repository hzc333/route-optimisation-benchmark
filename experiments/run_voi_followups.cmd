@echo off
rem Voi rich-instance studies, run detached (see HANDOFF: WMI launch).
cd /d %~dp0..
set PY=.venv\Scripts\python.exe -u
echo === main (fixed sequential arms) ===
%PY% -m rich.run_experiment
echo === V2 budget and scale ===
%PY% -m rich.run_experiment --sizes S M L --instances 3 --budgets 15 60 240 --seeds 2 --arms pyvrp:sequential_full,pyvrp:weighted,ortools:sequential_full --tag _scale
echo === V3 re-planning ===
%PY% -m rich.dynamic
echo === V4 robustness ===
%PY% -m rich.robust
echo VOI_FOLLOWUPS_DONE

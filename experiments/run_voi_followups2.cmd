@echo off
rem Second batch: re-planning (after the trip-load fix) and the v3 sequential arms.
cd /d %~dp0..
set PY=.venv\Scripts\python.exe -u
echo === V3 re-planning ===
%PY% -m rich.dynamic
echo === main (v3 sequential arms) ===
%PY% -m rich.run_experiment
echo VOI_FOLLOWUPS2_DONE

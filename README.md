# Route Optimisation Engine — Algorithm Track

Solver evaluation for the Route Optimisation Engine (Stockholm; first vertical:
Voi e-scooter battery swaps). The repository compares OR-Tools, PyVRP, VROOM
and Timefold on standard benchmarks and on a Voi-style working day, tests how
strict priorities and time-dependent traffic can be modelled, and prepares the
hand-off to the road engine (Valhalla).

中文说明：主报告是 [docs/Phase0_Algorithm_Report_CN.md](docs/Phase0_Algorithm_Report_CN.md)，
开发笔记与踩坑记录是 [docs/DEV_NOTES_CN.md](docs/DEV_NOTES_CN.md)。

## Findings in brief

| Question | Answer | Evidence |
|---|---|---|
| Which core solver? | **PyVRP.** Best quality everywhere: 1.3 % from the best known solution on 1,000-stop instances (VROOM 21 %, OR-Tools 33 %, Timefold CE 133 %). On a Voi-style day it expresses every constraint: 5 natively, 4 through tested workarounds | 9,000 benchmark runs; Voi study, report §6 |
| Strict priorities? | Not with "~10× penalties per class". An external **staged controller** (solve one class at a time, lock it, warm-start the next, keep lower classes in every stage) never gave up a CRITICAL or HIGH job that could be served | Report §4, §6.3 |
| Traffic inside the search? | Yes, with PyVRP: **one copy of each stop per 90-minute time slot**, legs at the slowest time in the slot. 100 % of plans on time with no extra driving (synthetic traffic) | Report §5, §5.1 |
| Learned / hybrid methods? | Not tested yet | — |

Open points: driver breaks and plan stability during mid-shift re-planning,
real Stockholm road and traffic data, a time buffer calibrated on real data.

## Documents

| File | Content |
|---|---|
| [docs/Phase0_Algorithm_Report_CN.md](docs/Phase0_Algorithm_Report_CN.md) | Full report (Chinese): setup, every result table, limitations, reproduction |
| [docs/Algorithm_Track_Findings_EN.md](docs/Algorithm_Track_Findings_EN.md) | Short findings summary in English (12 Oct 2026; before the Voi follow-up studies) |
| [docs/viz/](docs/viz/README.md) | Interactive step-by-step walkthrough of the traffic and Voi computations, Chinese and English; open `walkthrough_en.html` in a browser |
| [docs/DEV_NOTES_CN.md](docs/DEV_NOTES_CN.md) | Development notes (Chinese): structure, status, next steps, pitfalls |
| [docs/background/](docs/background/) | Project idea document and the benchmark plan |
| [roads/README.md](roads/README.md) | Hand-off to the road engine: stop lists and a Valhalla matrix builder |

## Repository layout

```
schema/        Shared Problem / Solution model for standard VRPs (pydantic)
evaluator/     Independent validator: re-simulates every route, never trusts solver output
adapters/      OR-Tools, PyVRP, VROOM (pyvroom) and Timefold (Java, adapters/timefold_java)
priority/      Strict-priority strategies: weighted, stacked, staged (sequential)
experiments/   Benchmark runner, tuning, standby/power guards, plots, walkthrough data export
traffic/       Time-dependent travel model, synthetic city, traffic strategies, time-slot copies
rich/          Voi-style instances: rich schema and validator, Stockholm generator,
               PyVRP / OR-Tools models, staged controller, re-planning, robustness studies
roads/         Road-engine hand-off: stop lists, Valhalla matrix builder, loader, checks
data/          Download / conversion scripts, converted instances, best known solutions
results/       Summary CSVs and plots of every experiment (raw per-run logs are not kept)
tests/         358 tests
docs/          Report, notes, walkthrough pages, background documents
environments/  Pinned Python requirements, Java environment helper, machine snapshot
```

## Setup

Python 3.13 (tested on Windows 11; the solvers also install on Linux and macOS):

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r environments/requirements-python.txt   # Linux/macOS: .venv/bin/python
.venv/Scripts/python -m pytest
```

Timefold needs JDK 21 and Maven 3.9 (only for the Timefold adapter and the
experiments that use it):

```bash
source environments/java_env.sh            # uses ../tools/jdk-21*, apache-maven-* if present
(cd adapters/timefold_java && mvn -q package)
```

Standard benchmark instances are downloaded and converted with
`python -m data.download`; converted instances are already in `data/converted/`.

## Running

All commands run from the repository root.

| What | Command | Time |
|---|---|---|
| Tests | `python -m pytest` | ~3.5 min |
| Standard benchmarks + priority experiments | `bash experiments/run_all.sh` | ~12 h |
| Traffic experiment (report §5) | `python -m traffic.run_experiment` | ~80 min |
| Time-slot copies (report §5.1) | `python -m traffic.run_experiment --tag _buckets --combos pyvrp:bucketed_90,pyvrp:bucketed_60,ortools:bucketed_90,ortools:bucketed_60,pyvrp:static_mean,pyvrp:static_peak,pyvrp:iterative,timefold:td_search` | ~60 min |
| Voi quality and priorities (§6.3) | `python -m rich.run_experiment --tag _final` | ~75 min |
| Voi budget and scale (§6.5) | `python -m rich.run_experiment --sizes S M L --instances 3 --budgets 15 60 240 --seeds 2 --arms pyvrp:sequential_full,pyvrp:weighted,ortools:sequential_full --tag _scale` | ~60 min |
| Voi re-planning (§6.4) | `python -m rich.dynamic` | ~15 min |
| Voi execution uncertainty (§6.6) | `python -m rich.robust` | ~10 min |
| Voi with real road matrices | `python -m rich.run_experiment --matrices roads/exchange/results --sizes S M --instances 1` | ~30 min |
| Walkthrough pages | `python -m experiments.export_viz` then `python -m experiments.build_viz` | ~5 min |

Quick demos (a few minutes, results kept separate):

```bash
python -m traffic.run_experiment --combos pyvrp:static_mean,pyvrp:bucketed_90 --seeds 0 --time-limit 10 --tag _demo
python -m rich.run_experiment --sizes S --instances 1 --seeds 1 --arms pyvrp:sequential_full,pyvrp:weighted --tag _demo
```

Runners journal every finished run and resume after an interruption; rerun
with a new `--tag` to start from scratch. Summaries land in `results/summary/`.

### Measurement conditions

Timed runs are single-threaded and pinned to fixed performance cores (CPUs
0, 2, 4, 6 of an i5-13500H; edit `CPUS` in the runners for another machine).
On Windows, runs that overlap a Modern Standby period or battery power are
detected from the event log and redone (`experiments/standby_check.py`); on
other systems that check is skipped. Compare configurations only within runs
made on the same day: results drift by 0.1–5 percentage points between days.

## Limitations

Single laptop; the Voi day and the traffic model are synthetic (real Stockholm
coordinates, but straight-line distances times a detour factor until the road
engine provides matrices); learned methods are not evaluated.

# Route Optimisation Engine — Algorithm Track

This folder is the **Algorithm Track** of the Route Optimisation Engine project
(Stockholm; first vertical: Voi e-scooter battery swaps). It answers which
solver should plan the routes and how priorities and traffic are modelled:
it compares OR-Tools, PyVRP, VROOM and Timefold on standard benchmarks and on
a Voi-style working day, and tests strict priorities and time-dependent
traffic.

**How it connects to the road engine:** the algorithm takes travel-time and
distance matrices between stops and returns each vehicle's ordered stops and
schedule. The road engine (Valhalla) supplies those matrices and turns the
stop order into driving routes. Until that link is live, the matrices are
exchanged as files; see [roads/README.md](roads/README.md).

Everything below is relative to this folder, and every command runs from it.

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
| [docs/Phase0_Algorithm_Report_EN.md](docs/Phase0_Algorithm_Report_EN.md) | **Full report**: setup, every result table (standard benchmarks, priorities, traffic, Voi studies), engineering findings, recommendations, limitations, reproduction |
| [docs/Phase0_Algorithm_Report_CN.md](docs/Phase0_Algorithm_Report_CN.md) | The same report in Chinese (the original) |
| [docs/viz/](docs/viz/README.md) | Interactive step-by-step walkthrough of the traffic and Voi computations, Chinese and English; open `walkthrough_en.html` in a browser |
| [docs/DEV_NOTES_CN.md](docs/DEV_NOTES_CN.md) | Development notes (Chinese): structure, status, next steps, pitfalls |
| [docs/background/](docs/background/) | Project idea document (Markdown and the original PDF) and the benchmark plan |
| [roads/README.md](roads/README.md) | Hand-off to the road engine: stop lists and a Valhalla matrix builder |
| [notes/](notes/README.md) | Working notes: hand-off, map-solver bridge meeting prep, short findings |

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
docs/          Reports, notes, walkthrough pages, background documents
environments/  Pinned Python requirements, Java environment helper, machine snapshot
notes/         Working notes: hand-off, meeting prep, short findings
```

## Setup

Python 3.13 (developed on Windows 11; everything is plain Python and also runs
on Ubuntu). Create a virtual environment in this folder and activate it:

```bash
python -m venv .venv
source .venv/Scripts/activate        # Windows Git Bash; Linux/macOS: source .venv/bin/activate
                                     # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r environments/requirements-python.txt
python -m pytest                     # about 1.5 minutes
```

Tests that need the Timefold jar are skipped until it is built (below), and the
216 best-known-solution checks are skipped until `python -m data.download` has run;
with both in place there are 358 tests.

All later commands assume the environment is active, so `python` is the
environment's Python.

Timefold needs JDK 21 and Maven 3.9 (only for the Timefold adapter and the
experiments that use it):

```bash
source environments/java_env.sh            # PowerShell: . .\environments\java_env.ps1
(cd adapters/timefold_java && mvn -q package)
```

The helper uses a JDK and Maven already on `PATH`, or portable copies
(`jdk-21*`, `apache-maven-*`) in the folder named by `ROUTE_OPTI_TOOLS`
(default: a `tools` folder next to this one).

Standard benchmark instances are downloaded and converted with
`python -m data.download`; converted instances are already in `data/converted/`.

### On Ubuntu

```bash
sudo apt install git openjdk-21-jdk maven      # Java only for Timefold
git clone <this repository> && cd route-optimisation-benchmark
# Python 3.13: if `python3.13` is missing, install it from the deadsnakes PPA
# (sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt install python3.13 python3.13-venv)
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r environments/requirements-python.txt
python -m pytest
```

Commands written as `.venv/Scripts/python` in the docs are `.venv/bin/python`
on Ubuntu (or just `python` with the environment active). Set
`ROUTE_OPTI_CPUS` to the cores the timed runs should use (see Measurement
conditions).

## Running

All commands run from this folder with the virtual environment active.

| What | Command | Time |
|---|---|---|
| Tests | `python -m pytest` | 1.5–3.5 min |
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
0, 2, 4, 6 of an i5-13500H). On another machine set `ROUTE_OPTI_CPUS`, e.g.
`export ROUTE_OPTI_CPUS=0,1,2,3`; cores the machine lacks are dropped.
On Windows, runs that overlap a Modern Standby period or battery power are
detected from the event log and redone (`experiments/standby_check.py`); on
other systems that check is skipped. Compare configurations only within runs
made on the same day: results drift by 0.1–5 percentage points between days.

## Limitations

Single laptop; the Voi day and the traffic model are synthetic (real Stockholm
coordinates, but straight-line distances times a detour factor until the road
engine provides matrices); learned methods are not evaluated.

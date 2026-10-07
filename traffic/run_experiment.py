"""Traffic experiment (Q3): does traffic belong inside the search?

    python -m traffic.run_experiment [--time-limit 30] [--seeds 0 1 2]

Every (solver, strategy) plans each instance with the same total budget;
traffic.evaluate.simulate scores the plan under time-dependent traffic.
Runs are pinned to P-cores, pause while on battery, and any run that
overlaps a Windows standby is redone (experiments.standby_check). Every
finished run is appended to results/raw/traffic<tag>.jsonl, so a restart
resumes instead of starting over.
Outputs results/summary/traffic_runs.csv and traffic_summary.csv.
"""

from __future__ import annotations

import argparse
import datetime as dt
import itertools
import json
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import psutil

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "results" / "summary"
RAW = ROOT / "results" / "raw"
CPUS = [0, 2, 4, 6]
INSTANCES = [f"{lv}{k:02d}" for lv in ("T", "H") for k in range(10)]
COMBOS = [("pyvrp", "static_free"), ("pyvrp", "static_mean"), ("pyvrp", "static_peak"),
          ("pyvrp", "iterative"), ("ortools", "static_mean"), ("ortools", "iterative"),
          ("timefold", "static_mean"), ("timefold", "iterative"), ("timefold", "td_search")]
# Timefold's priority-aware sorted construction is for priority instances;
# here every job is required and NORMAL (see adapters/timefold_adapter.py).
SOLVER_OPTIONS = {"timefold": {"construction": "default"}}


def run_one(args) -> dict:
    instance, solver, strategy, seed, time_limit, cpu = args
    psutil.Process().cpu_affinity([cpu])
    from adapters import get_adapter
    from experiments.run_benchmark import wait_for_ac

    from .evaluate import simulate
    from .instances import load
    from .strategies import STRATEGIES

    wait_for_ac()
    problem, td = load(instance)
    row = {"instance": instance, "level": instance[0], "solver": solver, "strategy": strategy,
           "seed": seed, "time_limit_s": time_limit, "t_start": time.time()}
    t0 = time.perf_counter()
    try:
        sol, extra = STRATEGIES[strategy](get_adapter(solver), problem, td, time_limit_s=time_limit,
                                          seed=seed, **SOLVER_OPTIONS.get(solver, {}))
        if isinstance(extra, dict):  # time-slot plan (traffic.bucketed)
            row |= simulate(problem, td, sol, min_start=extra["min_start"])
            row["planned_travel_s"] = extra["planned_travel_s"]
        else:
            row |= simulate(problem, td, sol, extra)
        row["status"] = sol.status.value
    except Exception as exc:  # recorded, never dropped
        row |= {"status": "ERROR", "valid": False, "notes": f"{type(exc).__name__}: {exc}"[:300]}
    battery = psutil.sensors_battery()
    row |= {"wall_s": time.perf_counter() - t0, "t_end": time.time(),
            "on_ac": battery is None or battery.power_plugged}
    return row


KEY = ["instance", "solver", "strategy", "seed", "time_limit_s"]


def run_all(jobs: list[tuple], journal: Path) -> None:
    """Run jobs, appending each finished row to the JSONL journal at once, so
    an interrupted experiment loses at most the runs in flight."""
    tagged = [j + (CPUS[i % len(CPUS)],) for i, j in enumerate(jobs)]
    with ProcessPoolExecutor(len(CPUS)) as pool, open(journal, "a", encoding="utf-8") as fh:
        futures = [pool.submit(run_one, t) for t in tagged]
        for n, fut in enumerate(as_completed(futures), start=1):
            fh.write(json.dumps(fut.result(), default=str) + "\n")
            fh.flush()
            if n % 20 == 0 or n == len(futures):
                print(f"{n}/{len(futures)} runs", flush=True)


def load_journal(journal: Path) -> pd.DataFrame:
    if not journal.exists():
        return pd.DataFrame(columns=KEY)
    rows = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines() if line]
    return pd.DataFrame(rows).drop_duplicates(KEY, keep="last").reset_index(drop=True)


def contaminated(df: pd.DataFrame, since: dt.datetime) -> pd.Series:
    from experiments.standby_check import standby_intervals

    intervals = standby_intervals(since)
    hit = df.apply(lambda r: any(a <= r.t_end and r.t_start - 5 <= b for a, b in intervals), axis=1)
    return hit | ~df.on_ac.astype(bool)


def summarise(df: pd.DataFrame) -> pd.DataFrame:
    ok = df[df.valid.astype(bool)].copy()
    # Paired with PyVRP + day-average matrix on the same instance and seed.
    ref = ok[(ok.solver == "pyvrp") & (ok.strategy == "static_mean")].set_index(
        ["instance", "seed"]).travel_time_s
    ok["travel_vs_ref_pct"] = [(t / ref[(i, s)] - 1) * 100 if (i, s) in ref.index else float("nan")
                               for i, s, t in zip(ok.instance, ok.seed, ok.travel_time_s)]
    ok["planning_error_pct"] = [(p / t - 1) * 100 if p else float("nan")
                                for p, t in zip(ok.planned_travel_s, ok.travel_time_s)]
    g = ok.groupby(["level", "solver", "strategy"])
    out = g.agg(runs=("seed", "size"), on_time=("on_time", "mean"),
                late_jobs=("late_jobs", "mean"), lateness_min=("lateness_s", lambda s: s.mean() / 60),
                overtime_min=("overtime_s", lambda s: s.mean() / 60),
                travel_h=("travel_time_s", lambda s: s.mean() / 3600),
                travel_vs_ref_pct=("travel_vs_ref_pct", "mean"),
                planning_error_pct=("planning_error_pct", "mean"),
                vehicles=("vehicles_used", "mean")).reset_index()
    invalid = df[~df.valid.astype(bool)].groupby(["level", "solver", "strategy"]).size()
    out["invalid_runs"] = [int(invalid.get((lv, so, st), 0))
                           for lv, so, st in zip(out.level, out.solver, out.strategy)]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--time-limit", type=float, default=30.0)
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    ap.add_argument("--combos", help="comma list of solver:strategy (default: the T0/T2/T3 set)")
    ap.add_argument("--tag", default="", help="suffix for output files, e.g. _buckets")
    args = ap.parse_args()
    combos = [tuple(c.split(":")) for c in args.combos.split(",")] if args.combos else COMBOS
    SUMMARY.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    journal = RAW / f"traffic{args.tag}.jsonl"
    jobs = [(inst, so, st, seed, float(args.time_limit))
            for inst, (so, st), seed in itertools.product(INSTANCES, combos, args.seeds)]
    for attempt in range(4):  # resume, then redo runs hit by standby or battery
        df = load_journal(journal)
        good = set()
        if len(df):
            since = dt.datetime.fromtimestamp(df.t_start.min() - 60).astimezone()
            bad = contaminated(df, since)
            good = {tuple(r) for r in df[~bad][KEY].itertuples(index=False)}
            print(f"pass {attempt + 1}: {len(df)} recorded, {int(bad.sum())} hit standby/battery",
                  flush=True)
        todo = [j for j in jobs if j not in good]
        if not todo:
            break
        print(f"pass {attempt + 1}: running {len(todo)} of {len(jobs)}", flush=True)
        run_all(todo, journal)
    df = load_journal(journal)
    df = df[[tuple(r) in set(jobs) for r in df[KEY].itertuples(index=False)]]
    df.to_csv(SUMMARY / f"traffic_runs{args.tag}.csv", index=False, lineterminator="\n")
    summary = summarise(df)
    summary.to_csv(SUMMARY / f"traffic_summary{args.tag}.csv", index=False, lineterminator="\n",
                   float_format="%.4f")
    with pd.option_context("display.width", 250, "display.max_columns", 30):
        print(summary.to_string(index=False, float_format=lambda x: f"{x:.3f}"), flush=True)


if __name__ == "__main__":
    main()

"""Voi-style rich instance experiment (Q1 "our constraints", Q2 on a real-ish day).

    python -m rich.run_experiment [--sizes S M] [--instances 5] [--tag ""]

Arms = solver x priority strategy (rich.priority). PyVRP runs 3 seeds, OR-Tools
one (its search is deterministic). Every plan is re-checked by rich.validate.
Runs are pinned to P-cores, pause on battery, are journalled to
results/raw/voi<tag>.jsonl (resume on restart) and redone if they overlap a
Windows standby. Outputs results/summary/voi_runs<tag>.csv and
voi_summary<tag>.csv.
"""

from __future__ import annotations

import argparse
import datetime as dt
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
TIME_LIMIT = {"S": 30.0, "M": 120.0, "L": 240.0}
# arm: (module, options, strategy, seeds)
ARMS = {
    "pyvrp:weighted": ("pyvrp", {}, "weighted", (0, 1, 2)),
    "pyvrp:sequential": ("pyvrp", {}, "sequential", (0, 1, 2)),
    "pyvrp:sequential_full": ("pyvrp", {}, "sequential_full", (0, 1, 2)),
    "pyvrp_nosoft:sequential_full": ("pyvrp", {"soft_due": "ignore"}, "sequential_full", (0, 1, 2)),
    "pyvrp_nosoft:weighted": ("pyvrp", {"soft_due": "ignore"}, "weighted", (0, 1, 2)),
    # First version: soft-deadline copies in every stage, no fallback.
    "pyvrp:sequential_v1": ("pyvrp", {"early_stage_options": {}, "fallback": False},
                            "sequential", (0, 1, 2)),
    "pyvrp:sequential_full_v1": ("pyvrp", {"early_stage_options": {}, "fallback": False},
                                 "sequential_full", (0, 1, 2)),
    "pyvrp_nosoft:sequential_full_v1": ("pyvrp", {"soft_due": "ignore", "early_stage_options": {},
                                                  "fallback": False}, "sequential_full", (0, 1, 2)),
    "ortools:weighted": ("ortools", {}, "weighted", (0,)),
    "ortools:sequential": ("ortools", {}, "sequential", (0,)),
    "ortools:sequential_full": ("ortools", {}, "sequential_full", (0,)),
}
KEY = ["instance", "arm", "seed", "time_limit_s"]
CLASSES = ["CRITICAL", "HIGH", "NORMAL", "LOW"]


def run_one(args) -> dict:
    instance, arm, seed, time_limit, cpu = args
    psutil.Process().cpu_affinity([cpu])
    from experiments.run_benchmark import wait_for_ac

    from . import ortools_rich, pyvrp_rich
    from .priority import STRATEGIES
    from .validate import validate
    from .voi import build

    wait_for_ac()
    module_name, options, strategy, _ = ARMS[arm]
    module = {"pyvrp": pyvrp_rich, "ortools": ortools_rich}[module_name]
    problem = build(instance[0], int(instance[1:]))
    row = {"instance": instance, "size": instance[0], "arm": arm, "solver": module_name,
           "strategy": strategy, "seed": seed, "time_limit_s": time_limit, "t_start": time.time()}
    t0 = time.perf_counter()
    try:
        sol = STRATEGIES[strategy](module, problem, time_limit_s=time_limit, seed=seed, **options)
        rep = validate(problem, sol)
        row |= rep.flat() | {"status": sol.status, "notes": sol.notes[:300]}
        row["violations"] = json.dumps(rep.violations)
    except Exception as exc:  # recorded, never dropped
        row |= {"status": "ERROR", "feasible": False, "notes": f"{type(exc).__name__}: {exc}"[:300]}
    battery = psutil.sensors_battery()
    row |= {"wall_s": time.perf_counter() - t0, "t_end": time.time(),
            "on_ac": battery is None or battery.power_plugged}
    return row


def run_all(jobs: list[tuple], journal: Path) -> None:
    # Longest first so the pool drains evenly.
    jobs = sorted(jobs, key=lambda j: -j[3])
    tagged = [j + (CPUS[i % len(CPUS)],) for i, j in enumerate(jobs)]
    with ProcessPoolExecutor(len(CPUS)) as pool, open(journal, "a", encoding="utf-8") as fh:
        futures = [pool.submit(run_one, t) for t in tagged]
        for n, fut in enumerate(as_completed(futures), start=1):
            fh.write(json.dumps(fut.result(), default=str) + "\n")
            fh.flush()
            if n % 10 == 0 or n == len(futures):
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
    ok = df[df.status == "SOLVED"].copy()
    prio = ["hard_violations", *[f"unserved_{c}" for c in CLASSES]]
    # Lexicographic standing per instance: does the run reach the best
    # (hard, CRITICAL, HIGH, NORMAL, LOW) vector seen on that instance by any arm?
    best = ok.groupby(["instance", "time_limit_s"])[prio].apply(lambda g: min(map(tuple, g.values)))
    ok["prio_best"] = [tuple(r) == best[(i, t)] for i, t, r in
                       zip(ok.instance, ok.time_limit_s, ok[prio].values)]
    ref = ok[ok.arm == "pyvrp:sequential_full"].groupby(["instance", "time_limit_s"]).soft_cost.mean()
    ok["soft_vs_ref_pct"] = [(c / ref[(i, t)] - 1) * 100 if (i, t) in ref.index else float("nan")
                             for i, t, c in zip(ok.instance, ok.time_limit_s, ok.soft_cost)]
    g = ok.groupby(["size", "time_limit_s", "arm"])
    out = g.agg(runs=("seed", "size"), feasible=("feasible", "mean"), prio_best=("prio_best", "mean"),
                **{f"unserved_{c}": (f"unserved_{c}", "mean") for c in CLASSES},
                served_jobs=("served_jobs", "mean"), served_shipments=("served_shipments", "mean"),
                soft_cost_k=("soft_cost", lambda s: s.mean() / 1000),
                soft_vs_ref_pct=("soft_vs_ref_pct", "mean"),
                soft_late_h=("soft_late_s", lambda s: s.mean() / 3600),
                distance_km=("distance_m", lambda s: s.mean() / 1000),
                vehicles=("vehicles_used", "mean"), reloads=("reloads", "mean"),
                wall_s=("wall_s", "mean")).reset_index()
    failed = df[df.status != "SOLVED"].groupby(["size", "time_limit_s", "arm"]).size()
    out["failed_runs"] = [int(failed.get(k, 0)) for k in
                          zip(out["size"], out.time_limit_s, out.arm)]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", nargs="+", default=["S", "M"])
    ap.add_argument("--instances", type=int, default=5)
    ap.add_argument("--arms", help="comma list (default: all)")
    ap.add_argument("--budgets", type=float, nargs="+",
                    help="time limits in s for every size (default: TIME_LIMIT per size)")
    ap.add_argument("--seeds", type=int, help="use only the first N seeds of each arm")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()
    arms = args.arms.split(",") if args.arms else list(ARMS)
    SUMMARY.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    journal = RAW / f"voi{args.tag}.jsonl"
    jobs = [(f"{size}{k:02d}", arm, seed, budget)
            for size in args.sizes for k in range(args.instances)
            for budget in (args.budgets or [TIME_LIMIT[size]])
            for arm in arms for seed in ARMS[arm][3][:args.seeds]]
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
    df.to_csv(SUMMARY / f"voi_runs{args.tag}.csv", index=False, lineterminator="\n")
    summary = summarise(df)
    summary.to_csv(SUMMARY / f"voi_summary{args.tag}.csv", index=False, lineterminator="\n",
                   float_format="%.4f")
    with pd.option_context("display.width", 250, "display.max_columns", 30):
        print(summary.to_string(index=False, float_format=lambda x: f"{x:.2f}"), flush=True)


if __name__ == "__main__":
    main()

"""V4 - does a Voi plan survive real-world variability, and how much buffer?

    python -m rich.robust [--instances 5] [--samples 300]

Plans are made on a copy of the instance whose travel and service times are
inflated by a buffer b (0 / 10 / 20 %), then scored twice on the true
instance: by rich.validate (priority vector, cost) and by Monte Carlo
execution with random travel and service times (``execute``). The driver
keeps the planned order and start time, waits for windows, and takes the
break at the planned position as early as allowed.

Noise (mean-1 lognormal factors): one per route (day-level traffic), one per
leg, one per service.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .model import RichProblem, RichSolution

ROOT = Path(__file__).resolve().parents[1]
NOISE = {"moderate": (0.10, 0.20, 0.30), "high": (0.15, 0.35, 0.50)}  # route, leg, service
BUFFERS = (0.0, 0.1, 0.2)
ARMS = {  # arm: (solver, buffers, seeds)
    "pyvrp:sequential_full": ("pyvrp", BUFFERS, (0, 1)),
    "ortools:sequential_full": ("ortools", (0.0, 0.1), (0,)),
}
TIME_LIMIT = 60.0
KEY = ["instance", "arm", "buffer", "seed", "time_limit_s"]


def buffered(problem: RichProblem, b: float) -> RichProblem:
    if not b:
        return problem
    f = 1 + b
    profiles = {k: p.model_copy(update={"duration_matrix": [[int(x * f) for x in row]
                                                            for row in p.duration_matrix]})
                for k, p in problem.profiles.items()}
    jobs = [j.model_copy(update={"service": int(j.service * f)}) for j in problem.jobs]
    ships = [s.model_copy(update={
        "pickup": s.pickup.model_copy(update={"service": int(s.pickup.service * f)}),
        "delivery": s.delivery.model_copy(update={"service": int(s.delivery.service * f)})})
        for s in problem.shipments]
    return problem.model_copy(update={"profiles": profiles, "jobs": jobs, "shipments": ships})


def _lognormal(rng, sigma, size):
    return rng.lognormal(-sigma**2 / 2, sigma, size)


def execute(problem: RichProblem, solution: RichSolution, samples: int, noise: tuple,
            seed: int = 0, return_samples: bool = False) -> dict:
    """Monte Carlo execution of a plan; returns on-time probability and means."""
    s_route, s_leg, s_service = noise
    rng = np.random.default_rng(seed)
    jobs = {j.id: j for j in problem.jobs}
    ships = {s.id: s for s in problem.shipments}
    hubs = {h.id: h for h in problem.hubs}
    vehicles = {v.id: v for v in problem.vehicles}
    late_jobs = np.zeros(samples)
    overtime = np.zeros(samples)
    bad_break = np.zeros(samples)
    for route in solution.routes:
        if not route.visits:
            continue
        veh = vehicles[route.vehicle_id]
        dur = problem.profiles[veh.profile].duration_matrix
        stops = []  # (location, service, window)
        for v in route.visits:
            if v.kind == "reload":
                stops.append((hubs[v.id].location, hubs[v.id].service, None))
            elif v.kind == "job":
                j = jobs[v.id]
                stops.append((j.location, j.service, j.time_window))
            else:
                st = ships[v.id].pickup if v.kind == "pickup" else ships[v.id].delivery
                stops.append((st.location, st.service, st.time_window))
        locs = [hubs[veh.start_hub].location, *(s[0] for s in stops), hubs[veh.end_hub].location]
        base = np.array([dur[a][b] for a, b in zip(locs, locs[1:])], dtype=float)
        legs = base * _lognormal(rng, s_leg, (samples, len(base))) \
            * _lognormal(rng, s_route, (samples, 1))
        services = np.array([s[1] for s in stops], dtype=float) \
            * _lognormal(rng, s_service, (samples, len(stops)))
        t = np.full(samples, float(route.start_time if route.start_time is not None
                                   else veh.shift[0]) + hubs[veh.start_hub].service)
        rest = route.rest if veh.rest is not None else None
        for k in range(len(stops) + 1):
            if rest is not None and rest.position == k:
                start = np.maximum(t, veh.rest.earliest)
                bad_break += start > veh.rest.latest
                t = np.maximum(t + legs[:, k], start) + veh.rest.duration
            else:
                t = t + legs[:, k]
            if k == len(stops):
                break
            window = stops[k][2]
            if window:
                t = np.maximum(t, window[0])
                late_jobs += t > window[1]
            t = t + services[:, k]
        overtime += np.maximum(0, t - veh.shift[1])
    ok = (late_jobs == 0) & (overtime == 0) & (bad_break == 0)
    extra = ({"samples_late": late_jobs.tolist(), "samples_overtime_min": (overtime / 60).tolist()}
             if return_samples else {})
    return extra | {"on_time_prob": float(ok.mean()), "late_hard_mean": float(late_jobs.mean()),
            "overtime_min_mean": float(overtime.mean() / 60),
            "overtime_min_p95": float(np.percentile(overtime, 95) / 60),
            "break_late_prob": float((bad_break > 0).mean())}


def run_one(args) -> dict:
    instance, arm, b, seed, time_limit, samples, cpu = args
    from . import journal, ortools_rich, pyvrp_rich
    from .priority import STRATEGIES
    from .validate import validate
    from .voi import build

    journal.pin(cpu)
    module = {"pyvrp": pyvrp_rich, "ortools": ortools_rich}[ARMS[arm][0]]
    problem = build(instance[0], int(instance[1:]))
    row = journal.start_row(instance=instance, arm=arm, buffer=b, seed=seed,
                            time_limit_s=time_limit)
    t0 = time.perf_counter()
    try:
        sol = STRATEGIES["sequential_full"](module, buffered(problem, b),
                                            time_limit_s=time_limit, seed=seed)
        rep = validate(problem, sol)
        row |= rep.flat() | {"status": sol.status, "violations": json.dumps(rep.violations)}
        for name, noise in NOISE.items():
            row |= {f"{name}_{k}": v for k, v in
                    execute(problem, sol, samples, noise, seed=1000 + seed).items()}
        row["plan"] = sol.model_dump_json(include={"routes"})
    except Exception as exc:
        row |= {"status": "ERROR", "notes": f"{type(exc).__name__}: {exc}"[:300]}
    return journal.finish_row(row, t0)


def summarise(df: pd.DataFrame) -> pd.DataFrame:
    ok = df[df.status == "SOLVED"].copy()
    cols = {c: (c, "mean") for c in ok.columns
            if c.startswith(("moderate_", "high_")) or c.startswith("unserved_")}
    return ok.groupby(["arm", "buffer"]).agg(
        runs=("seed", "size"), feasible=("feasible", "mean"),
        served_jobs=("served_jobs", "mean"), soft_cost_k=("soft_cost", lambda s: s.mean() / 1000),
        **cols).reset_index()


def main() -> None:
    from .journal import run_guarded

    ap = argparse.ArgumentParser()
    ap.add_argument("--instances", type=int, default=5)
    ap.add_argument("--samples", type=int, default=300)
    ap.add_argument("--tag", default="")
    args = ap.parse_args()
    jobs = [(f"M{k:02d}", arm, b, seed, TIME_LIMIT, args.samples)
            for k in range(args.instances) for arm, (_, bufs, seeds) in ARMS.items()
            for b in bufs for seed in seeds]
    df = run_guarded(jobs, run_one, ROOT / "results" / "raw" / f"voi_robust{args.tag}.jsonl",
                     KEY, budget_index=4)
    out = ROOT / "results" / "summary"
    df.drop(columns=["plan"], errors="ignore").to_csv(
        out / f"voi_robust_runs{args.tag}.csv", index=False, lineterminator="\n")
    summary = summarise(df)
    summary.to_csv(out / f"voi_robust_summary{args.tag}.csv", index=False,
                   lineterminator="\n", float_format="%.4f")
    with pd.option_context("display.width", 250, "display.max_columns", 40):
        print(summary.to_string(index=False, float_format=lambda x: f"{x:.3f}"), flush=True)


if __name__ == "__main__":
    main()

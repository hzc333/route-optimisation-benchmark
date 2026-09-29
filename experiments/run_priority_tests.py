"""Strict-priority experiments (plan §14).

    python -m experiments.run_priority_tests [--quick]

Part 1 - counterexamples P1-P4 with a known strict-optimal unserved vector.
Part 2 - random stress instances (tight capacity, mixed classes): each
         strategy's priority vector vs the lexicographically best vector found
         by any strategy/solver/seed on that instance.

Every run is re-scored by the shared validator; the "priority vector" is
(hard_violations, unserved_critical, unserved_high, unserved_normal,
unserved_low). Outputs go to results/summary/priority_*.csv.
"""

from __future__ import annotations

import argparse
import itertools
import math
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import psutil

from schema.models import Job, Location, PriorityClass, Problem, Vehicle

C, H, N, L = (PriorityClass.CRITICAL, PriorityClass.HIGH,
              PriorityClass.NORMAL, PriorityClass.LOW)
SUMMARY = Path(__file__).resolve().parents[1] / "results" / "summary"
PRIO_FIELDS = ["hard_violations", "unserved_critical", "unserved_high",
               "unserved_normal", "unserved_low"]
SOLVERS = ["ortools", "pyvrp"]
CPUS = [0, 2, 4, 6]


def _problem(name, coords, jobs, vehicles) -> Problem:
    pts = np.asarray(coords, dtype=float)
    diff = pts[:, None, :] - pts[None, :, :]
    m = np.rint(np.hypot(diff[..., 0], diff[..., 1])).astype(int).tolist()
    return Problem(name=name, locations=[Location(id=str(i), x=x, y=y) for i, (x, y) in enumerate(coords)],
                   depot=0, vehicles=vehicles, jobs=jobs, distance_matrix=m, duration_matrix=m)


# ---------------------------------------------------------------- P1-P4 ---

def case_p1() -> tuple[Problem, tuple]:
    """1 HIGH vs 20 NORMAL; capacity serves exactly one side."""
    coords = [(0, 0), (100, 0)] + [(-100, k) for k in range(20)]
    jobs = [Job(id="high", location=1, demand=20, required=False, priority_class=H)]
    jobs += [Job(id=f"n{k}", location=k + 2, demand=1, required=False, priority_class=N)
             for k in range(20)]
    return _problem("P1_high_vs_20_normal", coords, jobs, [Vehicle(id="v0", capacity=20)]), \
        (0, 0, 0, 20, 0)


def case_p2() -> tuple[Problem, tuple]:
    """A CRITICAL job 60 km away (distances in metres) plus nearby NORMAL jobs."""
    coords = [(0, 0), (60_000, 0)] + [(500 * (k + 1), 300) for k in range(5)]
    jobs = [Job(id="crit", location=1, demand=1, required=False, priority_class=C)]
    jobs += [Job(id=f"n{k}", location=k + 2, demand=1, required=False, priority_class=N)
             for k in range(5)]
    return _problem("P2_far_critical", coords, jobs, [Vehicle(id="v0", capacity=10)]), \
        (0, 0, 0, 0, 0)


def case_p3() -> tuple[Problem, tuple]:
    """CRITICAL fixed; within HIGH serve far A (value 5) over near B+C (1 each)."""
    coords = [(0, 0), (0, 50), (0, -400), (10, 10), (-10, 10)]
    jobs = [Job(id="crit", location=1, demand=10, required=False, priority_class=C),
            Job(id="A", location=2, demand=10, required=False, priority_class=H, value=5),
            Job(id="B", location=3, demand=5, required=False, priority_class=H),
            Job(id="C", location=4, demand=5, required=False, priority_class=H)]
    return _problem("P3_value_within_high", coords, jobs, [Vehicle(id="v0", capacity=20)]), \
        (0, 0, 2, 0, 0)


def case_p4() -> tuple[Problem, tuple]:
    """Serving the last NORMAL job needs a 2nd vehicle with a huge fixed cost."""
    coords = [(0, 0)] + [(100, 10 * k) for k in range(5)]
    jobs = [Job(id=f"n{k}", location=k + 1, demand=4, required=False, priority_class=N)
            for k in range(5)]
    vehicles = [Vehicle(id=f"v{k}", capacity=16, fixed_cost=1_000_000) for k in range(2)]
    return _problem("P4_softcost_vs_one_normal", coords, jobs, vehicles), (0, 0, 0, 0, 0)


CASES = [case_p1, case_p2, case_p3, case_p4]


# ------------------------------------------------------- random stress ---

def random_instance(seed: int, n: int = 60) -> Problem:
    """Capacity for ~2/3 of the demand; classes 10/20/40/30 % C/H/N/L."""
    rng = np.random.default_rng(10_000 + seed)
    coords = [(500, 500)] + [tuple(p) for p in rng.integers(0, 1001, size=(n, 2))]
    order = [C, H, N, L]
    classes = [order[k] for k in rng.choice(4, size=n, p=[0.1, 0.2, 0.4, 0.3])]
    demand = rng.integers(1, 6, size=n)
    n_veh = 3
    cap = int(math.ceil(demand.sum() * 0.66 / n_veh))
    jobs = [Job(id=f"j{i}", location=i + 1, demand=int(demand[i]), required=False,
                priority_class=classes[i]) for i in range(n)]
    return _problem(f"R{seed:02d}", coords, jobs,
                    [Vehicle(id=f"v{k}", capacity=cap) for k in range(n_veh)])


# ------------------------------------------------------------- running ---

def run_one(args) -> dict:
    kind, builder_arg, solver, strategy, seed, time_limit, cpu = args
    psutil.Process().cpu_affinity([cpu])
    from adapters import get_adapter
    from evaluator import objective_vector, validate
    from priority import STRATEGIES

    problem, expected = (CASES[builder_arg]() if kind == "case"
                         else (random_instance(builder_arg), None))
    row = {"kind": kind, "instance": problem.name, "solver": solver, "strategy": strategy,
           "seed": seed, "time_limit_s": time_limit}
    try:
        sol = STRATEGIES[strategy](get_adapter(solver), problem, time_limit_s=time_limit, seed=seed)
    except OverflowError as exc:
        return row | {"status": "OVERFLOW", "feasible": False, "notes": str(exc)}
    rep = validate(problem, sol)
    vec = objective_vector(problem, rep)
    row |= {"status": sol.status.value, "feasible": rep.feasible, **vec, "notes": sol.notes}
    if expected is not None:
        row["expected"] = str(expected)
        row["strict_ok"] = tuple(vec[f] for f in PRIO_FIELDS) == expected
    return row


def run_all(jobs: list[tuple]) -> pd.DataFrame:
    tagged = [j + (CPUS[i % len(CPUS)],) for i, j in enumerate(jobs)]
    with ProcessPoolExecutor(len(CPUS)) as pool:
        return pd.DataFrame(pool.map(run_one, tagged, chunksize=1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="fewer seeds/instances")
    ap.add_argument("--time-limit", type=float, default=2.0)
    args = ap.parse_args()
    from priority import STRATEGIES

    seeds = range(2 if args.quick else 5)
    n_random = 6 if args.quick else 30
    tl = args.time_limit
    SUMMARY.mkdir(parents=True, exist_ok=True)

    cases = run_all([("case", i, s, st, seed, tl) for i, s, st, seed in
                     itertools.product(range(len(CASES)), SOLVERS, STRATEGIES, seeds)])
    cases.to_csv(SUMMARY / "priority_cases.csv", index=False, lineterminator="\n")
    table = cases.pivot_table(index=["instance", "solver"], columns="strategy",
                              values="strict_ok", aggfunc="mean")
    print("Share of runs matching the strict-optimal unserved vector:")
    print(table.to_string(float_format=lambda x: f"{x:.0%}"))

    rnd = run_all([("random", k, s, st, seed, tl) for k, s, st, seed in
                   itertools.product(range(n_random), SOLVERS, STRATEGIES, seeds)])
    ok = rnd[rnd.feasible]
    best = ok.groupby("instance")[PRIO_FIELDS].apply(lambda g: min(map(tuple, g.to_numpy())))
    rnd["best_vector"] = rnd.instance.map(best).astype(str)
    rnd["vector"] = rnd[PRIO_FIELDS].apply(tuple, axis=1).astype(str)
    rnd["lex_best"] = rnd.feasible & (rnd.vector == rnd.best_vector)
    # Priority inversion: worse than best at the first differing class, i.e.
    # a more important job was given up; report which class it happened at.
    def first_worse(row):
        if not row.feasible:
            return "infeasible"
        for f, b in zip(PRIO_FIELDS, best[row.instance]):
            if row[f] != b:
                return f.replace("unserved_", "") if row[f] > b else "better?"
        return ""
    rnd["first_worse_class"] = rnd.apply(first_worse, axis=1)
    rnd.to_csv(SUMMARY / "priority_random.csv", index=False, lineterminator="\n")

    summary = rnd.groupby(["solver", "strategy"]).agg(
        runs=("seed", "size"), feasible=("feasible", "mean"), lex_best=("lex_best", "mean"),
        worse_at_critical=("first_worse_class", lambda s: (s == "critical").mean()),
        worse_at_high=("first_worse_class", lambda s: (s == "high").mean()),
        worse_at_normal=("first_worse_class", lambda s: (s == "normal").mean()),
        worse_at_low=("first_worse_class", lambda s: (s == "low").mean()),
        mean_unserved_critical=("unserved_critical", "mean"),
        mean_unserved_high=("unserved_high", "mean"),
        mean_distance=("distance", "mean"),
    ).reset_index()
    summary.to_csv(SUMMARY / "priority_random_summary.csv", index=False,
                   lineterminator="\n", float_format="%.4f")
    print("\nRandom stress (share of runs):")
    print(summary.to_string(index=False, float_format=lambda x: f"{x:.3f}"))


if __name__ == "__main__":
    main()

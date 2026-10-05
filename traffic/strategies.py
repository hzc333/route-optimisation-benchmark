"""How traffic enters planning (plan §16): T0 static matrix, T2 iterative
re-estimation, T3 time-dependent travel inside the search.

All strategies minimise total travel time (the planning matrix is used as
both cost and duration), get the same total time budget, and return a
Solution that traffic.evaluate.simulate then scores under TD traffic.
"""

from __future__ import annotations

import numpy as np

from schema.models import Problem, Solution

from .evaluate import departure_times, simulate
from .model import TDModel


def planning_problem(problem: Problem, matrix: np.ndarray) -> Problem:
    m = np.asarray(matrix, dtype=int).tolist()
    return problem.model_copy(update={"distance_matrix": m, "duration_matrix": m})


def shift_window(problem: Problem) -> tuple[int, int]:
    return problem.vehicles[0].shift


def static_matrix(problem: Problem, td: TDModel, kind: str) -> np.ndarray:
    if kind == "free":
        return td.freeflow()
    if kind == "mean":
        return td.mean_matrix(*shift_window(problem))
    if kind == "peak":
        return td.peak_matrix()
    raise ValueError(kind)


def solve_static(adapter, problem, td, *, kind, time_limit_s, seed, **opts) -> tuple[Solution, np.ndarray]:
    m = static_matrix(problem, td, kind)
    return adapter.solve(planning_problem(problem, m), time_limit_s=time_limit_s, seed=seed, **opts), m


def _score(problem, td, sol) -> tuple:
    r = simulate(problem, td, sol)
    return (r["late_jobs"], r["lateness_s"] + r["overtime_s"], r["travel_time_s"])


def solve_iterative(adapter, problem, td, *, time_limit_s, seed, rounds=3, **opts) -> tuple[Solution, np.ndarray]:
    """T2: solve on the day-average matrix, then repeatedly re-estimate every
    arc from where the current plan actually leaves each node (TD departure
    times) and re-solve warm-started from the current plan. Budget split
    equally over rounds + 1 solves; best plan under TD traffic is kept."""
    budget = time_limit_s / (rounds + 1)
    m = static_matrix(problem, td, "mean")
    sol = adapter.solve(planning_problem(problem, m), time_limit_s=budget, seed=seed, **opts)
    best, best_m, best_key = sol, m, _score(problem, td, sol)
    for _ in range(rounds):
        dep = departure_times(problem, td, sol)
        n = m.shape[0]
        m = m.copy()
        t0 = shift_window(problem)[0]
        m[problem.depot] = [td.travel_time(problem.depot, j, t0) for j in range(n)]
        for i, t in dep.items():
            m[i] = [td.travel_time(i, j, t) for j in range(n)]
        sol = adapter.solve(planning_problem(problem, m), time_limit_s=budget, seed=seed,
                            initial_routes=[(r.vehicle_id, r.job_ids) for r in sol.routes], **opts)
        key = _score(problem, td, sol)
        if key < best_key:
            best, best_m, best_key = sol, m, key
    return best, best_m


def solve_td_search(adapter, problem, td, *, time_limit_s, seed, **opts) -> tuple[Solution, None]:
    """T3: time-dependent travel times inside the search (Timefold only)."""
    if adapter.NAME != "timefold":
        raise ValueError("TD search needs Timefold (PyVRP/VROOM: static matrices only; "
                         "OR-Tools: its cumul-dependent transits are not exposed to Python)")
    return adapter.solve(problem, time_limit_s=time_limit_s, seed=seed, td=td.to_json(), **opts), None


STRATEGIES = {
    "static_free": lambda a, p, td, **kw: solve_static(a, p, td, kind="free", **kw),
    "static_mean": lambda a, p, td, **kw: solve_static(a, p, td, kind="mean", **kw),
    "static_peak": lambda a, p, td, **kw: solve_static(a, p, td, kind="peak", **kw),
    "iterative": solve_iterative,
    "td_search": solve_td_search,
}

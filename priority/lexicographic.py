"""Strict-priority strategies layered on any adapter (plan §14).

Target: lexmin(P_CRITICAL, P_HIGH, P_NORMAL, P_LOW, SoftCost) over solutions
with no hard violation, where P_c is the unserved value of class c.

Strategies compared by experiments/run_priority_tests.py:

* weighted  - one solve, class penalties ~10x apart (the original design).
              Not lexicographic: enough lower-class jobs outweigh one higher.
* stacked   - one solve, penalties stacked so each class outweighs all lower
              classes plus any possible soft cost. Exact objective, but the
              numbers grow multiplicatively (overflow guard below) and huge
              penalties may distort metaheuristic search.
* sequential- one solve per class, most important first; each stage maximises
              served value of one class with lower classes removed, then the
              served jobs become required for later stages, warm-started from
              the previous stage. Locking the served *set* (not just the count)
              is stricter than true lexicographic optimisation and is a
              documented approximation. A stage solution that violates hard
              constraints (possible with PyVRP) propagates; the validator
              catches it at the end.
"""

from __future__ import annotations

from time import perf_counter

from adapters.base import build_solution, default_penalties
from schema.models import PRIORITY_ORDER, PriorityClass, Problem, Solution, SolverStatus

INT_LIMIT = 2**62  # headroom below int64 for the solvers' own arithmetic

# A partner-style penalty table in distance units (metres), 10x apart, not
# calibrated to the instance. Used to show the scale-dependence of weights.
FIXED_TABLE = {
    PriorityClass.CRITICAL: 100_000,
    PriorityClass.HIGH: 10_000,
    PriorityClass.NORMAL: 1_000,
    PriorityClass.LOW: 100,
}


def cost_upper_bound(problem: Problem) -> int:
    """Strict upper bound on distance + fixed cost of any solution: one
    outgoing arc per job, one depot departure per vehicle, all fixed costs."""
    d = problem.distance_matrix
    nodes = {problem.depot, *(j.location for j in problem.jobs)}
    out_max = {a: max(d[a][b] for b in nodes) for a in nodes}
    return (sum(out_max[j.location] for j in problem.jobs)
            + len(problem.vehicles) * out_max[problem.depot]
            + sum(v.fixed_cost for v in problem.vehicles) + 1)


def _optional_value(problem: Problem, cls: PriorityClass) -> int:
    return sum(j.value for j in problem.jobs if not j.required and j.priority_class is cls)


def stacked_penalties(problem: Problem) -> dict[PriorityClass, int]:
    """pen[c] > soft cost bound + sum over lower classes of pen * value."""
    unit, pens = cost_upper_bound(problem), {}
    for cls in reversed(PRIORITY_ORDER):  # LOW first
        pens[cls] = unit
        unit *= _optional_value(problem, cls) + 1
    if unit >= INT_LIMIT:
        raise OverflowError(f"stacked penalties need {unit:.3e} >= 2^62")
    return pens


def solve_weighted(adapter, problem: Problem, *, penalties=None, **kw) -> Solution:
    return adapter.solve(problem, penalties=penalties or default_penalties(problem), **kw)


def solve_stacked(adapter, problem: Problem, **kw) -> Solution:
    return adapter.solve(problem, penalties=stacked_penalties(problem), **kw)


def solve_sequential(adapter, problem: Problem, *, time_limit_s: float, seed: int = 0,
                     **kw) -> Solution:
    """Stage per class with optional jobs, then a soft-cost stage; the total
    time budget is split equally so it matches a single solve."""
    t0 = perf_counter()
    levels = [c for c in PRIORITY_ORDER if _optional_value(problem, c)]
    budget = time_limit_s / (len(levels) + 1)
    locked: set[str] = set()   # optional jobs fixed as served
    stage_notes = []
    # Each stage is warm-started from the previous one: those routes serve
    # exactly the locked jobs, so they are feasible for the next stage. Without
    # this, re-packing the locked set from scratch can fail (OR-Tools found no
    # first solution in ~20% of tight random instances).
    start: list[tuple[str, list[str]]] | None = None

    def stage(active_cls: PriorityClass | None) -> tuple[Problem, Solution]:
        jobs = [j.model_copy(update={"required": True}) if j.id in locked else j
                for j in problem.jobs
                if j.required or j.id in locked
                or (j.priority_class is active_cls and not j.required)]
        sub = problem.model_copy(update={"jobs": jobs})
        m = cost_upper_bound(sub)
        if m * (_optional_value(sub, active_cls) + 1 if active_cls else 1) >= INT_LIMIT:
            raise OverflowError("sequential stage penalty overflow")
        sol = adapter.solve(sub, time_limit_s=budget, seed=seed,
                            penalties={c: m for c in PRIORITY_ORDER},
                            initial_routes=start, **kw)
        return sub, sol

    for cls in levels:
        sub, sol = stage(cls)
        if sol.status is not SolverStatus.SOLVED:
            return sol.model_copy(update={"notes": f"sequential stage {cls.value}: {sol.notes}"})
        served = {jid for r in sol.routes for jid in r.job_ids}
        new = {j.id for j in sub.jobs if j.priority_class is cls and not j.required} & served
        locked |= new
        start = [(r.vehicle_id, r.job_ids) for r in sol.routes]
        stage_notes.append(f"{cls.value}:{len(new)}")

    _, final = stage(None)
    if final.status is not SolverStatus.SOLVED:
        return final.model_copy(update={"notes": f"sequential soft stage: {final.notes}"})
    return build_solution(
        problem, solver=f"{adapter.NAME}+seq", solver_version=adapter.VERSION,
        routes=[(r.vehicle_id, r.job_ids) for r in final.routes],
        seed=seed, time_limit_s=time_limit_s, threads=1,
        wall_runtime_s=perf_counter() - t0,
        notes="served per stage " + ",".join(stage_notes))


STRATEGIES = {
    # The solver's own priority handling, no penalties passed (used for VROOM,
    # whose 0-100 priorities are maximised before cost).
    "native": lambda a, p, **kw: a.solve(p, **kw),
    "weighted": solve_weighted,
    "weighted_fixed": lambda a, p, **kw: solve_weighted(a, p, penalties=FIXED_TABLE, **kw),
    "stacked": solve_stacked,
    "sequential": solve_sequential,
}

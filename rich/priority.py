"""Priority strategies for rich problems (same ideas as priority/lexicographic).

* weighted   - one solve with the original design's prizes, ~10x apart per
               class (``rich.common.WEIGHTED_PRIZE``); not lexicographic.
* sequential - one stage per class, most important first: maximise served
               value of that class (prize per value unit above any possible
               soft cost) with lower classes left out, lock the served items
               as required, warm-start the next stage; a last stage minimises
               soft cost over the locked set. The budget is split equally.
* sequential_full - same stages, but lower classes stay in every stage with
               their weighted prizes, so each stage searches the whole problem
               and hands a complete plan to the next one; the active class's
               prize exceeds the soft-cost bound plus all lower prizes, so the
               stage still maximises the active class first. No separate soft
               stage: the LOW stage already minimises soft cost.
"""

from __future__ import annotations

from time import perf_counter

from schema.models import PRIORITY_ORDER, PriorityClass

from .common import WEIGHTED_PRIZE, cost_upper_bound
from .model import RichProblem, RichSolution

INT_LIMIT = 2**62


def optional_value(problem: RichProblem, cls: PriorityClass | None) -> int:
    v = sum(j.value for j in problem.jobs if not j.required and j.priority_class is cls)
    return v + sum(s.value for s in problem.shipments if not s.required and s.priority_class is cls)


def stage_problem(problem: RichProblem, locked: set[str], active: PriorityClass | None,
                  keep_lower: bool = False) -> RichProblem:
    lower = set(PRIORITY_ORDER[PRIORITY_ORDER.index(active) + 1:]) if keep_lower and active else set()

    def keep(item) -> bool:
        return (item.required or item.id in locked or item.priority_class is active
                or item.priority_class in lower)

    def lock(item):
        return item.model_copy(update={"required": True}) if item.id in locked else item

    return problem.model_copy(update={
        "jobs": [lock(j) for j in problem.jobs if keep(j)],
        "shipments": [lock(s) for s in problem.shipments if keep(s)]})


def solve_weighted(module, problem: RichProblem, *, time_limit_s: float, seed: int = 0,
                   **kw) -> RichSolution:
    sol = module.solve(problem, time_limit_s=time_limit_s, seed=seed, prizes=WEIGHTED_PRIZE, **kw)
    return sol.model_copy(update={"solver": f"{module.NAME}+weighted"})


def solve_sequential(module, problem: RichProblem, *, time_limit_s: float, seed: int = 0,
                     keep_lower: bool = False, **kw) -> RichSolution:
    t0 = perf_counter()
    levels = [c for c in PRIORITY_ORDER if optional_value(problem, c)]
    stages = levels if keep_lower and levels else [*levels, None]
    budget = time_limit_s / len(stages)
    locked: set[str] = set()
    start: RichSolution | None = None
    notes = []
    for active in stages:
        sub = stage_problem(problem, locked, active, keep_lower)
        lower = [c for c in PRIORITY_ORDER if c is not active]
        lower_prizes = sum(WEIGHTED_PRIZE[c] * optional_value(sub, c) for c in lower)
        m = cost_upper_bound(sub) + lower_prizes
        if m * (optional_value(sub, active) + 1) >= INT_LIMIT:
            raise OverflowError("sequential stage prize overflow")
        prizes = {c: m if c is active else WEIGHTED_PRIZE[c] for c in PRIORITY_ORDER}
        sol = module.solve(sub, time_limit_s=budget, seed=seed, prizes=prizes,
                           initial=start, **kw)
        if sol.status != "SOLVED":
            return sol.model_copy(update={
                "solver": f"{module.NAME}+seq", "wall_runtime_s": perf_counter() - t0,
                "notes": f"stage {active.value if active else 'soft'}: {sol.notes}"})
        start = sol
        if active is not None:
            served = {v.id for r in sol.routes for v in r.visits if v.kind in ("job", "delivery")}
            new = {i.id for i in [*sub.jobs, *sub.shipments]
                   if i.priority_class is active and not i.required} & served
            locked |= new
            notes.append(f"{active.value}:{len(new)}")
    return start.model_copy(update={
        "solver": f"{module.NAME}+seq", "seed": seed, "time_limit_s": time_limit_s,
        "wall_runtime_s": perf_counter() - t0,
        "notes": "locked per stage " + ",".join(notes) + f"; last stage {start.notes}"})


def solve_sequential_full(module, problem: RichProblem, **kw) -> RichSolution:
    sol = solve_sequential(module, problem, keep_lower=True, **kw)
    return sol.model_copy(update={"solver": f"{module.NAME}+seqfull"})


STRATEGIES = {"weighted": solve_weighted, "sequential": solve_sequential,
              "sequential_full": solve_sequential_full}

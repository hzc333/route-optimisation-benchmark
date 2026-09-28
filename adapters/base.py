"""Shared adapter contract.

Every adapter exposes::

    solve(problem, *, time_limit_s, seed=0, threads=1, **options) -> Solution

and must never silently drop a constraint it cannot express: it raises
``UnsupportedFeature`` instead, which the runner records as a capability gap
(plan §1, §9 step 16).
"""

from __future__ import annotations

from collections.abc import Iterable

from schema.models import PriorityClass, Problem, Route, Solution, SolverStatus, Vehicle


class UnsupportedFeature(Exception):
    """The solver cannot represent a constraint present in the problem."""


# The original design's "about 10x apart" weighting. This is the *weighted*
# baseline, not a strict lexicographic guarantee (plan §14).
CLASS_WEIGHT = {
    PriorityClass.CRITICAL: 1000,
    PriorityClass.HIGH: 100,
    PriorityClass.NORMAL: 10,
    PriorityClass.LOW: 1,
}


def default_penalties(problem: Problem) -> dict[PriorityClass, int]:
    """Drop penalty per class. NORMAL costs one farthest out-and-back trip."""
    unit = 2 * max(max(row) for row in problem.distance_matrix) or 1
    return {cls: max(1, unit * w // CLASS_WEIGHT[PriorityClass.NORMAL])
            for cls, w in CLASS_WEIGHT.items()}


def build_solution(
    problem: Problem,
    *,
    solver: str,
    solver_version: str,
    routes: Iterable[tuple[str, list[str]]],
    **fields,
) -> Solution:
    """Assemble a SOLVED Solution; unserved = jobs not on any route."""
    route_objs = [Route(vehicle_id=v, job_ids=js) for v, js in routes if js]
    served = {j for r in route_objs for j in r.job_ids}
    unserved = [j.id for j in problem.jobs if j.id not in served]
    return Solution(
        problem_name=problem.name,
        solver=solver,
        solver_version=solver_version,
        status=SolverStatus.SOLVED,
        routes=route_objs,
        unserved=unserved,
        **fields,
    )


def has_time_constraints(problem: Problem) -> bool:
    default_shift = Vehicle.model_fields["shift"].default
    return any(j.time_window for j in problem.jobs) or any(
        v.shift != default_shift for v in problem.vehicles
    )

"""PyVRP adapter (plan §9).

Mapping from the shared schema:

* PyVRP 0.14 matrices are indexed by Location, so the shared matrices are
  passed through unchanged and jobs reference their location index;
* identical vehicles are grouped into one VehicleType; shift -> tw_early /
  tw_late of the vehicle type;
* optional jobs -> ``required=False`` with ``prize`` = per-class drop penalty
  (weighted, *not* strict priority);
* skills are not supported natively -> ``UnsupportedFeature``.

The objective is distance (+ fixed vehicle cost), matching OR-Tools.
"""

from __future__ import annotations

from collections import defaultdict
from importlib import metadata
from time import perf_counter

import numpy as np
import pyvrp
from pyvrp.IteratedLocalSearch import IteratedLocalSearchParams
from pyvrp.search import NeighbourhoodParams, PerturbationParams
from pyvrp.stop import MaxRuntime

from schema.models import PriorityClass, Problem, Solution

from .base import UnsupportedFeature, build_solution, default_penalties

NAME = "pyvrp"
VERSION = metadata.version("pyvrp")
# Features of the shared contract this adapter cannot honour.
UNSUPPORTED = frozenset({"skills"})

_INT_MAX = np.iinfo(np.int64).max


def _time_to_best(stats: pyvrp.Statistics) -> float | None:
    data = stats.data
    if not data or not data[-1].best_feas:
        return None
    final = data[-1].best_cost
    elapsed = 0.0
    for runtime, datum in zip(stats.runtimes, data):
        elapsed += runtime
        if datum.best_feas and datum.best_cost <= final:
            return elapsed
    return None


_GROUPS = {
    "neighbourhood": ("num_neighbours", "weight_wait_time", "symmetric_proximity"),
    "ils": ("history_length", "num_iters_no_improvement", "exhaustive_on_best"),
    "perturbation": ("min_perturbations", "max_perturbations"),
    "penalty": ("target_feasible", "penalty_increase", "penalty_decrease"),
}


def _solve_params(overrides: dict, max_penalty: float) -> pyvrp.SolveParams:
    unknown = set(overrides) - {k for keys in _GROUPS.values() for k in keys}
    if unknown:
        raise ValueError(f"unknown PyVRP solve_params: {sorted(unknown)}")
    pick = {g: {k: overrides[k] for k in keys if k in overrides} for g, keys in _GROUPS.items()}
    return pyvrp.SolveParams(
        ils=IteratedLocalSearchParams(**pick["ils"]),
        penalty=pyvrp.PenaltyParams(max_penalty=max_penalty, **pick["penalty"]),
        neighbourhood=NeighbourhoodParams(**pick["neighbourhood"]),
        perturbation=PerturbationParams(**pick["perturbation"]),
    )


def solve(
    problem: Problem,
    *,
    time_limit_s: float,
    seed: int = 0,
    threads: int = 1,
    penalties: dict[PriorityClass, int] | None = None,
    initial_routes: list[tuple[str, list[str]]] | None = None,
    solve_params: dict | None = None,
) -> Solution:
    """``initial_routes`` = [(vehicle_id, job_ids)] warm start.
    ``solve_params`` overrides PyVRP search parameters for tuning experiments:
    num_neighbours, weight_wait_time, symmetric_proximity (neighbourhood);
    history_length, num_iters_no_improvement, exhaustive_on_best (ILS);
    min_perturbations, max_perturbations; target_feasible, penalty_increase,
    penalty_decrease (penalty manager)."""
    t_wall = perf_counter()
    if any(j.skills for j in problem.jobs):
        raise UnsupportedFeature("skills (no native vehicle-client compatibility)")
    penalties = penalties or default_penalties(problem)

    # Group identical vehicles; remember the ids in each group for mapping back.
    groups: dict[tuple, list[str]] = defaultdict(list)
    for veh in problem.vehicles:
        groups[(veh.capacity, veh.shift, veh.fixed_cost)].append(veh.id)
    vehicle_types = [
        pyvrp.VehicleType(num_available=len(ids), capacity=[cap], fixed_cost=fixed,
                          tw_early=shift[0], tw_late=shift[1])
        for (cap, shift, fixed), ids in groups.items()
    ]
    type_ids = list(groups.values())

    clients = []
    for job in problem.jobs:
        early, late = job.time_window or (0, _INT_MAX)
        optional = not job.required
        clients.append(pyvrp.Client(
            location=job.location, delivery=[job.demand], service_duration=job.service,
            tw_early=early, tw_late=late, required=job.required,
            prize=penalties[job.priority_class] * job.value if optional else 0, name=job.id))

    data = pyvrp.ProblemData(
        locations=[pyvrp.Location(x=loc.x or 0.0, y=loc.y or 0.0) for loc in problem.locations],
        clients=clients,
        depots=[pyvrp.Depot(location=problem.depot)],
        vehicle_types=vehicle_types,
        distance_matrices=[np.asarray(problem.distance_matrix, dtype=np.int64)],
        duration_matrices=[np.asarray(problem.duration_matrix, dtype=np.int64)],
    )

    # PyVRP relaxes capacity/time windows with adaptive penalties capped at
    # max_penalty (1e5 per unit). If a single cost coefficient (fixed cost,
    # prize, arc) exceeds that, an infeasible solution becomes "cheaper" and is
    # returned as best. Scale the cap with the largest coefficient; the default
    # is kept whenever it already dominates (all standard benchmark sets).
    scale = max([max(map(max, problem.distance_matrix)),
                 *(v.fixed_cost for v in problem.vehicles),
                 *(c.prize for c in clients)])
    default = pyvrp.PenaltyParams()
    params = _solve_params(solve_params or {}, max(default.max_penalty, 10.0 * scale))

    initial = None
    if initial_routes is not None:
        client_of = {j.id: k for k, j in enumerate(problem.jobs)}
        type_of = {vid: t for t, ids in enumerate(type_ids) for vid in ids}
        initial = pyvrp.Solution(data, [
            pyvrp.Route(data, [client_of[j] for j in js], type_of[vid])
            for vid, js in initial_routes if js])

    t_solve = perf_counter()
    res = pyvrp.solve(data, stop=MaxRuntime(time_limit_s), seed=seed,
                      collect_stats=True, display=False, params=params,
                      initial_solution=initial)
    solver_runtime = perf_counter() - t_solve

    next_vehicle = [0] * len(type_ids)
    routes = []
    for route in res.best.routes():
        vt = route.vehicle_type()
        vid = type_ids[vt][next_vehicle[vt]]
        next_vehicle[vt] += 1
        routes.append((vid, [problem.jobs[act.idx].id for act in route if act.is_client()]))

    feasible = res.is_feasible()
    return build_solution(
        problem, solver=NAME, solver_version=VERSION, routes=routes,
        seed=seed, time_limit_s=time_limit_s, threads=1,
        solver_runtime_s=solver_runtime,
        native_objective=float(res.cost()) if feasible else None,
        time_to_best_s=_time_to_best(res.stats),
        wall_runtime_s=perf_counter() - t_wall,
        notes=f"iterations={res.num_iterations}; native_feasible={feasible}",
    )

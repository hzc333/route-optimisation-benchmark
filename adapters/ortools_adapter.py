"""OR-Tools RoutingModel adapter (plan §8).

Mapping from the shared schema:

* node 0 = depot, node k = k-th job (so jobs may share a location);
* arc cost = distance; fixed vehicle cost via SetFixedCostOfVehicle;
* capacity dimension; time dimension (travel + service at origin, waiting
  allowed) only when the problem has windows or finite shifts;
* skills -> VehicleVar domain; optional jobs -> AddDisjunction with
  a per-class drop penalty (weighted, *not* strict priority).

The routing search is deterministic, so ``seed`` permutes the job-to-node
order instead (seed 0 = input order). This samples OR-Tools' sensitivity to
input order and keeps the seed protocol identical to PyVRP's (plan §21).
"""

from __future__ import annotations

import random
from time import perf_counter

import ortools
from google.protobuf import json_format
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from schema.models import PriorityClass, Problem, Solution

from .base import build_solution, default_penalties, has_time_constraints

NAME = "ortools"
VERSION = ortools.__version__
# Features of the shared contract this adapter cannot honour.
UNSUPPORTED = frozenset()


def solve(
    problem: Problem,
    *,
    time_limit_s: float,
    seed: int = 0,
    threads: int = 1,
    penalties: dict[PriorityClass, int] | None = None,
    # PATH_CHEAPEST_ARC (the docs' default) finds no feasible start on tight
    # Solomon windows (R101, RC101) even in 10 s; parallel cheapest insertion
    # was the only strategy feasible and near-best on Solomon, X and HG1000.
    first_solution: str = "PARALLEL_CHEAPEST_INSERTION",
    metaheuristic: str = "GUIDED_LOCAL_SEARCH",
    initial_routes: list[tuple[str, list[str]]] | None = None,
    search_params: dict | None = None,
) -> Solution:
    """``initial_routes`` = [(vehicle_id, job_ids)] warm start; must be feasible.
    ``search_params`` is merged into RoutingSearchParameters (protobuf JSON
    names, e.g. {"use_iterated_local_search": true}) for tuning experiments;
    first_solution / metaheuristic / time limit are applied after it."""
    t_wall = perf_counter()
    penalties = penalties or default_penalties(problem)

    jobs = list(problem.jobs)
    if seed:
        random.Random(seed).shuffle(jobs)
    locs = [problem.depot] + [j.location for j in jobs]
    service = [0] + [j.service for j in jobs]
    vehicles = problem.vehicles

    manager = pywrapcp.RoutingIndexManager(len(locs), len(vehicles), 0)
    routing = pywrapcp.RoutingModel(manager)

    dist = problem.distance_matrix
    arc = routing.RegisterTransitMatrix([[dist[a][b] for b in locs] for a in locs])
    routing.SetArcCostEvaluatorOfAllVehicles(arc)
    for v, veh in enumerate(vehicles):
        if veh.fixed_cost:
            routing.SetFixedCostOfVehicle(veh.fixed_cost, v)

    demand = routing.RegisterUnaryTransitVector([0] + [j.demand for j in jobs])
    routing.AddDimensionWithVehicleCapacity(
        demand, 0, [veh.capacity for veh in vehicles], True, "Capacity")

    if has_time_constraints(problem):
        dur = problem.duration_matrix
        transit = routing.RegisterTransitMatrix(
            [[dur[a][b] + service[i] for b in locs] for i, a in enumerate(locs)])
        horizon = max(veh.shift[1] for veh in vehicles)
        routing.AddDimension(transit, horizon, horizon, False, "Time")
        time_dim = routing.GetDimensionOrDie("Time")
        for v, veh in enumerate(vehicles):
            for index in (routing.Start(v), routing.End(v)):
                time_dim.CumulVar(index).SetRange(*veh.shift)
        for node, job in enumerate(jobs, start=1):
            if job.time_window:
                time_dim.CumulVar(manager.NodeToIndex(node)).SetRange(*job.time_window)

    for node, job in enumerate(jobs, start=1):
        index = manager.NodeToIndex(node)
        if job.skills:
            # SetAllowedVehiclesForIndex is unusable here: its Python binding
            # rejects every sequence type in 9.15 (absl::Span typemap), and an
            # empty list would mean "all vehicles". Restrict VehicleVar instead;
            # -1 (unperformed) stays allowed only for optional jobs.
            need = set(job.skills)
            allowed = [v for v, veh in enumerate(vehicles) if need <= set(veh.skills)]
            routing.VehicleVar(index).SetValues(allowed + ([] if job.required else [-1]))
        if not job.required:
            routing.AddDisjunction([index], penalties[job.priority_class] * job.value)

    params = pywrapcp.DefaultRoutingSearchParameters()
    if search_params:
        json_format.ParseDict(search_params, params)
    params.first_solution_strategy = getattr(
        routing_enums_pb2.FirstSolutionStrategy, first_solution)
    params.local_search_metaheuristic = getattr(
        routing_enums_pb2.LocalSearchMetaheuristic, metaheuristic)
    params.time_limit.FromMilliseconds(max(1, round(time_limit_s * 1000)))

    improvements: list[tuple[float, int]] = []

    def on_solution():
        cost = routing.CostVar().Max()
        if not improvements or cost < improvements[-1][1]:
            improvements.append((perf_counter() - t_solve, cost))

    routing.AddAtSolutionCallback(on_solution)

    t_solve = perf_counter()
    warm = ""
    if initial_routes is not None:
        routing.CloseModelWithParameters(params)
        node_of = {j.id: node for node, j in enumerate(jobs, start=1)}
        by_vehicle = dict(initial_routes)
        start = routing.ReadAssignmentFromRoutes(
            [[manager.NodeToIndex(node_of[j]) for j in by_vehicle.get(veh.id, [])]
             for veh in vehicles], True)
        warm = "; warm=ok" if start is not None else "; warm=rejected"
    if initial_routes is not None and start is not None:
        assignment = routing.SolveFromAssignmentWithParameters(start, params)
    else:
        assignment = routing.SolveWithParameters(params)
    solver_runtime = perf_counter() - t_solve
    status = routing.status()
    status_name = routing_enums_pb2.RoutingSearchStatus.Value.Name(status)
    meta = dict(
        seed=seed, time_limit_s=time_limit_s, threads=1,
        solver_runtime_s=solver_runtime,
        notes=f"status={status_name}; fs={first_solution}; ls={metaheuristic}{warm}",
    )

    if assignment is None:
        return Solution(
            problem_name=problem.name, solver=NAME, solver_version=VERSION,
            status="NO_SOLUTION", unserved=[j.id for j in problem.jobs],
            wall_runtime_s=perf_counter() - t_wall, **meta)

    routes = []
    for v, veh in enumerate(vehicles):
        ids = []
        index = assignment.Value(routing.NextVar(routing.Start(v)))
        while not routing.IsEnd(index):
            ids.append(jobs[manager.IndexToNode(index) - 1].id)
            index = assignment.Value(routing.NextVar(index))
        routes.append((veh.id, ids))

    return build_solution(
        problem, solver=NAME, solver_version=VERSION, routes=routes,
        native_objective=float(assignment.ObjectiveValue()),
        time_to_best_s=improvements[-1][0] if improvements else None,
        wall_runtime_s=perf_counter() - t_wall, **meta)

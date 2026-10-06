"""Traffic inside PyVRP / OR-Tools search by time-bucket node duplication.

Neither solver accepts departure-time-dependent travel from Python, so the
time dimension is moved into the graph: the shift is cut into buckets of
``width_s``; every job gets one copy per bucket its time window overlaps,
with the copy's window restricted to that bucket; exactly one copy per job
must be visited (PyVRP: required mutually exclusive ClientGroup; OR-Tools:
mandatory disjunction). A leg leaving copy c uses the *largest* travel time
over every departure c allows (sampled every SAMPLE_S), the depot row the
time at shift start. Choosing a copy is choosing when to serve, so traffic
is inside the search.

Guarantee: by FIFO, if the plan is feasible on the expanded instance and
the driver starts no stop before its slot (``min_start``, which
traffic.evaluate.simulate honours), every real arrival is no later than
planned, so the plan is on time under TD traffic up to sampling error.
Cost: about (1 + K * share of untimed jobs) times more nodes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from importlib import metadata
from time import perf_counter

import numpy as np
import pyvrp
from ortools.constraint_solver import pywrapcp, routing_enums_pb2
from pyvrp.stop import MaxRuntime

from adapters.base import build_solution
from adapters.pyvrp_adapter import _solve_params
from schema.models import Problem, Solution

from .model import TDModel

SAMPLE_S = 30


@dataclass
class Copy:
    job_index: int
    lo: int  # service start window of this copy
    hi: int


@dataclass
class Expansion:
    copies: list[Copy]
    matrix: np.ndarray        # (1 + C, 1 + C): node 0 = depot, node c + 1 = copies[c]
    groups: list[list[int]]   # per job: copy indices
    buckets: int


def expand(problem: Problem, td: TDModel, width_s: int) -> Expansion:
    s0, s1 = problem.vehicles[0].shift
    k = math.ceil((s1 - s0) / width_s)
    buckets = [(s0 + b * width_s, min(s0 + (b + 1) * width_s, s1)) for b in range(k)]
    copies, groups = [], []
    for idx, job in enumerate(problem.jobs):
        a, b = job.time_window or (s0, s1)
        group = []
        for lo_b, hi_b in buckets:
            lo, hi = max(a, lo_b), min(b, hi_b)
            if lo <= hi:
                group.append(len(copies))
                copies.append(Copy(idx, lo, hi))
        groups.append(group)

    # Leg times by origin node and destination *location* (copies of a job
    # share its location), then spread to copy columns.
    dest_locs = np.array([problem.depot] + [problem.jobs[c.job_index].location for c in copies])
    uniq, col_of = np.unique(dest_locs, return_inverse=True)
    rows = np.zeros((1 + len(copies), len(uniq)), dtype=int)
    rows[0] = td.travel_time_vec(np.full(len(uniq), problem.depot), uniq, np.full(len(uniq), s0))
    for c, cp in enumerate(copies):
        job = problem.jobs[cp.job_index]
        deps = np.arange(cp.lo + job.service, cp.hi + job.service + 1, SAMPLE_S)
        deps = np.append(deps, cp.hi + job.service)
        ii = np.full((len(deps), len(uniq)), job.location)
        jj = np.broadcast_to(uniq, ii.shape)
        tt = td.travel_time_vec(ii.ravel(), jj.ravel(), np.repeat(deps, len(uniq)))
        rows[c + 1] = tt.reshape(len(deps), len(uniq)).max(axis=0)
    matrix = rows[:, col_of]
    np.fill_diagonal(matrix, 0)
    return Expansion(copies, matrix, groups, k)


def _result(problem, exp, routes_nodes, solver, version, **fields) -> tuple[Solution, dict]:
    """routes_nodes: [(vehicle_id, [copy index, ...])] -> Solution + min_start."""
    routes, min_start, planned = [], {}, 0
    for vid, nodes in routes_nodes:
        prev = 0
        for c in nodes:
            planned += int(exp.matrix[prev, c + 1])
            prev = c + 1
            min_start[problem.jobs[exp.copies[c].job_index].id] = exp.copies[c].lo
        if nodes:
            planned += int(exp.matrix[prev, 0])
        routes.append((vid, [problem.jobs[exp.copies[c].job_index].id for c in nodes]))
    sol = build_solution(problem, solver=solver, solver_version=version, routes=routes, **fields)
    return sol, {"min_start": min_start, "planned_travel_s": planned}


def solve_pyvrp(problem: Problem, td: TDModel, *, width_s: int, time_limit_s: float,
                seed: int = 0) -> tuple[Solution, dict]:
    t_wall = perf_counter()
    exp = expand(problem, td, width_s)
    s0, s1 = problem.vehicles[0].shift
    locs = [problem.locations[problem.depot]] + [
        problem.locations[problem.jobs[c.job_index].location] for c in exp.copies]
    # Jobs with several copies: optional clients in a required, mutually
    # exclusive group (exactly one visited); a single copy is just required.
    multi = [g for g in exp.groups if len(g) > 1]
    group_of = {c: k for k, g in enumerate(multi) for c in g}
    clients = []
    for c, cp in enumerate(exp.copies):
        job = problem.jobs[cp.job_index]
        clients.append(pyvrp.Client(
            location=c + 1, delivery=[job.demand], service_duration=job.service,
            tw_early=cp.lo, tw_late=cp.hi, required=c not in group_of,
            group=group_of.get(c), name=job.id))
    groups = [pyvrp.ClientGroup(clients=g, required=True) for g in multi]
    caps = {v.capacity for v in problem.vehicles}
    if len(caps) != 1:
        raise ValueError("bucketed PyVRP model assumes a homogeneous fleet")
    data = pyvrp.ProblemData(
        locations=[pyvrp.Location(x=l.x or 0.0, y=l.y or 0.0) for l in locs],
        clients=clients, depots=[pyvrp.Depot(location=0)],
        vehicle_types=[pyvrp.VehicleType(num_available=len(problem.vehicles), capacity=[caps.pop()],
                                         tw_early=s0, tw_late=s1)],
        distance_matrices=[exp.matrix.astype(np.int64)],
        duration_matrices=[exp.matrix.astype(np.int64)],
        groups=groups)
    params = _solve_params({}, max(pyvrp.PenaltyParams().max_penalty, 10.0 * float(exp.matrix.max())))
    t_solve = perf_counter()
    res = pyvrp.solve(data, stop=MaxRuntime(time_limit_s), seed=seed, display=False, params=params)
    solver_s = perf_counter() - t_solve
    routes = [(problem.vehicles[k].id, [a.idx for a in r if a.is_client()])
              for k, r in enumerate(res.best.routes())]
    return _result(problem, exp, routes, "pyvrp+buckets", metadata.version("pyvrp"),
                   seed=seed, time_limit_s=time_limit_s, threads=1, solver_runtime_s=solver_s,
                   wall_runtime_s=perf_counter() - t_wall,
                   notes=f"width_s={width_s}; copies={len(exp.copies)}; feasible={res.is_feasible()}")


def solve_ortools(problem: Problem, td: TDModel, *, width_s: int, time_limit_s: float,
                  seed: int = 0) -> tuple[Solution, dict]:
    t_wall = perf_counter()
    exp = expand(problem, td, width_s)
    s0, s1 = problem.vehicles[0].shift
    n, vehicles = 1 + len(exp.copies), problem.vehicles
    manager = pywrapcp.RoutingIndexManager(n, len(vehicles), 0)
    routing = pywrapcp.RoutingModel(manager)
    m = exp.matrix.tolist()
    arc = routing.RegisterTransitMatrix(m)
    routing.SetArcCostEvaluatorOfAllVehicles(arc)
    service = [0] + [problem.jobs[c.job_index].service for c in exp.copies]
    transit = routing.RegisterTransitMatrix([[m[i][j] + service[i] for j in range(n)] for i in range(n)])
    routing.AddDimension(transit, s1, s1, False, "Time")
    time_dim = routing.GetDimensionOrDie("Time")
    demand = routing.RegisterUnaryTransitVector([0] + [problem.jobs[c.job_index].demand for c in exp.copies])
    routing.AddDimensionWithVehicleCapacity(demand, 0, [v.capacity for v in vehicles], True, "Capacity")
    for v in range(len(vehicles)):
        for index in (routing.Start(v), routing.End(v)):
            time_dim.CumulVar(index).SetRange(s0, s1)
    for c, cp in enumerate(exp.copies):
        time_dim.CumulVar(manager.NodeToIndex(c + 1)).SetRange(cp.lo, cp.hi)
    for g in exp.groups:  # no penalty = mandatory: exactly one copy is performed
        routing.AddDisjunction([manager.NodeToIndex(c + 1) for c in g])
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.FromMilliseconds(max(1, round(time_limit_s * 1000)))
    t_solve = perf_counter()
    assignment = routing.SolveWithParameters(params)
    solver_s = perf_counter() - t_solve
    if assignment is None:
        raise RuntimeError(f"OR-Tools found no solution on the bucketed model "
                           f"({routing_enums_pb2.RoutingSearchStatus.Value.Name(routing.status())})")
    routes = []
    for v, veh in enumerate(vehicles):
        nodes, index = [], assignment.Value(routing.NextVar(routing.Start(v)))
        while not routing.IsEnd(index):
            nodes.append(manager.IndexToNode(index) - 1)
            index = assignment.Value(routing.NextVar(index))
        routes.append((veh.id, nodes))
    return _result(problem, exp, routes, "ortools+buckets", metadata.version("ortools"),
                   seed=seed, time_limit_s=time_limit_s, threads=1, solver_runtime_s=solver_s,
                   wall_runtime_s=perf_counter() - t_wall,
                   notes=f"width_s={width_s}; copies={len(exp.copies)}")


def solve(adapter, problem, td, *, width_s, time_limit_s, seed, **_opts):
    fn = {"pyvrp": solve_pyvrp, "ortools": solve_ortools}.get(adapter.NAME)
    if fn is None:
        raise ValueError(f"bucketed model not implemented for {adapter.NAME}")
    return fn(problem, td, width_s=width_s, time_limit_s=time_limit_s, seed=seed)

"""VROOM adapter via pyvroom (plan §10), in-process: no HTTP / Docker latency.

Mapping from the shared schema:

* durations matrix = shared duration matrix (time windows / shifts);
  costs matrix = shared distance matrix, so the objective is distance plus
  VehicleCosts.fixed - the same as the other adapters;
* capacity, hard time windows, shifts, service times and skills are native;
* priority: VROOM optimises lexicographically (sum of assigned priorities,
  then number of assigned jobs, then cost) with priorities in 0..100. Required
  jobs get 100; optional jobs get CLASS_PRIORITY[class] * value, capped at
  100. This is still a weighted sum across classes, not a strict class order;
* VROOM has no drop penalty (it never gives up a servable job to save cost)
  and no hard "required" flag: an unassignable required job comes back
  unassigned and the validator reports it.

VROOM is deterministic, so ``seed`` permutes the job insertion order (seed 0
= input order), as for OR-Tools. It may stop before ``time_limit_s`` once its
exploration level is exhausted; that is recorded as its runtime.
"""

from __future__ import annotations

import random
from datetime import timedelta
from importlib import metadata
from time import perf_counter

import numpy as np
import vroom
from vroom import _vroom

from schema.models import PriorityClass, Problem, Solution, Vehicle

from .base import UnsupportedFeature, build_solution

NAME = "vroom"
VERSION = metadata.version("pyvroom")
# Features of the shared contract this adapter cannot honour.
UNSUPPORTED = frozenset({"drop_penalty", "warm_start"})

CLASS_PRIORITY = {
    PriorityClass.CRITICAL: 100,
    PriorityClass.HIGH: 10,
    PriorityClass.NORMAL: 1,
    PriorityClass.LOW: 0,
}
_UINT32_MAX = np.iinfo(np.uint32).max


def _matrix(m: list[list[int]]) -> _vroom.Matrix:
    # pyvroom 1.15.2 casts with dtype="uint32", which numpy 2 on Windows
    # exposes as buffer format 'L'; the binding only accepts 'I' (C unsigned
    # int). Build the Matrix ourselves with np.uintc.
    arr = np.asarray(m, dtype=np.int64)
    if arr.max() > _UINT32_MAX:
        raise UnsupportedFeature("matrix values above uint32")
    return _vroom.Matrix(arr.astype(np.uintc))


def job_priority(job) -> int:
    if job.required:
        return 100
    return min(100, CLASS_PRIORITY[job.priority_class] * job.value)


def solve(
    problem: Problem,
    *,
    time_limit_s: float,
    seed: int = 0,
    threads: int = 1,
    penalties: dict[PriorityClass, int] | None = None,  # accepted, not expressible
    initial_routes: list[tuple[str, list[str]]] | None = None,
    exploration_level: int = 5,
) -> Solution:
    t_wall = perf_counter()
    if initial_routes is not None:
        raise UnsupportedFeature("warm start (initial_routes) not mapped for VROOM")

    inp = vroom.Input()
    inp.set_durations_matrix("car", _matrix(problem.duration_matrix))
    inp.set_costs_matrix("car", _matrix(problem.distance_matrix))

    default_shift = Vehicle.model_fields["shift"].default
    for k, veh in enumerate(problem.vehicles):
        inp.add_vehicle(vroom.Vehicle(
            id=k, start=problem.depot, end=problem.depot, capacity=[veh.capacity],
            skills=set(veh.skills) or None,
            time_window=vroom.TimeWindow(*veh.shift) if veh.shift != default_shift else None,
            costs=vroom.VehicleCosts(fixed=veh.fixed_cost)))

    order = list(range(len(problem.jobs)))
    if seed:
        random.Random(seed).shuffle(order)
    for i in order:
        job = problem.jobs[i]
        inp.add_job(vroom.Job(
            id=i, location=job.location, delivery=[job.demand], default_service=job.service,
            skills=set(job.skills) or None, priority=job_priority(job),
            time_windows=[vroom.TimeWindow(*job.time_window)] if job.time_window else ()))

    t_solve = perf_counter()
    sol = inp.solve(exploration_level=exploration_level, nb_threads=threads,
                    timeout=timedelta(seconds=time_limit_s))
    solver_runtime = perf_counter() - t_solve

    steps = sol.routes
    jobs_only = steps[steps["type"] == "job"]
    routes = [
        (problem.vehicles[int(vid)].id, [problem.jobs[int(j)].id for j in grp["id"]])
        for vid, grp in jobs_only.groupby("vehicle_id", sort=True)
    ]
    notes = f"exploration={exploration_level}; unassigned={len(sol.unassigned)}"
    if penalties is not None:
        notes += "; penalties ignored (VROOM has no drop penalty)"
    return build_solution(
        problem, solver=NAME, solver_version=VERSION, routes=routes,
        seed=seed, time_limit_s=time_limit_s, threads=threads,
        solver_runtime_s=solver_runtime, native_objective=float(sol.summary.cost),
        wall_runtime_s=perf_counter() - t_wall, notes=notes)

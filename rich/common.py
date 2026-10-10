"""Helpers shared by the rich solver builders and the priority controller."""

from __future__ import annotations

import math

import numpy as np

from schema.models import PriorityClass

from .model import Job, RestPlan, RichProblem, RichRoute
from .validate import simulate_route

# The original design's "about 10x apart" table, anchored on the business
# value of one ride (about 30 SEK = 30 000 points) for NORMAL.
WEIGHTED_PRIZE = {
    PriorityClass.CRITICAL: 3_000_000,
    PriorityClass.HIGH: 300_000,
    PriorityClass.NORMAL: 30_000,
    PriorityClass.LOW: 3_000,
}


def pad(vec: list[int], dims: int) -> list[int]:
    return list(vec) if vec else [0] * dims


def item_locations(problem: RichProblem):
    """(skills, locations) of every job and shipment."""
    for j in problem.jobs:
        yield j.skills, [j.location]
    for s in problem.shipments:
        yield s.skills, [s.pickup.location, s.delivery.location]


def cost_upper_bound(problem: RichProblem) -> int:
    """Strict upper bound on the soft cost of any solution: every vehicle used
    for its whole shift, every stop reached by the costliest leg into it, and
    every soft deadline missed by the whole shift."""
    n_stops = len(problem.jobs) + 2 * len(problem.shipments) + 1
    leg = 0
    for v in problem.vehicles:
        prof = problem.profiles[v.profile]
        leg = max(leg, v.distance_cost * int(np.max(prof.distance_matrix)))
    span = max(v.shift[1] - v.shift[0] for v in problem.vehicles)
    reload_legs = sum(v.max_reloads + 1 for v in problem.vehicles)
    soft = problem.soft_late_cost * span * sum(1 for j in problem.jobs if j.soft_due is not None)
    return (sum(v.fixed_cost + v.duration_cost * span for v in problem.vehicles)
            + leg * (n_stops + reload_legs) + soft + 1)


def partition_group(members: list[Job], parts: int, coords) -> list[list[Job]]:
    """Split optional group members into ``parts`` geographic sectors (angle
    around the centroid) - the PyVRP workaround for "any k of n": at most one
    per sector. Approximate: two members of one sector can never both be
    chosen."""
    if parts <= 0 or not members:
        return []
    pts = np.array([coords(j.location) for j in members])
    c = pts.mean(axis=0)
    angle = np.arctan2(pts[:, 1] - c[1], pts[:, 0] - c[0])
    order = [members[i] for i in np.argsort(angle)]
    size = math.ceil(len(order) / parts)
    return [order[i:i + size] for i in range(0, len(order), size)][:parts]


def insert_rest(problem: RichProblem, route: RichRoute) -> RichRoute:
    """Post-insert the driver break into a route planned without it (PyVRP
    has no breaks). Tries every position, starting as early as allowed; keeps
    the feasible choice that ends earliest, else the least-violating one."""
    veh = next(v for v in problem.vehicles if v.id == route.vehicle_id)
    if veh.rest is None or not route.visits:
        return route
    base = simulate_route(problem, route.model_copy(update={"rest": None}))
    best, best_key = None, None
    for pos, ready in enumerate(base.ready):
        start = max(ready, veh.rest.earliest)
        if start > veh.rest.latest:
            continue
        cand = route.model_copy(update={"rest": RestPlan(position=pos, start=start)})
        r = simulate_route(problem, cand)
        key = (sum(r.violations.values()), r.end)
        if best_key is None or key < best_key:
            best, best_key = cand, key
    if best is None:  # whole route outside the break window: break at the end
        pos = len(route.visits)
        best = route.model_copy(update={"rest": RestPlan(
            position=pos, start=max(base.ready[-1], veh.rest.earliest))})
    return best

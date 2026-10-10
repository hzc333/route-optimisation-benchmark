"""RichProblem -> PyVRP 0.14.

Native: load dimensions with delivery + pickup, shipments (paired pickup and
delivery), several hubs, start/end hub, reloads (``reload_depots``), routing
profiles, hard windows, shifts, fixed / distance / duration costs, optional
items with prizes, mutually exclusive groups.

Workarounds (PyVRP has no such concept):

* skills -> a derived profile per (profile, skill set) in which every leg into
  or out of a stop the vehicle may not serve takes ``FORBIDDEN_S``, far longer
  than any shift, so serving it is infeasible;
* "any k of n" -> geographic sectors, at most one member per sector
  (``rich.common.partition_group``) - stricter than the real rule;
* driver break -> the shift ends ``rest.duration`` early, then the break is
  post-inserted (``rich.common.insert_rest``); it can still clash with a later
  hard window, which the validator then reports;
* soft deadlines -> ``soft_due="copies"`` (default): the job becomes a
  mutually exclusive group of copies whose window ends at the deadline plus
  0 / 15 / 30 / 60 min or not at all, and whose prize drops by the lateness
  cost of that step (a step approximation of linear lateness, like the
  time-bucket trick for traffic). ``soft_due="ignore"``: the search ignores
  deadlines; only the validator scores them.
"""

from __future__ import annotations

from collections import defaultdict
from importlib import metadata
from time import perf_counter

import numpy as np
import pyvrp
from pyvrp import Activity, ActivityType
from pyvrp.stop import MaxRuntime

from schema.models import PriorityClass

from .common import insert_rest, item_locations, pad, partition_group
from .model import RichProblem, RichRoute, RichSolution, Visit

NAME = "pyvrp"
VERSION = metadata.version("pyvrp")
FORBIDDEN_S = 10**6
WORKAROUNDS = ("skills->profile", "k_of_n->sectors", "break->post_insert", "soft_due->copies")
LATE_STEPS_S = (0, 900, 1800, 3600)   # copy windows end at soft_due + step; one more is open
OPEN_COPY_LATE_S = 7200               # lateness charged to the open copy


def _profiles(problem: RichProblem):
    """Matrices per (profile, vehicle skill set) and each vehicle's index."""
    keys, mats, of_vehicle = {}, [], {}
    for v in problem.vehicles:
        key = (v.profile, frozenset(v.skills))
        if key not in keys:
            prof = problem.profiles[v.profile]
            dur = np.array(prof.duration_matrix, dtype=np.int64)
            banned = [loc for skills, locs in item_locations(problem) if set(skills) - set(v.skills)
                      for loc in locs]
            if banned:
                dur = dur.copy()
                dur[banned, :] = FORBIDDEN_S
                dur[:, banned] = FORBIDDEN_S
                dur[banned, banned] = 0
            keys[key] = len(mats)
            mats.append((np.array(prof.distance_matrix, dtype=np.int64), dur))
        of_vehicle[v.id] = keys[key]
    return mats, of_vehicle


def build(problem: RichProblem, prizes: dict[PriorityClass, int], soft_due: str = "copies"):
    dims = len(problem.dims)
    hub_index = {h.id: k for k, h in enumerate(problem.hubs)}
    mats, profile_of = _profiles(problem)

    groups_spec: dict[tuple, list[str]] = defaultdict(list)
    for v in problem.vehicles:
        rest = v.rest.duration if v.rest else 0
        key = (profile_of[v.id], tuple(v.capacity), v.start_hub, v.end_hub,
               tuple(v.reload_hubs), v.max_reloads, v.shift[0], v.shift[1] - rest,
               v.fixed_cost, v.distance_cost, v.duration_cost)
        groups_spec[key].append(v.id)
    vehicle_types, type_ids = [], []
    for (prof, cap, start, end, reload, max_reloads, early, late, fixed, dc, tc), ids \
            in groups_spec.items():
        vehicle_types.append(pyvrp.VehicleType(
            num_available=len(ids), capacity=list(cap), start_depot=hub_index[start],
            end_depot=hub_index[end], fixed_cost=fixed, tw_early=early, tw_late=late,
            unit_distance_cost=dc, unit_duration_cost=tc, profile=prof,
            reload_depots=[hub_index[h] for h in reload], max_reloads=max_reloads))
        type_ids.append(ids)

    # Groups: required (locked) members count towards k; the optional rest is
    # split into k - locked sectors, at most one served per sector.
    coords = lambda loc: (problem.locations[loc].x, problem.locations[loc].y)  # noqa: E731
    sector_of: dict[str, int] = {}
    dropped: set[str] = set()
    pv_groups = []
    k_of = {g.id: g.k for g in problem.groups}
    for gid, members in problem.group_members().items():
        locked = sum(1 for j in members if j.required)
        optional = [j for j in members if not j.required]
        parts = partition_group(optional, k_of[gid] - locked, coords)
        dropped |= {j.id for j in optional} - {j.id for part in parts for j in part}
        for part in parts:
            for j in part:
                sector_of[j.id] = len(pv_groups)
            pv_groups.append(part)

    clients, client_ids = [], []
    soft_groups: list[tuple[list[int], bool]] = []
    big = np.iinfo(np.int64).max
    for j in problem.jobs:
        if j.id in dropped:
            continue
        early, late = j.time_window or (0, big)
        base = 0 if j.required else prizes[j.priority_class] * j.value
        common = dict(location=j.location, delivery=pad(j.delivery, dims),
                      pickup=pad(j.pickup, dims), service_duration=j.service, name=j.id)
        if soft_due == "copies" and j.soft_due is not None and j.id not in sector_of                 and problem.soft_late_cost:
            # One copy per lateness step; exactly one served if required.
            gidx = len(pv_groups) + len(soft_groups)
            members = []
            steps = [s_ for s_ in LATE_STEPS_S if j.soft_due + s_ < late] + [None]
            # Prize = value - lateness cost of the copy. A required job
            # serves exactly one copy, so only differences matter: offset
            # them to stay positive.
            top = base + (problem.soft_late_cost * OPEN_COPY_LATE_S if j.required else 0)
            for step in steps:
                charged = OPEN_COPY_LATE_S if step is None else step
                members.append(len(clients))
                clients.append(pyvrp.Client(
                    **common, tw_early=early,
                    tw_late=late if step is None else min(late, j.soft_due + step),
                    required=False, group=gidx,
                    prize=max(0, top - problem.soft_late_cost * charged)))
                client_ids.append(j.id)
            soft_groups.append((members, j.required))
            continue
        clients.append(pyvrp.Client(
            **common, tw_early=early, tw_late=late, required=j.required, prize=base,
            group=sector_of.get(j.id)))
        client_ids.append(j.id)
    # Warm starts use the last (open-window) copy of a job.
    client_index = {jid: k for k, jid in enumerate(client_ids)}
    groups = [pyvrp.ClientGroup(clients=[client_index[j.id] for j in part], required=False)
              for part in pv_groups]
    groups += [pyvrp.ClientGroup(clients=m, required=req) for m, req in soft_groups]

    shipments = []
    for s in problem.shipments:
        pe, pl = s.pickup.time_window or (0, np.iinfo(np.int64).max)
        de, dl = s.delivery.time_window or (0, np.iinfo(np.int64).max)
        shipments.append(pyvrp.Shipment(
            pickup_location=s.pickup.location, delivery_location=s.delivery.location,
            pickup_tw_early=pe, pickup_tw_late=pl, pickup_service_duration=s.pickup.service,
            delivery_tw_early=de, delivery_tw_late=dl,
            delivery_service_duration=s.delivery.service, amount=pad(s.amount, dims),
            prize=0 if s.required else prizes[s.priority_class] * s.value,
            required=s.required, name=s.id))

    data = pyvrp.ProblemData(
        locations=[pyvrp.Location(x=loc.x or 0.0, y=loc.y or 0.0) for loc in problem.locations],
        clients=clients,
        depots=[pyvrp.Depot(location=h.location, service_duration=h.service) for h in problem.hubs],
        vehicle_types=vehicle_types,
        distance_matrices=[d for d, _ in mats], duration_matrices=[t for _, t in mats],
        groups=groups, shipments=shipments)
    scale = max([int(d.max()) * max(v.distance_cost for v in problem.vehicles) for d, _ in mats]
                + [v.fixed_cost for v in problem.vehicles]
                + [c.prize for c in clients] + [s.prize for s in shipments])
    return data, type_ids, client_ids, client_index, scale


def solve(problem: RichProblem, *, time_limit_s: float, seed: int = 0,
          prizes: dict[PriorityClass, int], initial: RichSolution | None = None,
          soft_due: str = "copies") -> RichSolution:
    t0 = perf_counter()
    data, type_ids, client_ids, client_index, scale = build(problem, prizes, soft_due)
    hub_index = {h.id: k for k, h in enumerate(problem.hubs)}
    ship_index = {s.id: k for k, s in enumerate(problem.shipments)}
    type_of = {vid: t for t, ids in enumerate(type_ids) for vid in ids}

    init = None
    if initial is not None:
        kinds = {"job": ActivityType.CLIENT, "pickup": ActivityType.PICKUP,
                 "delivery": ActivityType.DELIVERY, "reload": ActivityType.DEPOT}
        index = {"job": client_index, "pickup": ship_index, "delivery": ship_index,
                 "reload": hub_index}
        init = pyvrp.Solution(data, [
            pyvrp.Route(data, [Activity(kinds[v.kind], index[v.kind][v.id]) for v in r.visits],
                        type_of[r.vehicle_id])
            for r in initial.routes if r.visits])

    params = pyvrp.SolveParams(penalty=pyvrp.PenaltyParams(
        max_penalty=max(pyvrp.PenaltyParams().max_penalty, 10.0 * scale)))
    res = pyvrp.solve(data, stop=MaxRuntime(time_limit_s), seed=seed, display=False,
                      params=params, initial_solution=init)

    hub_ids = [h.id for h in problem.hubs]
    ship_ids = [s.id for s in problem.shipments]
    next_vehicle = [0] * len(type_ids)
    routes = []
    for route in res.best.routes():
        vt = route.vehicle_type()
        vid = type_ids[vt][next_vehicle[vt]]
        next_vehicle[vt] += 1
        sched = route.schedule()
        visits = []
        for act in sched[1:-1]:
            if act.type == ActivityType.CLIENT:
                visits.append(Visit(kind="job", id=client_ids[act.idx]))
            elif act.type == ActivityType.PICKUP:
                visits.append(Visit(kind="pickup", id=ship_ids[act.idx]))
            elif act.type == ActivityType.DELIVERY:
                visits.append(Visit(kind="delivery", id=ship_ids[act.idx]))
            else:
                visits.append(Visit(kind="reload", id=hub_ids[act.idx]))
        r = RichRoute(vehicle_id=vid, visits=visits, start_time=route.start_time())
        routes.append(insert_rest(problem, r))
    return RichSolution(
        problem_name=problem.name, solver=NAME, routes=routes, seed=seed,
        time_limit_s=time_limit_s, wall_runtime_s=perf_counter() - t0,
        notes=f"iterations={res.num_iterations}; native_feasible={res.is_feasible()}; "
              f"pyvrp_cost={res.cost() if res.is_feasible() else 'inf'}")

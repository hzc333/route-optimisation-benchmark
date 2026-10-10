"""Solver-independent validator for RichProblem / RichSolution.

Re-simulates every route and never trusts solver-reported values.

Schedule rule: a vehicle starts at ``start_time`` (default shift start) at its
start hub, spends the hub's service time loading, then drives; it waits if
early, starts service no later than a hard window's end, and must be back at
its end hub by shift end. A reload visit = drive to the hub, then its service
time (unload depleted / load charged), then a new trip. A break taken after
``position`` visits may split the next drive: arrival = max(ready + travel,
break start) + break duration, and it must not start before the vehicle is
ready there.

Load rule per trip: the vehicle leaves a hub with the deliveries of the jobs in
that trip plus any shipment still on board; jobs subtract delivery and add
pickup; shipment pickup adds its amount and delivery subtracts it. Shipments
may stay on board across a reload. Every dimension stays in [0, capacity].
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from schema.models import PRIORITY_ORDER

from .model import RichProblem, RichRoute, RichSolution, Vehicle


@dataclass
class RouteResult:
    distance: int = 0
    duration: int = 0
    start: int = 0
    end: int = 0
    soft_late_s: int = 0
    reloads: int = 0
    violations: Counter = field(default_factory=Counter)
    served_jobs: list[str] = field(default_factory=list)
    served_shipments: list[str] = field(default_factory=list)
    service_starts: dict[str, int] = field(default_factory=dict)
    # ready[k]: time the vehicle can leave after its first k visits.
    ready: list[int] = field(default_factory=list)


def _add(a: list[int], b: list[int], sign: int = 1) -> list[int]:
    return [x + sign * y for x, y in zip(a, b)] if b else a


def simulate_route(problem: RichProblem, route: RichRoute) -> RouteResult:
    """Simulate one route; violations are counted, never raised."""
    jobs = {j.id: j for j in problem.jobs}
    ships = {s.id: s for s in problem.shipments}
    hubs = {h.id: h for h in problem.hubs}
    veh: Vehicle = next(v for v in problem.vehicles if v.id == route.vehicle_id)
    prof = problem.profiles[veh.profile]
    dist, dur = prof.distance_matrix, prof.duration_matrix
    cap = veh.capacity
    res = RouteResult()
    bad = res.violations
    vskills = set(veh.skills)

    t = max(route.start_time if route.start_time is not None else veh.shift[0], veh.shift[0])
    if t > veh.shift[1]:
        bad["shift"] += 1
    res.start = t
    here = hubs[veh.start_hub].location
    t += hubs[veh.start_hub].service

    # Split into trips at reload visits to know each trip's loaded deliveries.
    trips: list[list[int]] = [[]]
    for k, v in enumerate(route.visits):
        if v.kind == "reload":
            trips.append([])
        else:
            trips[-1].append(k)
    trip_delivery = []
    for trip in trips:
        load = problem.zeros()
        for k in trip:
            v = route.visits[k]
            if v.kind == "job" and v.id in jobs:
                load = _add(load, jobs[v.id].delivery)
        trip_delivery.append(load)

    on_board_ships: dict[str, list[int]] = {}
    trip_no = 0
    load = list(trip_delivery[0])
    if any(x > c for x, c in zip(load, cap)):
        bad["capacity"] += 1
    seen_ships: dict[str, str] = {}
    rest = route.rest
    if veh.rest is not None and route.visits and rest is None:
        bad["break_missing"] += 1

    def drive(to_loc: int, position: int) -> None:
        nonlocal t, here
        res.ready.append(t)
        travel = dur[here][to_loc]
        res.distance += dist[here][to_loc]
        if rest is not None and veh.rest is not None and rest.position == position:
            b = veh.rest
            if rest.start < t:
                bad["break_before_ready"] += 1
            if not b.earliest <= rest.start <= b.latest:
                bad["break_window"] += 1
            t = max(t + travel, rest.start) + b.duration
        else:
            t += travel
        here = to_loc

    for k, visit in enumerate(route.visits):
        if visit.kind == "reload":
            hub = hubs.get(visit.id)
            if hub is None or visit.id not in veh.reload_hubs:
                bad["reload_hub"] += 1
                continue
            drive(hub.location, k)
            t += hub.service
            res.reloads += 1
            trip_no += 1
            load = _add(list(trip_delivery[trip_no]), [sum(x) for x in zip(*on_board_ships.values())]
                        if on_board_ships else problem.zeros())
            if any(x > c for x, c in zip(load, cap)):
                bad["capacity"] += 1
            continue

        if visit.kind == "job":
            job = jobs.get(visit.id)
            if job is None:
                bad["unknown_visit"] += 1
                continue
            loc, service, window, skills = job.location, job.service, job.time_window, job.skills
        else:
            s = ships.get(visit.id)
            if s is None:
                bad["unknown_visit"] += 1
                continue
            step = s.pickup if visit.kind == "pickup" else s.delivery
            loc, service, window, skills = step.location, step.service, step.time_window, s.skills
        if set(skills) - vskills:
            bad["skills"] += 1
        drive(loc, k)
        if window:
            t = max(t, window[0])
            if t > window[1]:
                bad["time_window"] += 1
        res.service_starts[f"{visit.kind}:{visit.id}"] = t
        if visit.kind == "job":
            if job.soft_due is not None and t > job.soft_due:
                res.soft_late_s += t - job.soft_due
            load = _add(_add(load, job.delivery, -1), job.pickup)
            res.served_jobs.append(job.id)
        elif visit.kind == "pickup":
            if visit.id in seen_ships:
                bad["shipment_order"] += 1
            seen_ships[visit.id] = "pickup"
            on_board_ships[visit.id] = s.amount
            load = _add(load, s.amount)
        else:
            if seen_ships.get(visit.id) != "pickup":
                bad["shipment_order"] += 1
            seen_ships[visit.id] = "delivered"
            on_board_ships.pop(visit.id, None)
            load = _add(load, s.amount, -1)
            res.served_shipments.append(visit.id)
        if any(x < 0 or x > c for x, c in zip(load, cap)):
            bad["capacity"] += 1
        t += service

    drive(hubs[veh.end_hub].location, len(route.visits))
    if rest is not None and veh.rest is not None and rest.position > len(route.visits):
        bad["break_position"] += 1
    res.end = t
    res.duration = t - res.start
    if t > veh.shift[1]:
        bad["shift"] += 1
    if res.reloads > veh.max_reloads:
        bad["max_reloads"] += 1
    for sid, state in seen_ships.items():
        if state != "delivered":
            bad["shipment_incomplete"] += 1
    return res


@dataclass
class Report:
    feasible: bool
    violations: dict[str, int]
    unserved: dict[str, int]          # value per priority class
    soft_cost: int
    cost_parts: dict[str, int]
    vehicles_used: int
    served_jobs: int
    served_shipments: int
    distance_m: int
    soft_late_s: int
    reloads: int

    def vector(self) -> tuple:
        return (sum(self.violations.values()),
                *(self.unserved[c.value] for c in PRIORITY_ORDER), self.soft_cost)

    def flat(self) -> dict:
        out = {"feasible": self.feasible, "hard_violations": sum(self.violations.values()),
               "soft_cost": self.soft_cost, "vehicles_used": self.vehicles_used,
               "served_jobs": self.served_jobs, "served_shipments": self.served_shipments,
               "distance_m": self.distance_m, "soft_late_s": self.soft_late_s,
               "reloads": self.reloads}
        out |= {f"unserved_{c.value}": self.unserved[c.value] for c in PRIORITY_ORDER}
        out |= {f"cost_{k}": v for k, v in self.cost_parts.items()}
        out |= {f"viol_{k}": v for k, v in self.violations.items()}
        return out


def validate(problem: RichProblem, solution: RichSolution) -> Report:
    vehicles = {v.id: v for v in problem.vehicles}
    bad: Counter = Counter()
    parts = Counter({"fixed": 0, "distance": 0, "duration": 0, "soft_late": 0})
    served_j: Counter = Counter()
    served_s: Counter = Counter()
    used_vehicles: Counter = Counter()
    late = dist = reloads = 0
    for route in solution.routes:
        veh = vehicles.get(route.vehicle_id)
        if veh is None:
            bad["unknown_vehicle"] += 1
            continue
        used_vehicles[veh.id] += 1
        if not route.visits:
            continue
        r = simulate_route(problem, route)
        bad.update(r.violations)
        served_j.update(r.served_jobs)
        served_s.update(r.served_shipments)
        parts["fixed"] += veh.fixed_cost
        parts["distance"] += veh.distance_cost * r.distance
        parts["duration"] += veh.duration_cost * r.duration
        late += r.soft_late_s
        dist += r.distance
        reloads += r.reloads
    bad["vehicle_reused"] += sum(c - 1 for c in used_vehicles.values() if c > 1)
    bad["duplicate_visit"] += sum(c - 1 for c in served_j.values() if c > 1)
    bad["duplicate_visit"] += sum(c - 1 for c in served_s.values() if c > 1)
    parts["soft_late"] = problem.soft_late_cost * late

    unserved = {c.value: 0 for c in PRIORITY_ORDER}
    for j in problem.jobs:
        if j.id in served_j:
            continue
        if j.required:
            bad["required_unserved"] += 1
        elif j.group is None:
            unserved[j.priority_class.value] += j.value
    for s in problem.shipments:
        if s.id in served_s:
            continue
        if s.required:
            bad["required_unserved"] += 1
        else:
            unserved[s.priority_class.value] += s.value
    group_k = {g.id: g.k for g in problem.groups}
    for gid, members in problem.group_members().items():
        if not members:
            continue
        count = sum(1 for j in members if j.id in served_j)
        if count > group_k[gid]:
            bad["group_k"] += count - group_k[gid]
        optional = [j for j in members if not j.required] or members
        unserved[optional[0].priority_class.value] += max(0, group_k[gid] - count) * optional[0].value

    violations = {k: v for k, v in bad.items() if v}
    return Report(
        feasible=not violations, violations=violations, unserved=unserved,
        soft_cost=sum(parts.values()), cost_parts=dict(parts),
        vehicles_used=sum(1 for r in solution.routes if r.visits),
        served_jobs=len(served_j), served_shipments=len(served_s),
        distance_m=dist, soft_late_s=late, reloads=reloads)

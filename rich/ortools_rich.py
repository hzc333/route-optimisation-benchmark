"""RichProblem -> OR-Tools 9.15 RoutingModel.

Native: several hubs as start/end nodes, per-vehicle profiles (transit and arc
cost evaluators per vehicle), hard windows, shifts, soft deadlines
(``SetCumulVarSoftUpperBound``), driver breaks (``SetBreakIntervalsOfVehicle``,
kept inside the route), skills (``VehicleVar``), "any k of n" (disjunction with
``max_cardinality`` and per-inactive penalty), paired pickup and delivery,
fixed / distance / duration (span) costs.

Workaround - reloads: OR-Tools has no multi-trip concept. Each hub gets
optional "reload" copies; at a copy the load dimensions get slack, which
restocks a delivery dimension (on-board count goes up) or empties a pickup
dimension (free space goes up). A dimension that holds both job deliveries
and job pickups cannot be modelled this way and raises NotImplementedError.
Shipments may stay on board across a reload (no slack on their dimension).
"""

from __future__ import annotations

from importlib import metadata
from time import perf_counter

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from schema.models import PriorityClass

from .model import RestPlan, RichProblem, RichRoute, RichSolution, Visit

NAME = "ortools"
VERSION = metadata.version("ortools")
HORIZON = 48 * 3600


class _Node:
    __slots__ = ("kind", "id", "loc", "service", "window", "delta", "skills")

    def __init__(self, kind, id_, loc, service=0, window=None, delta=None, skills=()):
        self.kind, self.id, self.loc, self.service = kind, id_, loc, service
        self.window, self.delta, self.skills = window, delta, set(skills)


def _dim_modes(problem: RichProblem) -> list[str]:
    modes = []
    for d in range(len(problem.dims)):
        dl = any(j.delivery and j.delivery[d] for j in problem.jobs)
        pk = any(j.pickup and j.pickup[d] for j in problem.jobs)
        if dl and pk:
            raise NotImplementedError(f"dimension {problem.dims[d]} mixes deliveries and pickups")
        modes.append("space" if pk else "onboard")
    return modes


def solve(problem: RichProblem, *, time_limit_s: float, seed: int = 0,
          prizes: dict[PriorityClass, int], initial: RichSolution | None = None,
          **kw) -> RichSolution:
    """With driver breaks, local search started from ReadAssignmentFromRoutes
    never inserts a further node (seen on every Voi stage: 0 of 116 HIGH jobs
    added, versus all of them from scratch). So with breaks the warm start is
    only a fallback when a cold solve finds nothing, with a third of the
    budget on top."""
    if initial is not None and any(v.rest for v in problem.vehicles):
        t0 = perf_counter()
        sol = _solve(problem, time_limit_s=time_limit_s, seed=seed, prizes=prizes, **kw)
        if sol.status == "SOLVED":
            return sol
        sol = _solve(problem, time_limit_s=time_limit_s / 3, seed=seed, prizes=prizes,
                     initial=initial, **kw)
        return sol.model_copy(update={"wall_runtime_s": perf_counter() - t0,
                                      "notes": "cold failed, warm fallback; " + sol.notes})
    return _solve(problem, time_limit_s=time_limit_s, seed=seed, prizes=prizes,
                  initial=initial, **kw)


def _solve(problem: RichProblem, *, time_limit_s: float, seed: int = 0,
           prizes: dict[PriorityClass, int], initial: RichSolution | None = None,
           first_solution: str = "PARALLEL_CHEAPEST_INSERTION",
           metaheuristic: str = "GUIDED_LOCAL_SEARCH") -> RichSolution:
    t0 = perf_counter()
    dims = len(problem.dims)
    modes = _dim_modes(problem)

    # Nodes: hubs, jobs, shipment steps, reload copies. ``delta`` is the
    # change of the dimension's cumul when leaving the node.
    nodes: list[_Node] = [_Node("hub", h.id, h.location, h.service) for h in problem.hubs]
    hub_node = {h.id: k for k, h in enumerate(problem.hubs)}

    def delta(delivery, pickup, ship_sign=0, amount=None):
        out = []
        for d in range(dims):
            dl = delivery[d] if delivery else 0
            pk = pickup[d] if pickup else 0
            sh = ship_sign * (amount[d] if amount else 0)
            # onboard: load - delivery + pickup + shipment; space: the negative
            out.append(pk - dl + sh if modes[d] == "onboard" else dl - pk - sh)
        return out

    job_node, pick_node, drop_node = {}, {}, {}
    for j in problem.jobs:
        job_node[j.id] = len(nodes)
        nodes.append(_Node("job", j.id, j.location, j.service, j.time_window,
                           delta(j.delivery, j.pickup), j.skills))
    for s in problem.shipments:
        pick_node[s.id] = len(nodes)
        nodes.append(_Node("pickup", s.id, s.pickup.location, s.pickup.service,
                           s.pickup.time_window, delta(None, None, 1, s.amount), s.skills))
        drop_node[s.id] = len(nodes)
        nodes.append(_Node("delivery", s.id, s.delivery.location, s.delivery.service,
                           s.delivery.time_window, delta(None, None, -1, s.amount), s.skills))
    reload_nodes: dict[str, list[int]] = {}
    for h in problem.hubs:
        copies = sum(v.max_reloads for v in problem.vehicles if h.id in v.reload_hubs)
        reload_nodes[h.id] = []
        for _ in range(copies):
            reload_nodes[h.id].append(len(nodes))
            nodes.append(_Node("reload", h.id, h.location, h.service))

    V = len(problem.vehicles)
    starts = [hub_node[v.start_hub] for v in problem.vehicles]
    ends = [hub_node[v.end_hub] for v in problem.vehicles]
    manager = pywrapcp.RoutingIndexManager(len(nodes), V, starts, ends)
    routing = pywrapcp.RoutingModel(manager)
    solver = routing.solver()
    N = routing.Size() + V  # all indices including ends

    def node_of(index):
        return nodes[manager.IndexToNode(index)]

    # Costs and time per profile -------------------------------------------
    arc_cb, time_cb = {}, {}
    for v_id, v in enumerate(problem.vehicles):
        prof = problem.profiles[v.profile]
        key = (v.profile, v.distance_cost)
        if key not in arc_cb:
            dist, c = prof.distance_matrix, v.distance_cost
            arc_cb[key] = routing.RegisterTransitCallback(
                lambda i, j, dist=dist, c=c: c * dist[node_of(i).loc][node_of(j).loc])
        routing.SetArcCostEvaluatorOfVehicle(arc_cb[key], v_id)
        routing.SetFixedCostOfVehicle(v.fixed_cost, v_id)
        if v.profile not in time_cb:
            dur = prof.duration_matrix
            time_cb[v.profile] = routing.RegisterTransitCallback(
                lambda i, j, dur=dur: node_of(i).service + dur[node_of(i).loc][node_of(j).loc])
    routing.AddDimensionWithVehicleTransits(
        [time_cb[v.profile] for v in problem.vehicles], HORIZON, HORIZON, False, "time")
    time = routing.GetDimensionOrDie("time")
    for v_id, v in enumerate(problem.vehicles):
        time.CumulVar(routing.Start(v_id)).SetRange(*v.shift)
        time.CumulVar(routing.End(v_id)).SetRange(*v.shift)
        time.SetSpanCostCoefficientForVehicle(v.duration_cost, v_id)
    for index in range(routing.Size()):
        if routing.IsStart(index):
            continue
        n = node_of(index)
        if n.window:
            time.CumulVar(index).SetRange(*n.window)
    if problem.soft_late_cost:
        for j in problem.jobs:
            if j.soft_due is not None:
                time.SetCumulVarSoftUpperBound(manager.NodeToIndex(job_node[j.id]), j.soft_due,
                                               problem.soft_late_cost)

    # Breaks, kept inside the route so the plan is executable as written.
    visit_transit = [node_of(i).service for i in range(routing.Size())]
    rests = {}
    for v_id, v in enumerate(problem.vehicles):
        if v.rest is None:
            continue
        iv = solver.FixedDurationIntervalVar(v.rest.earliest, v.rest.latest, v.rest.duration,
                                             False, f"rest{v_id}")
        solver.Add(iv.StartExpr() >= time.CumulVar(routing.Start(v_id))
                   + problem.hub(v.start_hub).service)
        solver.Add(iv.EndExpr() <= time.CumulVar(routing.End(v_id)))
        time.SetBreakIntervalsOfVehicle([iv], v_id, visit_transit)
        rests[v_id] = iv

    # Load dimensions --------------------------------------------------------
    for d in range(dims):
        cb = routing.RegisterUnaryTransitCallback(
            lambda i, d=d: node_of(i).delta[d] if node_of(i).delta else 0)
        caps = [v.capacity[d] for v in problem.vehicles]
        has_jobs = any((j.delivery and j.delivery[d]) or (j.pickup and j.pickup[d])
                       for j in problem.jobs)
        slack = max(caps) if has_jobs else 0
        routing.AddDimensionWithVehicleCapacity(cb, slack, caps, False, f"load_{d}")
        dim = routing.GetDimensionOrDie(f"load_{d}")
        if slack:
            for index in range(routing.Size()):
                if node_of(index).kind != "reload":
                    dim.SlackVar(index).SetValue(0)
        if modes[d] == "onboard" and not has_jobs:
            for v_id in range(V):
                dim.CumulVar(routing.Start(v_id)).SetValue(0)
        if modes[d] == "space":
            for v_id in range(V):
                dim.CumulVar(routing.Start(v_id)).SetValue(caps[v_id])

    # Reload counting --------------------------------------------------------
    if any(reload_nodes.values()):
        cb = routing.RegisterUnaryTransitCallback(lambda i: int(node_of(i).kind == "reload"))
        routing.AddDimensionWithVehicleCapacity(
            cb, 0, [v.max_reloads for v in problem.vehicles], True, "reloads")

    # Skills, disjunctions, pickup and delivery --------------------------------
    def restrict(index, skills, optional):
        if not skills:
            return
        allowed = [k for k, v in enumerate(problem.vehicles) if skills <= set(v.skills)]
        routing.VehicleVar(index).SetValues(allowed + ([-1] if optional else []))

    k_of = {g.id: g.k for g in problem.groups}
    members = problem.group_members()
    grouped = {j.id for ms in members.values() for j in ms}
    for j in problem.jobs:
        idx = manager.NodeToIndex(job_node[j.id])
        restrict(idx, set(j.skills), not j.required)
        if not j.required and j.id not in grouped:
            routing.AddDisjunction([idx], prizes[j.priority_class] * j.value)
    for gid, ms in members.items():
        optional = [j for j in ms if not j.required]
        room = k_of[gid] - (len(ms) - len(optional))
        idxs = [manager.NodeToIndex(job_node[j.id]) for j in optional]
        if not idxs:
            continue
        if room <= 0:
            for idx in idxs:
                routing.AddDisjunction([idx], 0)
                routing.VehicleVar(idx).SetValues([-1])
            continue
        prize = prizes[optional[0].priority_class] * optional[0].value
        routing.AddDisjunction(idxs, prize, room, routing.PENALIZE_PER_INACTIVE)
    for s in problem.shipments:
        p, q = manager.NodeToIndex(pick_node[s.id]), manager.NodeToIndex(drop_node[s.id])
        routing.AddPickupAndDelivery(p, q)
        solver.Add(routing.VehicleVar(p) == routing.VehicleVar(q))
        solver.Add(time.CumulVar(p) <= time.CumulVar(q))
        restrict(p, set(s.skills), not s.required)
        restrict(q, set(s.skills), not s.required)
        if not s.required:
            routing.AddDisjunction([p], prizes[s.priority_class] * s.value)
            routing.AddDisjunction([q], 0)
    for hid, copies in reload_nodes.items():
        allowed = [k for k, v in enumerate(problem.vehicles) if hid in v.reload_hubs]
        for n in copies:
            idx = manager.NodeToIndex(n)
            routing.AddDisjunction([idx], 0)
            routing.VehicleVar(idx).SetValues(allowed + [-1])

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = getattr(routing_enums_pb2.FirstSolutionStrategy,
                                             first_solution)
    params.local_search_metaheuristic = getattr(
        routing_enums_pb2.LocalSearchMetaheuristic, metaheuristic)
    params.time_limit.FromMilliseconds(max(1, round(time_limit_s * 1000)))

    start = None
    if initial is not None:
        pool = {h: list(c) for h, c in reload_nodes.items()}
        index_of = {"job": job_node, "pickup": pick_node, "delivery": drop_node}
        vid = {v.id: k for k, v in enumerate(problem.vehicles)}
        plan = [[] for _ in range(V)]
        for r in initial.routes:
            for visit in r.visits:
                n = pool[visit.id].pop(0) if visit.kind == "reload" else index_of[visit.kind][visit.id]
                plan[vid[r.vehicle_id]].append(manager.NodeToIndex(n))
        routing.CloseModelWithParameters(params)
        start = routing.ReadAssignmentFromRoutes(plan, True)

    sol = (routing.SolveFromAssignmentWithParameters(start, params) if start is not None
           else routing.SolveWithParameters(params))
    status = routing.status()
    if sol is None:
        return RichSolution(problem_name=problem.name, solver=NAME, status="NO_SOLUTION",
                            seed=seed, time_limit_s=time_limit_s,
                            wall_runtime_s=perf_counter() - t0, notes=f"status={status}")

    rest_start = {}
    if rests:
        for k in range(sol.IntervalVarContainer().Size()):
            e = sol.IntervalVarContainer().Element(k)
            rest_start[e.Var().Name()] = e.StartValue()

    routes = []
    for v_id, v in enumerate(problem.vehicles):
        index = sol.Value(routing.NextVar(routing.Start(v_id)))
        visits, ready = [], [sol.Value(time.CumulVar(routing.Start(v_id)))
                             + problem.hub(v.start_hub).service]
        while not routing.IsEnd(index):
            n = node_of(index)
            visits.append(Visit(kind=n.kind, id=n.id))
            ready.append(sol.Value(time.CumulVar(index)) + n.service)
            index = sol.Value(routing.NextVar(index))
        if not visits:
            continue
        rest = None
        if v_id in rests:
            s = rest_start.get(f"rest{v_id}")
            if s is not None:
                pos = max(k for k, r in enumerate(ready) if r <= s) if ready[0] <= s else 0
                rest = RestPlan(position=pos, start=s)
        routes.append(RichRoute(vehicle_id=v.id, visits=visits, rest=rest,
                                start_time=sol.Value(time.CumulVar(routing.Start(v_id)))))
    return RichSolution(
        problem_name=problem.name, solver=NAME, routes=routes, seed=seed,
        time_limit_s=time_limit_s, wall_runtime_s=perf_counter() - t0,
        notes=f"status={status}; objective={sol.ObjectiveValue()}; nodes={len(nodes)}")

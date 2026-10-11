"""V3 - re-planning mid-shift (plan §8 "replanning"; untested so far).

    python -m rich.dynamic [--instances 5]

A full-day plan (PyVRP + sequential_full, 120 s) is executed until 10:00.
Then something happens:

* ``events``    - 4 new parking violations (required, pick up within 1-2.5 h)
                  and 8 new CRITICAL swaps (hard window: within 2 h);
* ``breakdown`` - the same, and one cargo bike breaks down at 10:00.

``residual`` turns the situation into a new RichProblem: each vehicle starts
where it is (a pseudo-hub) when it is free, with what it carries (charged
batteries still on board can be delivered without a reload; depleted ones
occupy room until the next hub visit), its remaining reloads, and its break
if not yet taken. Scooters on board become required drop-off jobs that only
that vehicle can do. Done work is removed; groups keep only their remaining k.

Arms: ``keep`` (no re-optimisation: old plan, new work unserved), ``warm5`` /
``warm30`` (sequential_full warm-started from the old plan, 5 / 30 s) and
``cold30`` (from scratch, 30 s). Stability = share of the old plan's
remaining jobs that stay on the same vehicle.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd

from schema.models import Location, PriorityClass

from .model import Hub, Job, RichProblem, RichRoute, RichSolution, Shipment, Step, Visit
from .validate import simulate_route

ROOT = Path(__file__).resolve().parents[1]
CUT = 10 * 3600
BASE_TIME = 120.0
ARMS = {"keep": (None, 0.0), "warm5": (True, 5.0), "warm30": (True, 30.0),
        "cold30": (False, 30.0)}
SCENARIOS = ("events", "breakdown")
KEY = ["instance", "scenario", "arm", "seed", "time_limit_s"]


def _route_state(problem: RichProblem, route: RichRoute, cut: int):
    """(visits done, available time, location, on-board vectors, reloads done,
    break taken)."""
    r = simulate_route(problem, route)
    hubs = {h.id: h for h in problem.hubs}
    jobs = {j.id: j for j in problem.jobs}
    ships = {s.id: s for s in problem.shipments}
    veh = next(v for v in problem.vehicles if v.id == route.vehicle_id)
    starts = []
    for k, v in enumerate(route.visits):
        if v.kind == "reload":
            starts.append(r.ready[k + 1] - hubs[v.id].service)
        else:
            starts.append(r.service_starts[f"{v.kind}:{v.id}"])
    done = sum(1 for s in starts if s < cut)
    if done == len(route.visits):
        avail, loc = max(cut, r.end), hubs[veh.end_hub].location
    else:
        avail = max(cut, r.ready[done])
        last = route.visits[done - 1] if done else None
        if last is None:
            loc = hubs[veh.start_hub].location
        elif last.kind == "reload":
            loc = hubs[last.id].location
        elif last.kind == "job":
            loc = jobs[last.id].location
        else:
            s = ships[last.id]
            loc = (s.pickup if last.kind == "pickup" else s.delivery).location
    taken = route.rest is not None and route.rest.start < cut
    if taken and route.rest.position == done:
        avail = max(avail, route.rest.start + veh.rest.duration)
    # Current trip: visits after the last reload that has started.
    last_reload = max([k for k in range(done) if route.visits[k].kind == "reload"], default=-1)
    next_reload = min([k for k in range(done, len(route.visits))
                       if route.visits[k].kind == "reload"], default=len(route.visits))
    trip = route.visits[last_reload + 1:next_reload]
    trip_done = route.visits[last_reload + 1:done]
    zeros = problem.zeros()
    charged = list(zeros)
    for v in trip:
        if v.kind == "job" and v not in trip_done:
            charged = [a + b for a, b in zip(charged, jobs[v.id].delivery or zeros)]
    picked = list(zeros)
    for v in trip_done:
        if v.kind == "job":
            picked = [a + b for a, b in zip(picked, jobs[v.id].pickup or zeros)]
    in_flight = [v.id for v in route.visits[:done] if v.kind == "pickup"
                 and Visit(kind="delivery", id=v.id) not in route.visits[:done]]
    reloads = sum(1 for v in route.visits[:done] if v.kind == "reload")
    return dict(done=done, avail=int(avail), loc=loc, charged=charged, picked=picked,
                in_flight=in_flight, reloads=reloads, rest_taken=taken)


def _new_events(rng, cut, add_point):
    from .voi import HOTSPOTS, KM_PER_DEG_LAT, KM_PER_DEG_LON, _near

    hot = list(HOTSPOTS.values())
    jobs, ships = [], []
    for k in range(8):
        loc, skills = add_point(_near(rng, hot[rng.integers(0, len(hot))], 400, 1)[0], f"new_crit{k}")
        jobs.append(Job(id=f"new_crit{k}", location=loc, service=150, delivery=[1, 0, 0],
                        pickup=[0, 1, 0], time_window=(cut, cut + 7200),
                        priority_class=PriorityClass.CRITICAL, value=4, skills=skills))
    for k in range(4):
        p = _near(rng, hot[rng.integers(0, len(hot))], 500, 1)[0]
        angle, metres = rng.uniform(0, 2 * math.pi), rng.uniform(300, 700)
        q = (p[0] + metres * math.sin(angle) / 1000 / KM_PER_DEG_LAT,
             p[1] + metres * math.cos(angle) / 1000 / KM_PER_DEG_LON)
        a, sa = add_point(p, f"new_viol{k}_from")
        b, sb = add_point(q, f"new_viol{k}_to")
        ships.append(Shipment(
            id=f"new_viol{k}", pickup=Step(location=a, service=180,
                                           time_window=(cut, cut + int(rng.integers(3600, 9000)))),
            delivery=Step(location=b, service=60), amount=[0, 0, 1], required=True,
            priority_class=PriorityClass.HIGH, skills=sorted(set(sa) | set(sb))))
    return jobs, ships


def residual(problem: RichProblem, plan: RichSolution, scenario: str, seed: int = 0,
             cut: int = CUT) -> tuple[RichProblem, RichSolution, dict]:
    from .voi import matrices, zone_skill_of

    rng = np.random.default_rng(70_000 + seed)
    latlon = [(loc.y, loc.x) for loc in problem.locations]
    names = [loc.id for loc in problem.locations]

    def add_point(p, name):
        latlon.append((float(p[0]), float(p[1])))
        names.append(name)
        return len(latlon) - 1, zone_skill_of(p)

    states = {r.vehicle_id: _route_state(problem, r, cut) for r in plan.routes if r.visits}
    routes = {r.vehicle_id: r for r in plan.routes if r.visits}
    broken = None
    if scenario == "breakdown":
        bikes = [v.id for v in problem.vehicles if v.profile == "bike" and v.id in states]
        broken = bikes[0] if bikes else None

    done_items = set()
    for vid, st in states.items():
        for v in routes[vid].visits[:st["done"]]:
            if v.kind in ("job", "delivery"):
                done_items.add(v.id)
    in_flight = {sid: vid for vid, st in states.items() for sid in st["in_flight"]}

    modes = ["delivery" if any(j.delivery and j.delivery[d] for j in problem.jobs) else
             "pickup" if any(j.pickup and j.pickup[d] for j in problem.jobs) else "none"
             for d in range(len(problem.dims))]
    hubs, vehicles, extra_jobs, warm = list(problem.hubs), [], [], []
    for v in problem.vehicles:
        if v.id == broken:
            continue
        st = states.get(v.id)
        if st is None:  # unused vehicle: still at its hub, fresh
            vehicles.append(v.model_copy(update={"shift": (max(cut, v.shift[0]), v.shift[1])}))
            continue
        pos = f"POS_{v.id}"
        hubs.append(Hub(id=pos, location=st["loc"], service=0))
        skill = f"veh:{v.id}"
        # PyVRP semantics: initial load occupies room until the next hub
        # visit. Delivery dims: what is *not* on board is blocked, so the
        # first trip can hand out only what the vehicle carries.
        initial = [cap - on if mode == "delivery" else (got if mode == "pickup" else 0)
                   for cap, on, got, mode in zip(v.capacity, st["charged"], st["picked"], modes)]
        vehicles.append(v.model_copy(update={
            "start_hub": pos, "shift": (st["avail"], v.shift[1]),
            "max_reloads": max(0, v.max_reloads - st["reloads"]),
            "initial_load": initial, "skills": [*v.skills, skill],
            "rest": None if st["rest_taken"] else v.rest}))
        keep = []
        for visit in routes[v.id].visits[st["done"]:]:
            if visit.kind == "delivery" and visit.id in in_flight:
                visit = Visit(kind="job", id=f"{visit.id}_drop")
            keep.append(visit)
        warm.append(RichRoute(vehicle_id=v.id, visits=keep))
        for sid in st["in_flight"]:
            s = next(x for x in problem.shipments if x.id == sid)
            extra_jobs.append(Job(id=f"{sid}_drop", location=s.delivery.location,
                                  service=s.delivery.service, delivery=s.amount,
                                  time_window=s.delivery.time_window, required=True,
                                  priority_class=s.priority_class, skills=[*s.skills, skill]))
    # The bike's plan is gone; trim reloads beyond what each vehicle has left.
    left = {v.id: v.max_reloads for v in vehicles}
    for r in warm:
        out = []
        for visit in r.visits:
            if visit.kind == "reload":
                if left[r.vehicle_id] <= 0:
                    continue
                left[r.vehicle_id] -= 1
            out.append(visit)
        r.visits[:] = out

    k_left = {}
    for g in problem.groups:
        served = sum(1 for j in problem.group_members()[g.id] if j.id in done_items)
        k_left[g.id] = g.k - served
    groups = [g.model_copy(update={"k": k_left[g.id]}) for g in problem.groups if k_left[g.id] > 0]
    live = {g.id for g in groups}
    jobs = [j for j in problem.jobs if j.id not in done_items
            and (j.group is None or j.group in live)]
    ships = [s for s in problem.shipments if s.id not in done_items and s.id not in in_flight]
    new_jobs, new_ships = _new_events(rng, cut, add_point)
    pts = np.array(latlon)
    res = problem.model_copy(update={
        "name": f"{problem.name}_{scenario}",
        "locations": [Location(id=n, x=lon, y=lat) for n, (lat, lon) in zip(names, latlon)],
        "profiles": matrices(pts), "hubs": hubs, "vehicles": vehicles,
        "jobs": [*jobs, *extra_jobs, *new_jobs], "shipments": [*ships, *new_ships],
        "groups": groups})
    res = RichProblem.model_validate(res.model_dump())
    valid_ids = {j.id for j in res.jobs} | {s.id for s in res.shipments} | {h.id for h in res.hubs}
    warm = [RichRoute(vehicle_id=r.vehicle_id, visits=[v for v in r.visits if v.id in valid_ids])
            for r in warm]
    info = {"broken": broken, "in_flight": len(in_flight), "done_items": len(done_items),
            "old_remaining": {r.vehicle_id: [v.id for v in r.visits if v.kind == "job"]
                              for r in warm}}
    return res, RichSolution(problem_name=res.name, solver="old_plan", routes=warm), info


def stability(info: dict, sol: RichSolution) -> dict:
    new_vehicle = {v.id: r.vehicle_id for r in sol.routes for v in r.visits if v.kind == "job"}
    old = [(vid, j) for vid, js in info["old_remaining"].items() for j in js]
    if not old:
        return {"kept_same_vehicle": float("nan"), "old_dropped": float("nan")}
    return {"kept_same_vehicle": sum(new_vehicle.get(j) == vid for vid, j in old) / len(old),
            "old_dropped": sum(j not in new_vehicle for _, j in old) / len(old)}


def base_plan_path(instance: str) -> Path:
    return ROOT / "results" / "raw" / "voi_dynamic_base" / f"{instance}.json"


def run_base(args) -> dict:
    instance, _, _, seed, time_limit, cpu = args
    from . import journal, pyvrp_rich
    from .priority import STRATEGIES
    from .validate import validate
    from .voi import build

    journal.pin(cpu)
    problem = build(instance[0], int(instance[1:]))
    row = journal.start_row(instance=instance, scenario="base", arm="base", seed=seed,
                            time_limit_s=time_limit)
    t0 = time.perf_counter()
    sol = STRATEGIES["sequential_full"](pyvrp_rich, problem, time_limit_s=time_limit, seed=seed)
    path = base_plan_path(instance)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sol.model_dump_json(), encoding="utf-8")
    row |= validate(problem, sol).flat()
    return journal.finish_row(row, t0)


def run_one(args) -> dict:
    instance, scenario, arm, seed, time_limit, cpu = args
    from . import journal, pyvrp_rich
    from .priority import STRATEGIES
    from .validate import validate
    from .voi import build

    journal.pin(cpu)
    problem = build(instance[0], int(instance[1:]))
    plan = RichSolution.model_validate_json(base_plan_path(instance).read_text(encoding="utf-8"))
    row = journal.start_row(instance=instance, scenario=scenario, arm=arm, seed=seed,
                            time_limit_s=time_limit)
    t0 = time.perf_counter()
    try:
        res, warm, info = residual(problem, plan, scenario, seed=int(instance[1:]))
        row |= {"broken": info["broken"], "in_flight": info["in_flight"],
                "done_items": info["done_items"]}
        use_warm, _ = ARMS[arm]
        if use_warm is None:
            from .common import insert_rest
            sol = warm.model_copy(update={"routes": [insert_rest(res, r) for r in warm.routes]})
        else:
            t_solve = time.perf_counter()
            sol = STRATEGIES["sequential_full"](pyvrp_rich, res, time_limit_s=time_limit,
                                                seed=seed, initial=warm if use_warm else None)
            row["solve_s"] = time.perf_counter() - t_solve
        rep = validate(res, sol)
        row |= rep.flat() | stability(info, sol) | {"violations": json.dumps(rep.violations)}
        new_ids = {j.id for j in res.jobs if j.id.startswith("new_")} | \
            {s.id for s in res.shipments if s.id.startswith("new_")}
        served = {v.id for r in sol.routes for v in r.visits if v.kind in ("job", "delivery")}
        row["new_served"] = len(new_ids & served) / len(new_ids)
        row["status"] = sol.status
    except Exception as exc:
        row |= {"status": "ERROR", "notes": f"{type(exc).__name__}: {exc}"[:300]}
    return journal.finish_row(row, t0)


def main() -> None:
    from .journal import run_guarded

    ap = argparse.ArgumentParser()
    ap.add_argument("--instances", type=int, default=5)
    ap.add_argument("--tag", default="")
    args = ap.parse_args()
    raw = ROOT / "results" / "raw"
    insts = [f"M{k:02d}" for k in range(args.instances)]
    base = [(i, "base", "base", 0, BASE_TIME) for i in insts if not base_plan_path(i).exists()]
    if base:
        run_guarded(base, run_base, raw / f"voi_dynamic_base{args.tag}.jsonl", KEY)
    jobs = [(i, sc, arm, seed, t) for i in insts for sc in SCENARIOS
            for arm, (warm, t) in ARMS.items() for seed in ((0,) if warm is None else (0, 1, 2))]
    df = run_guarded(jobs, run_one, raw / f"voi_dynamic{args.tag}.jsonl", KEY)
    out = ROOT / "results" / "summary"
    df.to_csv(out / f"voi_dynamic_runs{args.tag}.csv", index=False, lineterminator="\n")
    ok = df[df.status == "SOLVED"]
    cols = ["hard_violations", "unserved_CRITICAL", "unserved_HIGH", "unserved_NORMAL",
            "unserved_LOW", "new_served", "kept_same_vehicle", "old_dropped", "soft_cost"]
    summary = ok.groupby(["scenario", "arm"])[cols + ["feasible"]].mean().reset_index()
    summary.insert(2, "runs", ok.groupby(["scenario", "arm"]).size().values)
    summary.to_csv(out / f"voi_dynamic_summary{args.tag}.csv", index=False,
                   lineterminator="\n", float_format="%.4f")
    with pd.option_context("display.width", 250, "display.max_columns", 30):
        print(summary.to_string(index=False, float_format=lambda x: f"{x:.3f}"), flush=True)


if __name__ == "__main__":
    main()

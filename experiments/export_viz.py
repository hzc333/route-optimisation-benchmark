"""Data for the explainer page (docs/viz/): the computations behind §5 and §6,
step by step, on one traffic instance (H00) and one Voi instance (M00).

    python -m experiments.export_viz        # ~5 min, writes docs/viz/viz_data.json

Everything is recomputed from the repo's own code; summary tables are read
from results/summary/*.csv. Not a timed benchmark (no CPU pinning).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "viz" / "viz_data.json"
SUMMARY = ROOT / "results" / "summary"


def _records(name: str) -> list[dict]:
    df = pd.read_csv(SUMMARY / name)
    return json.loads(df.to_json(orient="records", double_precision=4))


# Traffic ------------------------------------------------------------------

def traffic_part() -> dict:
    from adapters import get_adapter
    from traffic.bucketed import expand
    from traffic.instances import load
    from traffic.model import day_profile
    from traffic.strategies import STRATEGIES

    problem, td = load("H00")
    s0, s1 = problem.vehicles[0].shift
    times = list(range(6 * 3600, 17 * 3600 + 1, 300))
    length, cong = td.length_m, td.congestion
    n = length.shape[0]
    iu = [(i, j) for i in range(1, n) for j in range(1, n) if i != j and 2500 <= length[i, j] <= 3500]
    central = max(iu, key=lambda a: cong[a])
    outer = min(iu, key=lambda a: cong[a])
    arcs = []
    for name, (i, j) in (("市中心路段", central), ("外围路段", outer)):
        arcs.append({"name": name, "length_m": int(length[i, j]), "exposure": round(float(cong[i, j]), 2),
                     "times": times, "travel_s": [td.travel_time(i, j, t) for t in times]})

    # One untimed job near the centre and one destination: its copies and the
    # conservative leg time each copy carries.
    exp = expand(problem, td, 5400)
    untimed = [k for k, j in enumerate(problem.jobs) if j.time_window is None]
    jk = max(untimed, key=lambda k: cong[problem.jobs[k].location].mean())
    job = problem.jobs[jk]
    dest_k = max((k for k in range(len(problem.jobs)) if k != jk),
                 key=lambda k: cong[job.location, problem.jobs[k].location]
                 * (2000 <= length[job.location, problem.jobs[k].location] <= 4000))
    dest = problem.jobs[dest_k]
    dcopy = exp.groups[dest_k][0]
    copies = []
    for c in exp.groups[jk]:
        cp = exp.copies[c]
        deps = list(range(cp.lo + job.service, cp.hi + job.service + 1, 120))
        copies.append({"lo": cp.lo, "hi": cp.hi, "planned_leg_s": int(exp.matrix[c + 1, dcopy + 1]),
                       "deps": deps, "true_leg_s": [td.travel_time(job.location, dest.location, t)
                                                    for t in deps]})
    bucket_example = {"job": job.id, "dest": dest.id, "service_s": job.service,
                      "length_m": int(length[job.location, dest.location]), "copies": copies,
                      "n_jobs": len(problem.jobs), "n_copies": len(exp.copies)}

    # Two plans for the same day, replayed stop by stop in TD traffic.
    pyvrp = get_adapter("pyvrp")
    plans = {}
    for key, label in (("static_mean", "按全天平均车速规划"), ("bucketed_90", "按 90 分钟时段复制客户")):
        sol, extra = STRATEGIES[key](pyvrp, problem, td, time_limit_s=10, seed=0)
        min_start = extra["min_start"] if isinstance(extra, dict) else {}
        planning = extra if not isinstance(extra, dict) else None
        jobs = problem.job_by_id()
        routes = []
        for r in sol.routes:
            t = tp = s0
            prev = problem.depot
            stops = []
            for jid in r.job_ids:
                j = jobs[jid]
                arrive = t + td.travel_time(prev, j.location, t)
                start = max(arrive, min_start.get(jid, 0), j.time_window[0] if j.time_window else 0)
                if planning is not None:
                    tp = max(tp + int(planning[prev][j.location]),
                             j.time_window[0] if j.time_window else 0)
                    planned = tp
                    tp += j.service
                else:
                    planned = min_start.get(jid)
                late = bool(j.time_window and start > j.time_window[1])
                stops.append({"job": jid, "arrive": int(arrive), "start": int(start),
                              "window": j.time_window, "planned": planned, "late": late})
                t = start + j.service
                prev = j.location
            end = t + td.travel_time(prev, problem.depot, t)
            routes.append({"vehicle": r.vehicle_id, "stops": stops, "end": int(end)})
        plans[key] = {"label": label, "routes": routes,
                      "late_stops": sum(s["late"] for r in routes for s in r["stops"]),
                      "stops": sum(len(r["stops"]) for r in routes)}

    return {"profile": day_profile(), "bucket_s": 900, "shift": [s0, s1], "arcs": arcs,
            "bucket_example": bucket_example, "plans": plans,
            "summary": _records("traffic_summary.csv") + _records("traffic_summary_buckets.csv")}


# Voi ------------------------------------------------------------------------

def _visit_loc(problem, v):
    if v.kind == "reload":
        return problem.hub(v.id).location
    if v.kind == "job":
        return next(j for j in problem.jobs if j.id == v.id).location
    s = next(s for s in problem.shipments if s.id == v.id)
    return (s.pickup if v.kind == "pickup" else s.delivery).location


def _routes(problem, sol):
    out = []
    for r in sol.routes:
        if not r.visits:
            continue
        veh = next(v for v in problem.vehicles if v.id == r.vehicle_id)
        locs = [problem.hub(veh.start_hub).location, *(_visit_loc(problem, v) for v in r.visits),
                problem.hub(veh.end_hub).location]
        out.append({"vehicle": r.vehicle_id, "kind": veh.profile if veh.skills else "dvan",
                    "locs": locs, "visits": [[v.kind, v.id] for v in r.visits]})
    return out


def _served_value(problem, sol_or_routes) -> dict:
    """[served, total] value per class, counting an "any k of n" group as k
    members (the validator's rule), so total = what could be served."""
    routes = sol_or_routes.routes if hasattr(sol_or_routes, "routes") else sol_or_routes
    served = {v.id if hasattr(v, "id") else v[1] for r in routes
              for v in (r.visits if hasattr(r, "visits") else r["visits"])
              if (v.kind if hasattr(v, "kind") else v[0]) in ("job", "delivery")}
    out = {}
    for item in [*problem.jobs, *problem.shipments]:
        if getattr(item, "group", None) is not None:
            continue
        tot = out.setdefault(item.priority_class.value, [0, 0])
        tot[1] += item.value
        tot[0] += item.value if item.id in served else 0
    k_of = {g.id: g.k for g in problem.groups}
    for gid, members in problem.group_members().items():
        if not members:
            continue
        tot = out.setdefault(members[0].priority_class.value, [0, 0])
        tot[1] += k_of[gid] * members[0].value
        tot[0] += min(k_of[gid], sum(1 for j in members if j.id in served)) * members[0].value
    return out


def _timeline(problem, route) -> list[dict]:
    """Segments of one vehicle's day: drive / wait / serve / reload / break."""
    veh = next(v for v in problem.vehicles if v.id == route.vehicle_id)
    dur = problem.profiles[veh.profile].duration_matrix
    hubs = {h.id: h for h in problem.hubs}
    jobs = {j.id: j for j in problem.jobs}
    ships = {s.id: s for s in problem.shipments}
    t = max(route.start_time or veh.shift[0], veh.shift[0])
    segs = [{"k": "load", "a": t, "b": t + hubs[veh.start_hub].service}]
    t += hubs[veh.start_hub].service
    here = hubs[veh.start_hub].location
    rest = route.rest

    def go(loc, pos):
        nonlocal t, here
        travel = dur[here][loc]
        if rest is not None and veh.rest is not None and rest.position == pos:
            s = max(rest.start, t)
            drive_before = min(travel, s - t)
            if drive_before > 0:
                segs.append({"k": "drive", "a": t, "b": t + drive_before})
            segs.append({"k": "break", "a": s, "b": s + veh.rest.duration})
            remaining = travel - drive_before
            t = s + veh.rest.duration
            if remaining > 0:
                segs.append({"k": "drive", "a": t, "b": t + remaining})
            t += remaining
        else:
            segs.append({"k": "drive", "a": t, "b": t + travel})
            t += travel
        here = loc

    for k, v in enumerate(route.visits):
        if v.kind == "reload":
            go(hubs[v.id].location, k)
            segs.append({"k": "reload", "a": t, "b": t + hubs[v.id].service})
            t += hubs[v.id].service
            continue
        if v.kind == "job":
            j = jobs[v.id]
            loc, service, window, cls = j.location, j.service, j.time_window, j.priority_class.value
        else:
            s = ships[v.id]
            st = s.pickup if v.kind == "pickup" else s.delivery
            loc, service, window, cls = st.location, st.service, st.time_window, "SHIP"
        go(loc, k)
        if window and t < window[0]:
            segs.append({"k": "wait", "a": t, "b": window[0]})
            t = window[0]
        segs.append({"k": "serve", "a": t, "b": t + service, "c": cls})
        t += service
    go(hubs[veh.end_hub].location, len(route.visits))
    return segs


def voi_part() -> dict:
    from rich import ortools_rich, pyvrp_rich
    from rich.common import WEIGHTED_PRIZE
    from rich.dynamic import CUT, _route_state, base_plan_path, residual
    from rich.model import RichSolution
    from rich.priority import STRATEGIES, solve_sequential_full
    from rich.robust import NOISE, buffered, execute
    from rich.validate import validate
    from rich import voi
    from rich.pyvrp_rich import LATE_STEPS_S, OPEN_COPY_LATE_S
    from rich.voi import HOTSPOTS, ZONE

    problem = voi.build("M", 0)
    loc = [[round(l.y, 5), round(l.x, 5)] for l in problem.locations]
    jobs = [{"id": j.id, "loc": j.location, "cls": j.priority_class.value, "value": j.value,
             "tw": j.time_window, "soft": j.soft_due, "zone": bool(j.skills), "group": j.group}
            for j in problem.jobs]
    ships = [{"id": s.id, "from": s.pickup.location, "to": s.delivery.location,
              "required": s.required, "cls": s.priority_class.value, "value": s.value}
             for s in problem.shipments]
    vehicles = [{"id": v.id, "profile": v.profile, "cap": v.capacity, "skills": v.skills,
                 "hub": v.start_hub} for v in problem.vehicles]

    t0 = time.time()
    trace: list = []
    seq = solve_sequential_full(pyvrp_rich, problem, time_limit_s=60, seed=0, trace=trace)
    stages = [{"stage": e["stage"], "routes": _routes(problem, e["solution"]),
               "served": _served_value(problem, e["solution"]), "locked": len(e["locked"]),
               "fallback": e["fallback"]} for e in trace]
    finals = {"pyvrp_seqfull": seq,
              "pyvrp_weighted": STRATEGIES["weighted"](pyvrp_rich, problem, time_limit_s=60, seed=0),
              "ortools_seqfull": STRATEGIES["sequential_full"](ortools_rich, problem, time_limit_s=60,
                                                               seed=0)}
    final = {k: {"routes": _routes(problem, s), "served": _served_value(problem, s),
                 "report": validate(problem, s).flat()} for k, s in finals.items()}
    timelines = [{"vehicle": r.vehicle_id, "segs": _timeline(problem, r)} for r in seq.routes if r.visits]
    print(f"voi solves {time.time() - t0:.0f} s", flush=True)

    # Re-planning at 10:00 from the experiment's base plan.
    plan = RichSolution.model_validate_json(base_plan_path("M00").read_text(encoding="utf-8"))
    res, warm, info = residual(problem, plan, "events", seed=0)
    states = {r.vehicle_id: _route_state(problem, r, CUT) for r in plan.routes if r.visits}
    done_paths = []
    for r in plan.routes:
        if not r.visits:
            continue
        veh = next(v for v in problem.vehicles if v.id == r.vehicle_id)
        k = states[r.vehicle_id]["done"]
        done_paths.append({"vehicle": r.vehicle_id, "locs": [problem.hub(veh.start_hub).location]
                           + [_visit_loc(problem, v) for v in r.visits[:k]]})
    new_plan = solve_sequential_full(pyvrp_rich, res, time_limit_s=5, seed=0, initial=warm)
    replan = {"cut": CUT, "loc": [[round(l.y, 5), round(l.x, 5)] for l in res.locations],
              "done": done_paths,
              "positions": [{"vehicle": v.id, "loc": res.hub(v.start_hub).location, "avail": v.shift[0],
                             "initial_load": v.initial_load} for v in res.vehicles],
              "new_items": [{"id": j.id, "loc": j.location} for j in res.jobs if j.id.startswith("new_")]
              + [{"id": s.id, "loc": s.pickup.location} for s in res.shipments if s.id.startswith("new_")],
              "routes": _routes(res, new_plan), "report": validate(res, new_plan).flat(),
              "old_routes": _routes(res, warm)}

    # Monte Carlo execution of the plan made without / with a 20 % buffer.
    plan20 = solve_sequential_full(pyvrp_rich, buffered(problem, 0.2), time_limit_s=60, seed=0)
    robust = {}
    for key, sol in (("buffer_0", seq), ("buffer_20", plan20)):
        mc = execute(problem, sol, 300, NOISE["moderate"], seed=1000, return_samples=True)
        robust[key] = mc | {"served_jobs": validate(problem, sol).served_jobs}

    return {"loc": loc, "hubs": [{"id": h.id, "loc": h.location} for h in problem.hubs],
            "hotspots": [{"name": k, "lat": v[0], "lon": v[1]} for k, v in HOTSPOTS.items()],
            "zone": ZONE, "jobs": jobs, "ships": ships, "vehicles": vehicles,
            "weighted_prize": {c.value: p for c, p in WEIGHTED_PRIZE.items()},
            "soft": {"steps_s": list(LATE_STEPS_S), "open_s": OPEN_COPY_LATE_S,
                     "late_cost": problem.soft_late_cost, "due": voi.SOFT_DUE},
            "rest": problem.vehicles[0].rest.model_dump(), "shift": problem.vehicles[0].shift,
            "stages": stages, "final": final, "timelines": timelines, "replan": replan,
            "robust": robust,
            "summary": {"main": _records("voi_summary_final.csv"), "scale": _records("voi_summary_scale.csv"),
                        "dynamic": _records("voi_dynamic_summary.csv"),
                        "robust": _records("voi_robust_summary.csv")}}


def main() -> None:
    import warnings

    warnings.filterwarnings("ignore")
    t0 = time.time()
    data = {"generated": time.strftime("%Y-%m-%d"), "traffic": traffic_part()}
    print(f"traffic part {time.time() - t0:.0f} s", flush=True)
    data["voi"] = voi_part()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":"),
                              default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)),
                   encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.2f} MB) in {time.time() - t0:.0f} s", flush=True)


if __name__ == "__main__":
    main()

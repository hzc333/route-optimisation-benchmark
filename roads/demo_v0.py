"""Shared demo for the map-solver bridge, in data format v0
(D:/route_opti/Meeting_Prep_Map_Solver_Bridge.md, section 2.2).

    python -m roads.demo_v0          # writes roads/exchange/demo_v0/

26 hand-picked stops at real Stockholm places, one depot, a van and a cargo
bike. 4 stops are required (2 with an 08:00-09:00 window); 22 are optional in
four priority classes. Every stop takes one battery and the two vehicles carry
16 in total, so about 10 optional stops must be left out: the priorities
decide which. Two stops are placed where snapping may go wrong (a quay by the
water, inside a park) to test how unreachable stops are reported.

Outputs:
  demo_request_v0.json    solve request (example 1 of the format)
  demo_stops_v0.csv       the same stops for roads/build_matrices.py
  demo_plan_v0_straight_line.json
                          the solver's plan using straight-line distances,
                          a placeholder until Valhalla matrices replace them
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from schema.models import Location, PriorityClass

OUT = Path(__file__).resolve().parent / "exchange" / "demo_v0"

DEPOT = {"id": "HUB", "name": "Depot (Årsta)", "lat": 59.2985, "lon": 18.0400}
# id, place, lat, lon, required, priority, value, time window, note
STOPS = [
    ("r1", "T-Centralen", 59.3310, 18.0590, True, None, None, ("08:00", "09:00"), ""),
    ("r2", "Slussen", 59.3195, 18.0720, True, None, None, ("08:00", "09:00"), ""),
    ("r3", "Fridhemsplan", 59.3320, 18.0290, True, None, None, None, ""),
    ("r4", "Medborgarplatsen", 59.3143, 18.0735, True, None, None, None, ""),
    ("c1", "Odenplan", 59.3429, 18.0496, False, "CRITICAL", 4, None, ""),
    ("c2", "Hötorget", 59.3355, 18.0630, False, "CRITICAL", 4, None, ""),
    ("c3", "Östermalmstorg", 59.3350, 18.0770, False, "CRITICAL", 4, None, ""),
    ("h1", "KTH", 59.3456, 18.0715, False, "HIGH", 3, None, ""),
    ("h2", "S:t Eriksplan", 59.3395, 18.0370, False, "HIGH", 3, None, ""),
    ("h3", "Mariatorget", 59.3170, 18.0630, False, "HIGH", 3, None, ""),
    ("h4", "Skanstull", 59.3080, 18.0760, False, "HIGH", 3, None, ""),
    ("h5", "Rådmansgatan", 59.3405, 18.0585, False, "HIGH", 3, None, ""),
    ("h6", "Stadshagen", 59.3365, 18.0175, False, "HIGH", 3, None, ""),
    ("n1", "Liljeholmen", 59.3100, 18.0230, False, "NORMAL", 2, None, ""),
    ("n2", "Gullmarsplan", 59.2990, 18.0810, False, "NORMAL", 2, None, ""),
    ("n3", "Hornstull", 59.3157, 18.0340, False, "NORMAL", 2, None, ""),
    ("n4", "Zinkensdamm", 59.3177, 18.0500, False, "NORMAL", 2, None, ""),
    ("n5", "Karlaplan", 59.3389, 18.0904, False, "NORMAL", 2, None, ""),
    ("n6", "Gärdet", 59.3460, 18.0990, False, "NORMAL", 2, None, ""),
    ("n7", "Thorildsplan", 59.3318, 18.0150, False, "NORMAL", 2, None, ""),
    ("n8", "Riddarfjärden quay", 59.3238, 18.0560, False, "NORMAL", 2, None,
     "snap test: by the water"),
    ("l1", "Hammarby sjöstad", 59.3035, 18.1000, False, "LOW", 1, None, ""),
    ("l2", "Årstaberg", 59.2990, 18.0300, False, "LOW", 1, None, ""),
    ("l3", "Telefonplan", 59.2980, 17.9970, False, "LOW", 1, None, ""),
    ("l4", "Södra Hammarbyhamnen", 59.3045, 18.0880, False, "LOW", 1, None, ""),
    ("l5", "Djurgården (park)", 59.3268, 18.1150, False, "LOW", 1, None,
     "snap test: inside a park"),
]
VEHICLES = [
    {"id": "van1", "profile": "van", "capacity": 10, "shift": ["07:00", "11:00"]},
    {"id": "bike1", "profile": "cargo_bike", "capacity": 6, "shift": ["07:00", "11:00"]},
]
SERVICE_S = 150


def request() -> dict:
    stops = []
    for sid, place, lat, lon, required, prio, value, tw, note in STOPS:
        s = {"id": sid, "name": place, "lat": lat, "lon": lon, "service_s": SERVICE_S,
             "demand": 1, "required": required}
        if tw:
            s["time_window"] = list(tw)
        if not required:
            s["priority"], s["value"] = prio, value
        if note:
            s["note"] = note
        stops.append(s)
    return {"format": "route-opti-request/v0", "depot": DEPOT, "stops": stops, "vehicles": VEHICLES,
            "options": {"priority_mode": "strict", "time_limit_s": 10}}


def to_seconds(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 3600 + int(m) * 60


def to_hhmm(seconds: int) -> str:
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}"


def rich_problem(req: dict, profiles=None):
    """v0 request -> RichProblem. Without ``profiles`` the straight-line
    matrices of rich.voi are used (placeholder until Valhalla matrices)."""
    from rich.model import Hub, Job, RichProblem, Vehicle
    from rich.voi import matrices

    depot, stops = req["depot"], req["stops"]
    pts = [(depot["lat"], depot["lon"])] + [(s["lat"], s["lon"]) for s in stops]
    jobs = []
    for k, s in enumerate(stops, start=1):
        tw = tuple(to_seconds(t) for t in s["time_window"]) if s.get("time_window") else None
        jobs.append(Job(id=s["id"], location=k, service=s["service_s"], delivery=[s["demand"]],
                        time_window=tw, required=s["required"],
                        priority_class=PriorityClass(s.get("priority") or "NORMAL"),
                        value=s.get("value") or 1))
    profile_of = {"van": "van", "cargo_bike": "bike"}
    vehicles = [Vehicle(id=v["id"], profile=profile_of[v["profile"]], capacity=[v["capacity"]],
                        start_hub=depot["id"], end_hub=depot["id"],
                        shift=tuple(to_seconds(t) for t in v["shift"]),
                        duration_cost=83, distance_cost=2 if v["profile"] == "van" else 1,
                        skills=["zero_emission"])
                for v in req["vehicles"]]
    return RichProblem(
        name="demo_v0", dims=["batteries"],
        locations=[Location(id=depot["id"], x=depot["lon"], y=depot["lat"])]
        + [Location(id=s["id"], x=s["lon"], y=s["lat"]) for s in stops],
        profiles=profiles or matrices(np.array(pts)), hubs=[Hub(id=depot["id"], location=0)],
        vehicles=vehicles, jobs=jobs)


def plan_v0(problem, solution) -> dict:
    """Solver result -> plan in format v0 (example 3); paths come from Valhalla later."""
    from rich.validate import simulate_route, validate

    jobs = {j.id: j for j in problem.jobs}
    routes = []
    for r in solution.routes:
        if not r.visits:
            continue
        sim = simulate_route(problem, r)
        stops = [{"id": v.id, "start": to_hhmm(sim.service_starts[f"job:{v.id}"])} for v in r.visits]
        routes.append({"vehicle": r.vehicle_id, "stops": stops, "return": to_hhmm(sim.end),
                       "distance_m": sim.distance, "path": None})
    served = {v.id for r in solution.routes for v in r.visits}
    unserved = [{"id": j.id, "priority": j.priority_class.value, "reason": "not enough capacity or time"}
                for j in problem.jobs if j.id not in served]
    rep = validate(problem, solution)
    return {"format": "route-opti-plan/v0", "matrices": "straight-line placeholder, not Valhalla",
            "routes": routes, "unserved": unserved,
            "summary": {"feasible": rep.feasible, "distance_m": rep.distance_m,
                        "served": len(served), "unserved": len(unserved)}}


def main() -> None:
    from rich import pyvrp_rich
    from rich.priority import solve_sequential_full

    OUT.mkdir(parents=True, exist_ok=True)
    req = request()
    (OUT / "demo_request_v0.json").write_text(json.dumps(req, ensure_ascii=False, indent=2),
                                              encoding="utf-8")
    with open(OUT / "demo_stops_v0.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["id", "lat", "lon", "kind", "name", "required", "priority", "note"])
        w.writerow([DEPOT["id"], DEPOT["lat"], DEPOT["lon"], "depot", DEPOT["name"], "", "", ""])
        for s in req["stops"]:
            w.writerow([s["id"], s["lat"], s["lon"], "stop", s["name"], int(s["required"]),
                        s.get("priority", ""), s.get("note", "")])
    problem = rich_problem(req)
    sol = solve_sequential_full(pyvrp_rich, problem, time_limit_s=req["options"]["time_limit_s"], seed=0)
    plan = plan_v0(problem, sol)
    (OUT / "demo_plan_v0_straight_line.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2),
                                                         encoding="utf-8")
    print(f"wrote {OUT}: {len(req['stops'])} stops, plan feasible={plan['summary']['feasible']}, "
          f"served {plan['summary']['served']}, unserved {[u['id'] for u in plan['unserved']]}")


if __name__ == "__main__":
    main()

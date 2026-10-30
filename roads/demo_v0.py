"""Shared demo for the map-solver bridge, in data format v0
(D:/route_opti/Meeting_Prep_Map_Solver_Bridge.md, section 2.2).

    python -m roads.demo_v0 make                       # request + stop list
    python -m roads.demo_v0 solve                      # straight-line placeholder
    python -m roads.demo_v0 solve --matrices FILE      # real road matrices from Valhalla
    python -m roads.demo_v0 map --routes FILE          # redraw with Valhalla road paths

Files live in roads/exchange/demo_v0/:

  demo_request_v0.json        solve request (example 1 of the format)
  demo_stops_v0.csv           the stops for roads/build_matrices.py (send to Eren)
  demo_stops_v0.matrices.json matrices returned by Eren (example 2)
  demo_plan_v0.json           the solver's plan (example 3); "_straight_line"
                              suffix when no matrices were given
  demo_plan_v0.routes.json    road paths for the plan, from roads/build_routes.py
  demo_map.html               map of the plan; open it in a browser

26 hand-picked stops at real Stockholm places, one depot, a van and a cargo
bike. 4 stops are required (2 with an 08:00-09:00 window); 22 are optional in
four priority classes. Every stop takes one battery and the two vehicles carry
16 in total, so about 10 optional stops must be left out: the priorities
decide which. Two stops are placed where snapping may go wrong (a quay by the
water, inside a park) to test how unreachable stops are reported.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

import numpy as np

from schema.models import Location, PriorityClass

OUT = Path(__file__).resolve().parent / "exchange" / "demo_v0"
REQUEST = OUT / "demo_request_v0.json"

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
# request vehicle profile -> matrix profile in a Valhalla matrix file
MATRIX_PROFILE = {"van": "van", "cargo_bike": "bike"}


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


def matrix_profiles(req: dict, path: Path) -> tuple[dict, dict]:
    """Profiles from a Valhalla matrix file, in the request's order, plus a
    short report (unreachable pairs, far-snapped stops, build time)."""
    from rich.model import Profile
    from roads.load_matrices import UNREACHABLE, load

    data = load(path)
    ids = [s["id"] for s in data["stops"]]
    want = [req["depot"]["id"]] + [s["id"] for s in req["stops"]]
    missing = [i for i in want if i not in ids]
    if missing:
        raise SystemExit(f"{path.name} lacks stops {missing}: was it built from demo_stops_v0.csv?")
    order = [ids.index(i) for i in want]

    def mat(rows):
        m = np.array([[UNREACHABLE if v is None else v for v in row] for row in rows], dtype=np.int64)
        m = m[np.ix_(order, order)]
        np.fill_diagonal(m, 0)
        return m.tolist()

    profiles, report = {}, {"valhalla": data["valhalla"].get("status", {}).get("version"),
                            "build_seconds": data.get("total_seconds"), "profiles": {}}
    for v in req["vehicles"]:
        name = MATRIX_PROFILE[v["profile"]]
        if name not in data["profiles"]:
            raise SystemExit(f"{path.name} has no '{name}' matrices (profiles: {list(data['profiles'])})")
        p = data["profiles"][name]
        solver_name = "van" if v["profile"] == "van" else "bike"
        profiles[solver_name] = Profile(distance_matrix=mat(p["distance_m"]), duration_matrix=mat(p["duration_s"]))
        dur = np.array(mat(p["duration_s"]))
        bad = sorted({want[i] for i, j in zip(*np.where(dur >= UNREACHABLE))} |
                     {want[j] for i, j in zip(*np.where(dur >= UNREACHABLE))})
        report["profiles"][name] = {"unreachable_stops": bad}
    snaps = [r for rows in (data.get("snap") or {}).values() for r in rows or []]
    report["far_snaps"] = sorted({(r["id"], r["snap_m"]) for r in snaps if (r.get("snap_m") or 0) > 50},
                                 key=lambda t: -t[1])
    return profiles, report


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
    vehicles = [Vehicle(id=v["id"], profile="van" if v["profile"] == "van" else "bike",
                        capacity=[v["capacity"]], start_hub=depot["id"], end_hub=depot["id"],
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


def plan_v0(req: dict, problem, solution, source: str) -> dict:
    """Solver result -> plan in format v0 (example 3). Road paths are added
    later from Valhalla (roads/build_routes.py)."""
    from rich.validate import simulate_route, validate

    stop = {s["id"]: s for s in req["stops"]}
    prof = {v["id"]: v["profile"] for v in req["vehicles"]}
    routes = []
    for r in solution.routes:
        if not r.visits:
            continue
        sim = simulate_route(problem, r)
        stops = [{"id": v.id, "name": stop[v.id]["name"], "lat": stop[v.id]["lat"], "lon": stop[v.id]["lon"],
                  "start": to_hhmm(sim.service_starts[f"job:{v.id}"])} for v in r.visits]
        routes.append({"vehicle": r.vehicle_id, "profile": prof[r.vehicle_id], "leave": to_hhmm(sim.start),
                       "stops": stops, "return": to_hhmm(sim.end), "distance_m": sim.distance,
                       "path": None})
    served = {v.id for r in solution.routes for v in r.visits}
    unserved = [{"id": s["id"], "name": s["name"], "lat": s["lat"], "lon": s["lon"],
                 "priority": s.get("priority") or "REQUIRED", "reason": "not enough capacity or time"}
                for s in req["stops"] if s["id"] not in served]
    rep = validate(problem, solution)
    return {"format": "route-opti-plan/v0", "matrices": source, "depot": req["depot"],
            "routes": routes, "unserved": unserved,
            "summary": {"feasible": rep.feasible, "violations": rep.violations,
                        "distance_m": rep.distance_m, "served": len(served), "unserved": len(unserved)}}


MAP_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Demo v0 plan</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
 body { margin: 0; font: 14px/1.5 system-ui, sans-serif; }
 #map { position: absolute; top: 0; bottom: 0; left: 0; right: 320px; }
 #side { position: absolute; top: 0; bottom: 0; right: 0; width: 320px; overflow: auto; padding: 12px 14px;
         box-sizing: border-box; border-left: 1px solid #ddd; background: #fafafa; }
 h1 { font-size: 17px; margin: 0 0 6px; } .muted { color: #666; font-size: 12px; }
 .row { display: flex; align-items: center; gap: 6px; margin: 2px 0; }
 .dot { width: 11px; height: 11px; border-radius: 50%; display: inline-block; border: 2px solid #fff; box-shadow: 0 0 0 1px #999; }
 .pin { width: 22px; height: 22px; border-radius: 50%; border: 2px solid #fff; box-shadow: 0 0 0 1px #444;
        box-sizing: border-box; font: 700 11px/18px system-ui, sans-serif; text-align: center; }
 table { border-collapse: collapse; width: 100%; font-size: 12.5px; } td { padding: 2px 4px; border-bottom: 1px solid #eee; }
</style></head><body>
<div id="map"></div><div id="side"></div>
<script>
const PLAN = __PLAN__;
const COLORS = {REQUIRED: "#111111", CRITICAL: "#e34948", HIGH: "#eda100", NORMAL: "#2a78d6", LOW: "#8f8e88"};
const VEH = ["#0e6a73", "#b0459a", "#5b6ee1", "#c06a1b"];
const map = L.map("map");
// Esri tiles: OSM's own tile servers refuse pages opened from file:// (no Referer -> 403)
L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
  {maxZoom: 19, attribution: "Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors"}).addTo(map);
const prio = {}; for (const s of PLAN.request_stops) prio[s.id] = s.required ? "REQUIRED" : s.priority;
const bounds = [];
const depot = PLAN.depot; bounds.push([depot.lat, depot.lon]);
L.marker([depot.lat, depot.lon]).addTo(map).bindPopup("<b>" + depot.name + "</b>");
PLAN.routes.forEach((r, k) => {
  const pts = r.path || [[depot.lat, depot.lon], ...r.stops.map(s => [s.lat, s.lon]), [depot.lat, depot.lon]];
  L.polyline(pts, {color: VEH[k % VEH.length], weight: 4, opacity: 0.8, dashArray: r.path ? null : "6 6"})
    .addTo(map).bindPopup(r.vehicle + " (" + r.profile + "): leaves " + r.leave + ", back " + r.return);
  r.stops.forEach((s, i) => {
    bounds.push([s.lat, s.lon]);
    const ink = prio[s.id] === "HIGH" ? "#111" : "#fff";
    L.marker([s.lat, s.lon], {icon: L.divIcon({className: "", iconSize: [22, 22], iconAnchor: [11, 11],
      html: "<div class='pin' style='background:" + COLORS[prio[s.id]] + ";color:" + ink + "'>" + (i + 1) + "</div>"})})
      .addTo(map).bindPopup("<b>" + s.name + "</b> (" + s.id + ")<br>" + prio[s.id] + "<br>" + r.vehicle + ", stop " + (i + 1) + ", starts " + s.start);
  });
});
for (const u of PLAN.unserved) {
  bounds.push([u.lat, u.lon]);
  L.circleMarker([u.lat, u.lon], {radius: 7, color: COLORS[u.priority], weight: 2, fillColor: "#fff", fillOpacity: 1})
    .addTo(map).bindPopup("<b>" + u.name + "</b> (" + u.id + ")<br>" + u.priority + "<br>not served: " + u.reason);
}
const fit = () => { map.invalidateSize(); map.fitBounds(bounds, {padding: [30, 30], maxZoom: 15}); };
fit(); window.addEventListener("load", fit); window.addEventListener("resize", fit);
const side = document.getElementById("side");
let h = "<h1>Demo v0 plan</h1><div class='muted'>Distances: " + PLAN.matrices + "<br>Lines: " +
  (PLAN.routes.some(r => r.path) ? "Valhalla road paths" : "straight lines between stops (road paths not added yet)") + "</div>";
h += "<p>Served " + PLAN.summary.served + ", not served " + PLAN.summary.unserved + ", " +
  (PLAN.summary.distance_m / 1000).toFixed(1) + " km in total" + (PLAN.summary.feasible ? "" : " — <b>plan breaks a rule</b>") + "</p>";
for (const [k, c] of Object.entries(COLORS)) h += "<div class='row'><span class='dot' style='background:" + c + "'></span>" + (k === "REQUIRED" ? "required" : k) + "</div>";
h += "<div class='row'><span class='dot' style='background:#fff'></span>hollow = not served</div>";
PLAN.routes.forEach((r, k) => {
  h += "<h1 style='margin-top:12px;color:" + VEH[k % VEH.length] + "'>" + r.vehicle + " (" + r.profile + ")</h1><table>";
  h += "<tr><td></td><td>depot</td><td>" + r.leave + "</td></tr>";
  r.stops.forEach((s, i) => h += "<tr><td>" + (i + 1) + "</td><td>" + s.name + "</td><td>" + s.start + "</td></tr>");
  h += "<tr><td></td><td>back at depot</td><td>" + r.return + "</td></tr></table>";
});
if (PLAN.unserved.length) h += "<h1 style='margin-top:12px'>Not served</h1><div>" + PLAN.unserved.map(u => u.name + " (" + u.priority + ")").join(", ") + "</div>";
side.innerHTML = h;
</script></body></html>
"""


def write_map(plan: dict, req: dict, path: Path) -> None:
    data = dict(plan, request_stops=req["stops"])
    path.write_text(MAP_TEMPLATE.replace("__PLAN__", json.dumps(data, ensure_ascii=False)), encoding="utf-8")


def cmd_make(_args) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    req = request()
    REQUEST.write_text(json.dumps(req, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(OUT / "demo_stops_v0.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["id", "lat", "lon", "kind", "name", "required", "priority", "note"])
        w.writerow([DEPOT["id"], DEPOT["lat"], DEPOT["lon"], "depot", DEPOT["name"], "", "", ""])
        for s in req["stops"]:
            w.writerow([s["id"], s["lat"], s["lon"], "stop", s["name"], int(s["required"]),
                        s.get("priority", ""), s.get("note", "")])
    print(f"wrote {REQUEST.name} and demo_stops_v0.csv in {OUT}")


def cmd_solve(args) -> None:
    from rich import pyvrp_rich
    from rich.priority import solve_sequential_full

    req = json.loads(REQUEST.read_text(encoding="utf-8"))
    if args.matrices:
        path = Path(args.matrices)
        profiles, report = matrix_profiles(req, path)
        source = f"Valhalla road matrices ({path.name}, Valhalla {report['valhalla']})"
        print(f"matrices: {path.name}, Valhalla {report['valhalla']}, built in {report['build_seconds']} s")
        for name, r in report["profiles"].items():
            print(f"  {name}: unreachable stops {r['unreachable_stops'] or 'none'}")
        if report["far_snaps"]:
            print("  snapped more than 50 m from the given point: "
                  + ", ".join(f"{i} {m:.0f} m" for i, m in report["far_snaps"]))
        stem = "demo_plan_v0"
    else:
        profiles, source, stem = None, "straight-line placeholder, not Valhalla", "demo_plan_v0_straight_line"
        print("no --matrices given: using straight-line distances as a placeholder")
    problem = rich_problem(req, profiles)
    limit = args.time_limit or req["options"]["time_limit_s"]
    t0 = time.perf_counter()
    sol = solve_sequential_full(pyvrp_rich, problem, time_limit_s=limit, seed=0)
    plan = plan_v0(req, problem, sol, source)
    plan_path = OUT / f"{stem}.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    write_map(plan, req, OUT / "demo_map.html")

    print(f"solved in {time.perf_counter() - t0:.1f} s; rules all kept: {plan['summary']['feasible']}"
          + ("" if plan["summary"]["feasible"] else f" {plan['summary']['violations']}"))
    for r in plan["routes"]:
        print(f"  {r['vehicle']:6s} leaves {r['leave']}  " + "  ".join(f"{s['id']}@{s['start']}" for s in r["stops"])
              + f"  back {r['return']}  ({r['distance_m'] / 1000:.1f} km)")
    print("  not served: " + (", ".join(f"{u['id']} ({u['priority']})" for u in plan["unserved"]) or "none"))
    print(f"wrote {plan_path.name} and demo_map.html in {OUT}")


def cmd_map(args) -> None:
    req = json.loads(REQUEST.read_text(encoding="utf-8"))
    plan_path = Path(args.plan) if args.plan else OUT / "demo_plan_v0.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    routes = json.loads(Path(args.routes).read_text(encoding="utf-8"))
    paths = {r["vehicle"]: r["path"] for r in routes["routes"]}
    for r in plan["routes"]:
        r["path"] = paths.get(r["vehicle"])
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    write_map(plan, req, OUT / "demo_map.html")
    print(f"added road paths for {sorted(paths)}; wrote demo_map.html in {OUT}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Demo v0 for the map-solver bridge")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("make", help="write the request and the stop list")
    s = sub.add_parser("solve", help="solve and draw the plan")
    s.add_argument("--matrices", help="matrix file from Valhalla (build_matrices.py output)")
    s.add_argument("--time-limit", type=float, help="seconds for the solver (default: request's 10)")
    m = sub.add_parser("map", help="redraw the map with Valhalla road paths")
    m.add_argument("--routes", required=True, help="routes file from build_routes.py")
    m.add_argument("--plan", help="plan file (default demo_plan_v0.json)")
    args = ap.parse_args()
    {"make": cmd_make, "solve": cmd_solve, "map": cmd_map}[args.cmd](args)


if __name__ == "__main__":
    main()

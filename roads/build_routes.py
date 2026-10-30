#!/usr/bin/env python3
"""Road paths for a solver plan, from Valhalla's /route.

Standalone: Python 3.8+ standard library only, no install needed.

    python build_routes.py demo_plan_v0.json --url http://localhost:8002

Reads a plan (format route-opti-plan/v0: depot plus each vehicle's ordered
stops with lat/lon), asks Valhalla for one route per vehicle (depot -> stops
-> depot) and writes <plan>.routes.json with, per vehicle, the road path as a
list of [lat, lon] points and the length and time of every leg. Send that
file back; `python -m roads.demo_v0 map --routes ...` draws it.

Vehicle profiles map to Valhalla costing: van -> auto, cargo_bike -> bicycle
(edit COSTING below).
"""

import argparse
import json
import sys
import urllib.error
import urllib.request

COSTING = {"van": ("auto", {}), "cargo_bike": ("bicycle", {"bicycle_type": "City", "cycling_speed": 15})}


def decode_polyline(encoded, precision=6):
    """Valhalla shapes are encoded polylines with 6 decimals -> [[lat, lon], ...]."""
    coords, index, lat, lon = [], 0, 0, 0
    factor = 10 ** precision
    while index < len(encoded):
        for which in (0, 1):
            shift = result = 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if which == 0:
                lat += delta
            else:
                lon += delta
        coords.append([round(lat / factor, 6), round(lon / factor, 6)])
    return coords


def route(url, locations, costing, options, timeout):
    payload = {"locations": [{"lat": p[0], "lon": p[1]} for p in locations],
               "costing": costing, "units": "kilometers"}
    if options:
        payload["costing_options"] = {costing: options}
    req = urllib.request.Request(url.rstrip("/") + "/route", data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        sys.exit("Valhalla /route failed (HTTP %s): %s" % (exc.code, exc.read().decode("utf-8", "replace")[:400]))
    except urllib.error.URLError as exc:
        sys.exit("cannot reach Valhalla at %s: %s" % (url, exc))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("plan", help="plan JSON from the solver")
    ap.add_argument("--url", default="http://localhost:8002", help="Valhalla service")
    ap.add_argument("--timeout", type=float, default=60)
    ap.add_argument("--out", help="output JSON (default: <plan>.routes.json)")
    args = ap.parse_args()

    with open(args.plan, encoding="utf-8") as fh:
        plan = json.load(fh)
    depot = (plan["depot"]["lat"], plan["depot"]["lon"])
    out = {"format": "route-opti-routes/1", "plan": args.plan, "routes": []}
    for r in plan["routes"]:
        costing, options = COSTING.get(r.get("profile"), ("auto", {}))
        locations = [depot] + [(s["lat"], s["lon"]) for s in r["stops"]] + [depot]
        resp = route(args.url, locations, costing, options, args.timeout)
        legs = resp["trip"]["legs"]
        path = []
        for leg in legs:
            pts = decode_polyline(leg["shape"])
            path.extend(pts if not path else pts[1:])
        summary = resp["trip"]["summary"]
        out["routes"].append({
            "vehicle": r["vehicle"], "costing": costing, "path": path,
            "length_km": summary.get("length"), "time_s": summary.get("time"),
            "legs": [{"length_km": l["summary"].get("length"), "time_s": l["summary"].get("time")} for l in legs]})
        print("%s: %d stops, %.1f km, %.0f min" % (r["vehicle"], len(r["stops"]),
                                                   summary.get("length", 0), summary.get("time", 0) / 60))
    target = args.out or (args.plan.rsplit(".", 1)[0] + ".routes.json")
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(out, fh)
    print("wrote", target)


if __name__ == "__main__":
    main()

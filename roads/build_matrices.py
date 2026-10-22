#!/usr/bin/env python3
"""Build travel-time and distance matrices for a stop list with Valhalla.

Standalone: Python 3.8+ standard library only, no install needed.

    python build_matrices.py stops_M00.csv --url http://localhost:8002
    python build_matrices.py stops_M00.csv --zone zone.geojson --block 50 --workers 4

Input  CSV with columns id,lat,lon (other columns are ignored).
Output stops_M00.matrices.json next to the CSV (or --out), containing for
each vehicle profile an N x N distance matrix (whole metres) and duration
matrix (whole seconds) in the CSV's row order; null marks a pair Valhalla
could not route. Also records how far each stop was snapped to the road,
the Valhalla version, and how long every profile took to build.

Profiles (edit PROFILES below to change costing options):

    van          auto     electric van
    van_no_zone  auto     diesel van: the --zone polygon is excluded
    bike         bicycle  electric cargo bike

The matrix is requested in blocks of --block x --block pairs, because
Valhalla's default service_limits cap the pairs per request; raise --block
if your valhalla.json allows more (fewer, faster requests).
"""

import argparse
import concurrent.futures
import csv
import datetime as dt
import json
import math
import sys
import time
import urllib.error
import urllib.request

FORMAT = "route-opti-matrices/1"

PROFILES = {
    "van": {"costing": "auto", "costing_options": {"auto": {}}, "exclude_zone": False},
    "van_no_zone": {"costing": "auto", "costing_options": {"auto": {}}, "exclude_zone": True},
    "bike": {"costing": "bicycle",
             "costing_options": {"bicycle": {"bicycle_type": "City", "cycling_speed": 15}},
             "exclude_zone": False},
}


def post(url, path, payload, timeout, retries=3):
    data = json.dumps(payload).encode("utf-8")
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(url.rstrip("/") + path, data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:500]
            last = RuntimeError("HTTP %s on %s: %s" % (exc.code, path, body))
            if exc.code < 500:
                break  # a request error will not fix itself
        except (urllib.error.URLError, TimeoutError) as exc:
            last = RuntimeError("cannot reach %s%s: %s" % (url, path, exc))
        time.sleep(1.5 * (attempt + 1))
    raise last


def get(url, path, timeout):
    try:
        with urllib.request.urlopen(url.rstrip("/") + path, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # status is informational only
        return {"error": str(exc)}


def read_stops(path):
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows or not {"id", "lat", "lon"} <= set(rows[0]):
        sys.exit("%s: need columns id,lat,lon" % path)
    stops = [{"id": r["id"], "lat": float(r["lat"]), "lon": float(r["lon"])} for r in rows]
    if len({s["id"] for s in stops}) != len(stops):
        sys.exit("%s: ids must be unique" % path)
    return stops


def read_zone(path):
    """GeoJSON Polygon / MultiPolygon / Feature(Collection) -> list of [lon, lat] rings."""
    with open(path, encoding="utf-8") as fh:
        gj = json.load(fh)
    feats = gj["features"] if gj.get("type") == "FeatureCollection" else [gj]
    rings = []
    for f in feats:
        geom = f.get("geometry", f)
        if geom["type"] == "Polygon":
            rings.append(geom["coordinates"][0])
        elif geom["type"] == "MultiPolygon":
            rings.extend(poly[0] for poly in geom["coordinates"])
    if not rings:
        sys.exit("%s: no polygon found" % path)
    return rings


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def parse_block(resp, n_src, n_tgt):
    """Valhalla returns either a list of rows of {distance, time} objects
    (verbose) or {durations, distances} arrays (concise); both -> (dist_km, time_s)."""
    body = resp["sources_to_targets"]
    dist = [[None] * n_tgt for _ in range(n_src)]
    dur = [[None] * n_tgt for _ in range(n_src)]
    if isinstance(body, dict):
        for i in range(n_src):
            for j in range(n_tgt):
                dist[i][j] = body["distances"][i][j]
                dur[i][j] = body["durations"][i][j]
        return dist, dur
    for i, row in enumerate(body):
        for j, cell in enumerate(row):
            fi = cell.get("from_index", i)
            tj = cell.get("to_index", j)
            dist[fi][tj] = cell.get("distance")
            dur[fi][tj] = cell.get("time")
    return dist, dur


def build_profile(name, spec, stops, args, zone):
    n = len(stops)
    locs = [{"lat": s["lat"], "lon": s["lon"]} for s in stops]
    dist = [[None] * n for _ in range(n)]
    dur = [[None] * n for _ in range(n)]
    base = {"costing": spec["costing"], "costing_options": spec["costing_options"],
            "units": "kilometers"}
    if spec["exclude_zone"]:
        if zone is None:
            print("  %s: no --zone given, built without excluded area" % name, file=sys.stderr)
        else:
            base["exclude_polygons"] = zone
    if args.depart_at:
        base["date_time"] = {"type": 1, "value": args.depart_at}
    blocks = [(a, b) for a in range(0, n, args.block) for b in range(0, n, args.block)]

    def run(block):
        a, b = block
        src, tgt = locs[a:a + args.block], locs[b:b + args.block]
        resp = post(args.url, "/sources_to_targets",
                    dict(base, sources=src, targets=tgt), args.timeout)
        return a, b, parse_block(resp, len(src), len(tgt))

    t0 = time.perf_counter()
    done = 0
    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        for a, b, (bd, bt) in pool.map(run, blocks):
            for i, row in enumerate(bd):
                for j, v in enumerate(row):
                    dist[a + i][b + j] = None if v is None else int(round(v * 1000))
                    t = bt[i][j]
                    dur[a + i][b + j] = None if t is None else int(round(t))
            done += 1
            if done % 20 == 0 or done == len(blocks):
                print("  %s: %d/%d blocks" % (name, done, len(blocks)), flush=True)
    seconds = time.perf_counter() - t0
    for i in range(n):
        dist[i][i], dur[i][i] = 0, 0
    unreachable = sum(1 for i in range(n) for j in range(n) if dur[i][j] is None)
    return {"costing": spec["costing"], "costing_options": spec["costing_options"],
            "exclude_zone": bool(spec["exclude_zone"] and zone is not None),
            "depart_at": args.depart_at, "distance_m": dist, "duration_s": dur,
            "unreachable_pairs": unreachable, "build_seconds": round(seconds, 2),
            "requests": len(blocks), "block": args.block}


def snap(stops, costing, args):
    """Where each stop lands on the road network (Valhalla /locate)."""
    out = []
    for k in range(0, len(stops), 100):
        chunk = stops[k:k + 100]
        try:
            resp = post(args.url, "/locate", {"locations": [{"lat": s["lat"], "lon": s["lon"]}
                                                           for s in chunk],
                                              "costing": costing, "verbose": False},
                        args.timeout)
        except RuntimeError as exc:
            print("  snapping skipped: %s" % exc, file=sys.stderr)
            return None
        for s, loc in zip(chunk, resp):
            edges = (loc or {}).get("edges") or []
            if not edges:
                out.append({"id": s["id"], "snap_m": None})
                continue
            e = edges[0]
            lat, lon = e.get("correlated_lat"), e.get("correlated_lon")
            out.append({"id": s["id"], "snapped_lat": lat, "snapped_lon": lon,
                        "side_of_street": e.get("side_of_street"),
                        "snap_m": None if lat is None else round(haversine_m(s["lat"], s["lon"], lat, lon), 1)})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("stops", help="CSV with id,lat,lon")
    ap.add_argument("--url", default="http://localhost:8002", help="Valhalla service")
    ap.add_argument("--zone", help="GeoJSON polygon excluded for the van_no_zone profile")
    ap.add_argument("--profiles", default=",".join(PROFILES), help="comma list of profiles")
    ap.add_argument("--block", type=int, default=50, help="sources/targets per request")
    ap.add_argument("--workers", type=int, default=2, help="parallel requests")
    ap.add_argument("--timeout", type=float, default=120, help="seconds per request")
    ap.add_argument("--depart-at", help="optional local departure time, e.g. 2026-10-20T08:00 "
                                        "(only matters if the tiles carry historical speeds)")
    ap.add_argument("--no-snap", action="store_true", help="skip the /locate snapping report")
    ap.add_argument("--out", help="output JSON (default: <stops>.matrices.json)")
    args = ap.parse_args()

    stops = read_stops(args.stops)
    zone = read_zone(args.zone) if args.zone else None
    names = [p for p in args.profiles.split(",") if p]
    unknown = set(names) - set(PROFILES)
    if unknown:
        sys.exit("unknown profiles: %s (known: %s)" % (sorted(unknown), list(PROFILES)))
    status = get(args.url, "/status", 10)
    if "error" in status:
        sys.exit("Valhalla not reachable at %s: %s" % (args.url, status["error"]))
    print("Valhalla %s at %s, %d stops, profiles %s"
          % (status.get("version", "?"), args.url, len(stops), names), flush=True)

    result = {"format": FORMAT, "created": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
              "valhalla": {"url": args.url, "status": status}, "stops_file": args.stops,
              "stops": stops, "units": {"distance": "m", "duration": "s"},
              "zone_file": args.zone, "profiles": {}, "snap": {}}
    t0 = time.perf_counter()
    for name in names:
        print("building %s ..." % name, flush=True)
        prof = build_profile(name, PROFILES[name], stops, args, zone)
        result["profiles"][name] = prof
        print("  %s: %.1f s, %d unreachable pairs" % (name, prof["build_seconds"],
                                                       prof["unreachable_pairs"]), flush=True)
        if not args.no_snap:
            costing = PROFILES[name]["costing"]
            if costing not in result["snap"]:
                result["snap"][costing] = snap(stops, costing, args)
    result["total_seconds"] = round(time.perf_counter() - t0, 2)

    out = args.out or (args.stops.rsplit(".", 1)[0] + ".matrices.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, separators=(",", ":"))
    print("wrote %s in %.1f s" % (out, result["total_seconds"]))


if __name__ == "__main__":
    main()

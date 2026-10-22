# Road engine hand-off: matrices for the Voi instances

For the Valhalla side. The routing algorithm needs, for every vehicle type, a
travel-time and a distance matrix between all stops of a working day. This
folder holds the stop lists and a script that builds those matrices from your
Valhalla instance. Please run it and send the result files back.

## What you get

| File | What it is |
|---|---|
| `build_matrices.py` | The script. Python 3.8+, standard library only, nothing to install |
| `exchange/stops_S00.csv` | 190 stops (2 hubs + scooters, parking violations, rebalancing points) |
| `exchange/stops_M00.csv` | 454 stops, about 206 000 pairs per vehicle type |
| `exchange/stops_L00.csv` | 922 stops, about 850 000 pairs per vehicle type (optional, mainly to measure speed) |
| `exchange/zone_approx.geojson` | Rough rectangle for the environmental zone (miljözon klass 3) in City |

Each CSV has `id, lat, lon, kind, in_zone`; the script only reads the first three.

## How to run

With the Valhalla container running on port 8002:

```bash
python build_matrices.py exchange/stops_S00.csv --url http://localhost:8002 --zone exchange/zone_approx.geojson
python build_matrices.py exchange/stops_M00.csv --url http://localhost:8002 --zone exchange/zone_approx.geojson
python build_matrices.py exchange/stops_L00.csv --url http://localhost:8002 --zone exchange/zone_approx.geojson   # optional
```

Each run writes `stops_XXX.matrices.json` next to the CSV and prints how long
every vehicle type took. Please send back the `.matrices.json` files and the
console output.

It builds three matrix sets with one request per block of stops:

| Profile | Valhalla costing | Used for |
|---|---|---|
| `van` | `auto` | electric vans |
| `van_no_zone` | `auto` + `exclude_polygons` = the zone file | diesel vans, which may not enter the zone |
| `bike` | `bicycle` (City, 15 km/h) | electric cargo bikes |

It also calls `/locate` once per costing to record how far each stop is
snapped to the road (scooters often stand on pavements and squares).

## Settings you may need

- **Request size.** Valhalla's default `service_limits` cap the number of
  source × target pairs per matrix request, so the script asks in blocks of
  50 × 50 stops (`--block 50`). If you raise the limits in `valhalla.json`
  (`service_limits.auto.max_matrix_location_pairs`, same for `bicycle`;
  `max_matrix_distance` should also cover Stockholm, e.g. 100000 m), use a
  larger `--block` for fewer, faster requests. If a request is rejected, the
  script prints Valhalla's error message; lower `--block` and run again.
- **Parallelism.** `--workers 2` sends two requests at a time, matching the
  container's `server_threads=2`. With more server threads, raise both.
- **Departure time.** `--depart-at 2026-10-20T08:00` adds a departure time to
  every request. It only changes anything if the tiles carry historical speed
  data; with plain OpenStreetMap tiles all times are the same.

## Questions for you

1. Which Valhalla version and which OSM extract date are you running? Could
   we pin both (a fixed image tag instead of `latest`)?
2. Do the tiles have historical / time-dependent speeds, or only the default
   speeds per road class? Without them, traffic cannot enter the route
   planning yet.
3. If you set `--depart-at`, does the matrix response actually change between
   08:00 and 12:00?
4. Is `exclude_polygons` supported in your version for matrix requests? The
   `van_no_zone` set should show unreachable pairs for stops inside the zone.
5. Is there an official zone boundary (Stockholm open data) we should use
   instead of the rectangle?
6. Could the service later be reachable from another machine (local network
   or a small cloud server), so the planner can request matrices live?

## Output format (for reference)

```json
{
  "format": "route-opti-matrices/1",
  "valhalla": {"url": "...", "status": {"version": "..."}},
  "stops": [{"id": "HUB_S", "lat": 59.2985, "lon": 18.04}, ...],
  "units": {"distance": "m", "duration": "s"},
  "profiles": {
    "van": {"costing": "auto", "distance_m": [[0, 5291, ...], ...],
            "duration_s": [[0, 672, ...], ...], "unreachable_pairs": 0,
            "build_seconds": 12.3, "requests": 100, "block": 50},
    "van_no_zone": {...}, "bike": {...}
  },
  "snap": {"auto": [{"id": "swap0", "snap_m": 8.2, "side_of_street": "right"}, ...]},
  "total_seconds": 41.0
}
```

Rows and columns follow the CSV order; `null` means Valhalla found no route.

## On our side

`python -m roads.export_stops` regenerates the stop lists from the instance
generator; `roads.load_matrices.apply(problem, path)` reads a result file into
a Voi instance (diesel vans get `van_no_zone`, unreachable pairs become a time
far beyond any shift). `tests/test_roads.py` runs the whole chain against a
mock Valhalla.

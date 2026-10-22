"""Road-engine hand-off: build_matrices.py against a mock Valhalla, then
load_matrices.apply into a Voi instance that the solvers can use."""

import csv
import json
import math
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from rich import pyvrp_rich
from rich.common import WEIGHTED_PRIZE
from rich.validate import validate
from rich.voi import build, in_zone
from roads import build_matrices
from roads.load_matrices import UNREACHABLE, apply, summary


def _inside(lon, lat, ring):
    xs, ys = [p[0] for p in ring], [p[1] for p in ring]
    return min(xs) <= lon <= max(xs) and min(ys) <= lat <= max(ys)


class MockValhalla(BaseHTTPRequestHandler):
    max_pairs = 0

    def log_message(self, *a):
        pass

    def _send(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send({"version": "mock-3.5"})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/locate":
            self._send([{"edges": [{"correlated_lat": l["lat"] + 0.0001, "correlated_lon": l["lon"],
                                    "side_of_street": "right"}]} for l in req["locations"]])
            return
        src, tgt = req["sources"], req["targets"]
        MockValhalla.max_pairs = max(MockValhalla.max_pairs, len(src) * len(tgt))
        zone = req.get("exclude_polygons")
        speed = 4.0 if req["costing"] == "bicycle" else 7.0
        rows = []
        for i, a in enumerate(src):
            row = []
            for j, b in enumerate(tgt):
                blocked = zone and any(_inside(p["lon"], p["lat"], r) for p in (a, b) for r in zone)
                d = build_matrices.haversine_m(a["lat"], a["lon"], b["lat"], b["lon"]) * 1.4
                row.append({"from_index": i, "to_index": j,
                            "distance": None if blocked else d / 1000,
                            "time": None if blocked else d / speed + 30})
            rows.append(row)
        self._send({"sources_to_targets": rows, "units": "kilometers"})


@pytest.fixture(scope="module")
def mock_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockValhalla)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(scope="module")
def matrices(mock_url, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("roads")
    problem = build("S", 0)
    stops = tmp / "stops_S00.csv"
    with open(stops, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "lat", "lon"])
        for loc in problem.locations:
            w.writerow([loc.id, loc.y, loc.x])
    zone = tmp / "zone.geojson"
    from rich.voi import ZONE
    lat0, lat1, lon0, lon1 = ZONE
    zone.write_text(json.dumps({"type": "Polygon", "coordinates": [[[lon0, lat0], [lon1, lat0],
                                                                    [lon1, lat1], [lon0, lat1],
                                                                    [lon0, lat0]]]}))
    old = sys.argv
    sys.argv = ["build_matrices.py", str(stops), "--url", mock_url, "--zone", str(zone),
                "--block", "40", "--workers", "3"]
    try:
        build_matrices.main()
    finally:
        sys.argv = old
    return problem, tmp / "stops_S00.matrices.json"


def test_blocks_are_stitched(matrices):
    problem, path = matrices
    data = json.loads(path.read_text())
    n = len(problem.locations)
    assert MockValhalla.max_pairs <= 40 * 40
    for p in data["profiles"].values():
        assert len(p["duration_s"]) == n and all(len(r) == n for r in p["duration_s"])
        assert all(p["duration_s"][i][i] == 0 for i in range(n))
    # stitched value equals a direct computation for an arbitrary pair
    a, b = problem.locations[3], problem.locations[150]
    d = build_matrices.haversine_m(a.y, a.x, b.y, b.x) * 1.4
    assert data["profiles"]["van"]["distance_m"][3][150] == round(d)


def test_zone_excluded_only_for_diesel(matrices):
    problem, path = matrices
    data = json.loads(path.read_text())
    inside = [k for k, loc in enumerate(problem.locations) if in_zone((loc.y, loc.x))]
    assert inside
    k = inside[0]
    assert data["profiles"]["van_no_zone"]["duration_s"][0][k] is None
    assert data["profiles"]["van"]["duration_s"][0][k] is not None
    assert data["profiles"]["van_no_zone"]["unreachable_pairs"] > 0


def test_apply_and_solve(matrices):
    problem, path = matrices
    real = apply(problem, path)
    prof = {v.id: v.profile for v in real.vehicles}
    assert prof["dvan1"] == "van_no_zone" and prof["evan0"] == "van" and prof["bike2"] == "bike"
    k = next(i for i, loc in enumerate(real.locations) if in_zone((loc.y, loc.x)))
    assert real.profiles["van_no_zone"].duration_matrix[0][k] == UNREACHABLE
    sol = pyvrp_rich.solve(real, time_limit_s=2, prizes=WEIGHTED_PRIZE)
    rep = validate(real, sol)
    assert rep.feasible, rep.violations
    s = summary(path)
    assert s["van"]["requests"] == math.ceil(len(problem.locations) / 40) ** 2
    assert s["snap_auto"]["median_m"] == pytest.approx(11.1, abs=0.5)

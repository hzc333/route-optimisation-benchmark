"""Convert VRPLIB instances in data/raw/ to the shared schema (plan §5, §6).

Families and rounding conventions (must match the BKS convention):

* solomon, hg1000 (VRPTW): DIMACS - distance/duration = floor(10 * euclid);
  time windows and service times x10. Fleet = VEHICLES header. Depot time
  window -> vehicle shift.
* x (CVRP): TSPLIB nint - int(euclid + 0.5). The file has no fleet size; we
  use max(ceil(1.5 k), k + 3) where k (from the name) is the minimum number of
  routes. Both solvers get the same fleet; the rule never looks at the BKS.

All costs are therefore integers in "scaled units"; ``meta.distance_scale``
converts back (BKS in data/bks/bks.csv are stored scaled as well).

Usage:
    python -m data.convert solomon/R101 x/X-n101-k25 ...
    python -m data.convert --all solomon
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from pathlib import Path

import numpy as np

from schema.models import Job, Location, Problem, Vehicle

DATA = Path(__file__).resolve().parent
RAW, CONVERTED, BKS_CSV = DATA / "raw", DATA / "converted", DATA / "bks" / "bks.csv"

FAMILIES = {
    "solomon": {"kind": "vrptw", "scale": 10},
    "hg1000": {"kind": "vrptw", "scale": 10},
    "x": {"kind": "cvrp", "scale": 1},
}


def parse_vrplib(path: Path) -> tuple[dict[str, str], dict[str, list[list[str]]]]:
    header: dict[str, str] = {}
    sections: dict[str, list[list[str]]] = {}
    current = None
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line == "EOF":
            continue
        if line.endswith("_SECTION"):
            current = line
            sections[current] = []
        elif ":" in line and current is None:
            key, _, value = line.partition(":")
            header[key.strip()] = value.strip().strip('"')
        elif current:
            sections[current].append(line.split())
    return header, sections


def parse_solution(path: Path) -> tuple[list[list[int]], float]:
    """Routes as lists of 1-based customer numbers (VRPLIB .sol convention)."""
    routes, cost = [], None
    for line in path.read_text().splitlines():
        if line.startswith("Route"):
            routes.append([int(t) for t in line.split(":", 1)[1].split()])
        elif line.startswith("Cost"):
            cost = float(line.split()[1])
    return routes, cost


def _euclid(coords: np.ndarray) -> np.ndarray:
    diff = coords[:, None, :] - coords[None, :, :]
    return np.sqrt((diff**2).sum(-1))


def fleet_size_x(name: str) -> int:
    k = int(re.search(r"-k(\d+)", name).group(1))
    return max(math.ceil(1.5 * k), k + 3)


def convert(family: str, name: str) -> Problem:
    spec = FAMILIES[family]
    header, sec = parse_vrplib(RAW / family / f"{name}.vrp")
    n = int(header["DIMENSION"])
    ids = [int(r[0]) for r in sec["NODE_COORD_SECTION"]]
    coords = np.array([[float(r[1]), float(r[2])] for r in sec["NODE_COORD_SECTION"]])
    depot_id = int(sec["DEPOT_SECTION"][0][0])
    if ids != list(range(1, n + 1)) or depot_id != 1:
        raise ValueError(f"{name}: expected nodes 1..n with depot 1")
    demand = [int(r[1]) for r in sec["DEMAND_SECTION"]]
    capacity = int(header["CAPACITY"])
    scale = spec["scale"]

    euclid = _euclid(coords)
    if spec["kind"] == "vrptw":
        matrix = np.floor(euclid * scale).astype(np.int64)          # DIMACS
        tws = [(int(r[1]) * scale, int(r[2]) * scale) for r in sec["TIME_WINDOW_SECTION"]]
        service = int(header.get("SERVICE_TIME", 0)) * scale
        num_vehicles = int(header["VEHICLES"])
        shift = tws[0]
    else:
        matrix = np.floor(euclid + 0.5).astype(np.int64)            # TSPLIB nint
        tws, service, shift = None, 0, None
        num_vehicles = fleet_size_x(name)

    m = matrix.tolist()
    vehicle_kw = {"shift": shift} if shift else {}
    return Problem(
        name=name,
        meta={"family": family, "source": f"PyVRP/Instances {family}/{name}.vrp",
              "distance_scale": scale, "rounding": "dimacs" if scale == 10 else "nint"},
        locations=[Location(id=str(i), x=float(x), y=float(y)) for i, (x, y) in zip(ids, coords)],
        depot=0,
        vehicles=[Vehicle(id=f"v{k}", capacity=capacity, **vehicle_kw) for k in range(num_vehicles)],
        jobs=[
            Job(id=str(i), location=i, demand=demand[i], service=service,
                time_window=tws[i] if tws else None)
            for i in range(1, n)
        ],
        distance_matrix=m,
        duration_matrix=m,
    )


def instance_names(family: str) -> list[str]:
    return sorted(p.stem for p in (RAW / family).glob("*.vrp"))


def converted_path(family: str, name: str) -> Path:
    return CONVERTED / family / f"{name}.json"


def write_converted(family: str, name: str) -> Path:
    path = converted_path(family, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(convert(family, name).model_dump_json())
    return path


def write_bks_table() -> None:
    rows = []
    for family, spec in FAMILIES.items():
        for name in instance_names(family):
            sol = RAW / family / f"{name}.sol"
            if not sol.exists():
                continue
            routes, cost = parse_solution(sol)
            rows.append({
                "family": family, "instance": name,
                "bks_scaled": round(cost * spec["scale"]), "bks_routes": len(routes),
                "distance_scale": spec["scale"],
                "rounding": "dimacs" if spec["scale"] == 10 else "nint",
                "source": "CVRPLIB via PyVRP/Instances",
            })
    BKS_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(BKS_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def load_bks() -> dict[str, dict]:
    with open(BKS_CSV, encoding="utf-8") as fh:
        return {r["instance"]: r for r in csv.DictReader(fh)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("refs", nargs="*", help="family/name, e.g. solomon/R101")
    ap.add_argument("--all", nargs="*", default=[], metavar="FAMILY")
    args = ap.parse_args()
    refs = [r.split("/", 1) for r in args.refs]
    refs += [(f, n) for f in args.all for n in instance_names(f)]
    for family, name in refs:
        print(write_converted(family, name).relative_to(DATA.parent))
    write_bks_table()
    print(f"wrote {BKS_CSV.relative_to(DATA.parent)}")

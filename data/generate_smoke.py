"""Generate the deterministic smoke-test instances (plan §6 stage 0).

* smoke_cvrp_20   20 clients, capacity only.
* smoke_vrptw_25  25 clients, hard time windows + service times.

Coordinates are drawn on a 100x100 grid; distances are Euclidean x10,
rounded to int, and duration == distance (Solomon convention, scaled).
Both instances are feasible by construction: every client fits on its own
route, and the fleet is large enough for singleton routes if needed.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from schema.models import Job, Location, Problem, Vehicle

OUT = Path(__file__).resolve().parent / "converted" / "smoke"
SCALE = 10


def _matrix(coords: np.ndarray) -> list[list[int]]:
    diff = coords[:, None, :] - coords[None, :, :]
    return np.rint(np.hypot(diff[..., 0], diff[..., 1]) * SCALE).astype(int).tolist()


def _locations(coords: np.ndarray) -> list[Location]:
    return [
        Location(id="depot" if i == 0 else f"L{i}", x=float(x), y=float(y))
        for i, (x, y) in enumerate(coords)
    ]


def smoke_cvrp(n: int = 20, capacity: int = 30, seed: int = 20260929) -> Problem:
    rng = np.random.default_rng(seed)
    coords = np.vstack([[50, 50], rng.integers(0, 101, size=(n, 2))])
    demands = rng.integers(1, 11, size=n)
    num_vehicles = math.ceil(demands.sum() / capacity) + 1
    m = _matrix(coords)
    return Problem(
        name=f"smoke_cvrp_{n}",
        meta={"source": "generate_smoke.py", "seed": seed, "distance_scale": SCALE},
        locations=_locations(coords),
        depot=0,
        vehicles=[Vehicle(id=f"v{k}", capacity=capacity) for k in range(num_vehicles)],
        jobs=[Job(id=f"c{i}", location=i, demand=int(demands[i - 1])) for i in range(1, n + 1)],
        distance_matrix=m,
        duration_matrix=m,
    )


def smoke_vrptw(
    n: int = 25, capacity: int = 50, horizon: int = 10_000,
    service: int = 100, seed: int = 20260930,
) -> Problem:
    rng = np.random.default_rng(seed)
    coords = np.vstack([[50, 50], rng.integers(0, 101, size=(n, 2))])
    demands = rng.integers(1, 11, size=n)
    m = _matrix(coords)

    jobs = []
    for i in range(1, n + 1):
        earliest = m[0][i]                         # direct from depot at t=0
        latest = horizon - service - m[i][0]       # still back by the horizon
        centre = int(rng.integers(earliest, latest + 1))
        half = int(rng.integers(150, 601))
        tw = (max(0, centre - half), min(latest, centre + half))
        jobs.append(Job(id=f"c{i}", location=i, demand=int(demands[i - 1]),
                        service=service, time_window=tw))

    return Problem(
        name=f"smoke_vrptw_{n}",
        meta={"source": "generate_smoke.py", "seed": seed, "distance_scale": SCALE},
        locations=_locations(coords),
        depot=0,
        # Solomon convention: fleet size == number of customers.
        vehicles=[Vehicle(id=f"v{k}", capacity=capacity, shift=(0, horizon)) for k in range(n)],
        jobs=jobs,
        distance_matrix=m,
        duration_matrix=m,
    )


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for problem in (smoke_cvrp(), smoke_vrptw()):
        path = OUT / f"{problem.name}.json"
        path.write_text(problem.model_dump_json(indent=1), encoding="utf-8")
        print(f"wrote {path.relative_to(OUT.parents[1])}")

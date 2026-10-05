"""Synthetic city instances for the traffic experiment.

20 x 20 km city, centre (10, 10) km, depot on the west side (3, 12) km.
100 customers: 60 % in four clusters (one in the congested centre), 40 %
scattered. Arc length = 1.3 x Euclidean (road detour factor). Service 6 min,
shift 07:00-16:00 so routes of 15-20 stops run through the morning peak;
60 % of the customers have a 1-hour window, which is always reachable from
the depot even at peak, so an instance is never infeasible by construction -
only plans can be. Tight windows and few vehicles make traffic matter.

    python -m traffic.instances      # writes data/converted/traffic/*.json
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from schema.models import Job, Location, Problem, Vehicle

from .model import A, B, TDModel

OUT = Path(__file__).resolve().parents[1] / "data" / "converted" / "traffic"
N_INSTANCES = 10
N_CUSTOMERS = 100
CENTRE_KM = np.array([10.0, 10.0])
DEPOT_KM = np.array([3.0, 12.0])
SIGMA_KM = 4.0
DETOUR = 1.3
SERVICE_S = 360
SHIFT = (7 * 3600, 16 * 3600)
TW_WIDTH_S = 3600
TW_SHARE = 0.6
CAPACITY = 100
# Congestion levels: slowdown at full peak = A + B * exposure.
LEVELS = {"T": (A, B),          # moderate: centre ~2.5x slower at peak
          "H": (0.30, 0.60)}    # heavy:    centre ~4.7x slower at peak


def _coords(rng: np.random.Generator) -> np.ndarray:
    centres = np.array([CENTRE_KM, [15.0, 5.0], [6.0, 4.0], [14.0, 16.0]])
    n_cl = int(N_CUSTOMERS * 0.6)
    which = rng.integers(0, len(centres), size=n_cl)
    clustered = centres[which] + rng.normal(0, 1.2, size=(n_cl, 2))
    scattered = rng.uniform(0, 20, size=(N_CUSTOMERS - n_cl, 2))
    return np.clip(np.vstack([clustered, scattered]), 0, 20)


def build(seed: int, level: str = "T") -> tuple[Problem, TDModel]:
    """Same geography, demands and window draws for a seed at every level; only
    traffic differs (windows are clamped to stay reachable at that level's
    worst traffic)."""
    rng = np.random.default_rng(30_000 + seed)
    pts = np.vstack([DEPOT_KM, _coords(rng)])                      # km
    diff = pts[:, None, :] - pts[None, :, :]
    length = np.hypot(diff[..., 0], diff[..., 1]) * 1000 * DETOUR  # m
    mid = (pts[:, None, :] + pts[None, :, :]) / 2
    dist_c = np.hypot(mid[..., 0] - CENTRE_KM[0], mid[..., 1] - CENTRE_KM[1])
    congestion = np.exp(-dist_c ** 2 / (2 * SIGMA_KM ** 2))
    a, b = LEVELS[level]
    td = TDModel(np.floor(length + 0.5), congestion, a=a, b=b)

    # Worst-case (slowest) leg times bound the windows so every job is
    # reachable on its own route whatever the traffic.
    worst = np.max([td.matrix_at(k * td.bucket_s)
                    for k in range(SHIFT[0] // td.bucket_s, SHIFT[1] // td.bucket_s)], axis=0)
    demand = rng.integers(1, 11, size=N_CUSTOMERS)
    jobs = []
    for i in range(1, N_CUSTOMERS + 1):
        tw = None
        if rng.random() < TW_SHARE:
            earliest = SHIFT[0] + worst[0, i]
            latest = SHIFT[1] - SERVICE_S - worst[i, 0]
            start = int(rng.integers(SHIFT[0], SHIFT[1] - TW_WIDTH_S))
            # Window end in [earliest arrival at worst traffic, latest start
            # that still returns in time]: reachable alone in any traffic.
            end = int(min(max(start + TW_WIDTH_S, earliest), latest))
            tw = (end - TW_WIDTH_S, end)
        jobs.append(Job(id=f"c{i}", location=i, demand=int(demand[i - 1]),
                        service=SERVICE_S, time_window=tw))
    n_veh = math.ceil(demand.sum() / CAPACITY) + 2
    ff = td.freeflow().tolist()
    problem = Problem(
        name=f"{level}{seed:02d}",
        meta={"family": "traffic", "source": "traffic/instances.py", "seed": seed, "level": level,
              "note": "duration_matrix = free-flow; strategies replace it"},
        locations=[Location(id="depot" if i == 0 else f"L{i}", x=float(x), y=float(y))
                   for i, (x, y) in enumerate(pts)],
        depot=0,
        vehicles=[Vehicle(id=f"v{k}", capacity=CAPACITY, shift=SHIFT) for k in range(n_veh)],
        jobs=jobs,
        distance_matrix=td.length_m.astype(int).tolist(),
        duration_matrix=ff,
    )
    return problem, td


def load(name: str) -> tuple[Problem, TDModel]:
    p = Problem.model_validate_json((OUT / f"{name}.json").read_text(encoding="utf-8"))
    td = TDModel.from_json(json.loads((OUT / f"{name}.td.json").read_text(encoding="utf-8")))
    return p, td


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for level, seed in [(lv, sd) for lv in LEVELS for sd in range(N_INSTANCES)]:
        problem, td = build(seed, level)
        (OUT / f"{problem.name}.json").write_text(problem.model_dump_json(), encoding="utf-8")
        (OUT / f"{problem.name}.td.json").write_text(json.dumps(td.to_json()), encoding="utf-8")
        print(f"wrote {problem.name}: {len(problem.jobs)} jobs, {len(problem.vehicles)} vehicles, "
              f"{sum(j.time_window is not None for j in problem.jobs)} windows")

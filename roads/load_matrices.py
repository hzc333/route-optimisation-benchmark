"""Read a Valhalla matrix file (roads/build_matrices.py) into a RichProblem.

    from roads.load_matrices import apply
    problem = apply(rich.voi.build("M", 0), "roads/exchange/results/stops_M00.matrices.json")

The file's stops must be the problem's locations (same ids; order is matched
by id). Its profiles replace the problem's: ``van`` for vans, ``bike`` for
cargo bikes, and - when present - ``van_no_zone`` for vans without the
zero-emission skill, so diesel vans really drive around the environmental
zone. Pairs Valhalla could not route become UNREACHABLE (seconds and metres),
far beyond any shift, so no solver will use them; stops inside the zone are
unreachable for the van_no_zone profile and the skill rule still applies.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from rich.model import Profile, RichProblem

FORMAT = "route-opti-matrices/1"
UNREACHABLE = 10**6
# rich.voi vehicle profile -> matrix profile
PROFILE_FOR = {"van": "van", "bike": "bike"}


def load(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("format") != FORMAT:
        raise ValueError(f"{path}: not a {FORMAT} file")
    return data


def _matrix(rows, order) -> list[list[int]]:
    m = np.array([[UNREACHABLE if v is None else v for v in row] for row in rows], dtype=np.int64)
    m = m[np.ix_(order, order)]
    np.fill_diagonal(m, 0)
    return m.tolist()


def apply(problem: RichProblem, path: str | Path) -> RichProblem:
    data = load(path)
    ids = [s["id"] for s in data["stops"]]
    pos = {sid: k for k, sid in enumerate(ids)}
    missing = [loc.id for loc in problem.locations if loc.id not in pos]
    if missing:
        raise ValueError(f"{len(missing)} problem locations are not in {path}, e.g. {missing[:3]}")
    order = [pos[loc.id] for loc in problem.locations]
    profiles = {name: Profile(distance_matrix=_matrix(p["distance_m"], order),
                              duration_matrix=_matrix(p["duration_s"], order))
                for name, p in data["profiles"].items()}
    vehicles = []
    for v in problem.vehicles:
        target = PROFILE_FOR.get(v.profile, v.profile)
        if v.profile == "van" and not v.skills and "van_no_zone" in profiles:
            target = "van_no_zone"
        if target not in profiles:
            raise ValueError(f"vehicle {v.id}: profile {target} not in {path}")
        vehicles.append(v.model_copy(update={"profile": target}))
    meta = dict(problem.meta, matrices=str(path),
                valhalla_version=data["valhalla"].get("status", {}).get("version"))
    return problem.model_copy(update={"profiles": profiles, "vehicles": vehicles, "meta": meta})


def summary(path: str | Path) -> dict:
    """Build time, unreachable pairs and snapping distances per profile."""
    data = load(path)
    out = {"stops": len(data["stops"]), "total_seconds": data.get("total_seconds")}
    for name, p in data["profiles"].items():
        out[name] = {"build_seconds": p["build_seconds"], "unreachable_pairs": p["unreachable_pairs"],
                     "requests": p["requests"]}
    for costing, rows in (data.get("snap") or {}).items():
        d = [r["snap_m"] for r in rows or [] if r.get("snap_m") is not None]
        if d:
            out[f"snap_{costing}"] = {"median_m": float(np.median(d)), "p95_m": float(np.percentile(d, 95)),
                                      "over_50m": int(sum(x > 50 for x in d))}
    return out

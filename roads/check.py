"""Check matrix files returned by the road engine before using them.

    python -m roads.check                         # every file in roads/exchange/results/
    python -m roads.check path/to/stops_M00.matrices.json

Per file: Valhalla version, build time per vehicle type, unreachable pairs,
how far stops were snapped to the road (stops snapped > 50 m are listed: they
probably lie in water, a park or a building), and how the real road network
compares with the straight-line model the Voi instances used so far
(distance and time ratios, average driving speed).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from rich.voi import build
from roads.load_matrices import load

RESULTS = Path(__file__).resolve().parent / "exchange" / "results"
SYNTHETIC = {"van": "van", "van_no_zone": "van", "bike": "bike"}


def check(path: Path) -> None:
    data = load(path)
    ids = [s["id"] for s in data["stops"]]
    print(f"\n== {path.name}: {len(ids)} stops, Valhalla "
          f"{data['valhalla'].get('status', {}).get('version', '?')}, "
          f"built {data['created']}, total {data.get('total_seconds')} s")

    instance = path.name.removeprefix("stops_").split(".")[0]
    synthetic = None
    try:
        p = build(instance[0], int(instance[1:]))
        if [loc.id for loc in p.locations] == ids:
            synthetic = p
    except (KeyError, ValueError):
        pass

    for name, prof in data["profiles"].items():
        dur = np.array([[np.nan if v is None else v for v in r] for r in prof["duration_s"]], float)
        dist = np.array([[np.nan if v is None else v for v in r] for r in prof["distance_m"]], float)
        off = ~np.eye(len(ids), dtype=bool)
        ok = off & ~np.isnan(dur) & (dur > 0)
        speed = np.nanmedian(dist[ok] / dur[ok]) * 3.6
        line = (f"  {name:12s} {prof['costing']:8s} {prof['build_seconds']:7.1f} s "
                f"({prof['requests']} requests)  unreachable {prof['unreachable_pairs']:6d}  "
                f"median speed {speed:4.1f} km/h")
        if synthetic is not None:
            sp = synthetic.profiles[SYNTHETIC.get(name, name)]
            sd, st = np.array(sp.distance_matrix, float), np.array(sp.duration_matrix, float)
            good = ok & (sd > 300)
            rd, rt = dist[good] / sd[good], dur[good] / st[good]
            line += (f"\n               real / straight-line model: distance x{np.median(rd):.2f} "
                     f"(p10 {np.percentile(rd, 10):.2f}, p90 {np.percentile(rd, 90):.2f}), "
                     f"time x{np.median(rt):.2f} (p10 {np.percentile(rt, 10):.2f}, "
                     f"p90 {np.percentile(rt, 90):.2f})")
        print(line)
        if prof["unreachable_pairs"]:
            rows = np.isnan(dur).sum(axis=1)
            worst = [f"{ids[k]} ({rows[k]})" for k in np.argsort(-rows)[:5] if rows[k]]
            print(f"               most unreachable from: {', '.join(worst)}")

    for costing, rows in (data.get("snap") or {}).items():
        if not rows:
            continue
        d = np.array([r.get("snap_m") if r.get("snap_m") is not None else np.nan for r in rows])
        far = [f"{r['id']} {r['snap_m']:.0f} m" for r in sorted(
            (r for r in rows if (r.get("snap_m") or 0) > 50), key=lambda r: -r["snap_m"])]
        print(f"  snap ({costing}): median {np.nanmedian(d):.0f} m, p95 {np.nanpercentile(d, 95):.0f} m, "
              f"{len(far)} stops over 50 m{': ' + ', '.join(far[:8]) if far else ''}"
              f"{' ...' if len(far) > 8 else ''}")


def main() -> None:
    paths = [Path(a) for a in sys.argv[1:]] or sorted(RESULTS.glob("*.matrices.json"))
    if not paths:
        sys.exit(f"no *.matrices.json files given or found in {RESULTS}")
    for p in paths:
        check(p)


if __name__ == "__main__":
    main()

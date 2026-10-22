"""Stop lists for the road-engine hand-off (roads/README.md).

    python -m roads.export_stops            # S00, M00, L00 -> roads/exchange/

Writes stops_<instance>.csv (id, lat, lon, kind, in_zone) in the instance's
location order, and zone_approx.geojson: the approximate environmental-zone
rectangle used by the Voi generator (replace it with the official boundary
from Stockholm's open data when available).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from rich.voi import ZONE, build, in_zone

OUT = Path(__file__).resolve().parent / "exchange"
INSTANCES = [("S", 0), ("M", 0), ("L", 0)]


def kind_of(name: str) -> str:
    if name.startswith("HUB"):
        return "hub"
    if name.startswith(("viol", "reb")):
        return ("violation" if name.startswith("viol") else "rebalance") + \
            ("_pickup" if name.endswith("_from") else "_dropoff")
    if name.startswith("zone"):
        return "swap_group"
    return "swap"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for size, seed in INSTANCES:
        p = build(size, seed)
        path = OUT / f"stops_{size}{seed:02d}.csv"
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow(["id", "lat", "lon", "kind", "in_zone"])
            for loc in p.locations:
                w.writerow([loc.id, f"{loc.y:.6f}", f"{loc.x:.6f}", kind_of(loc.id),
                            int(in_zone((loc.y, loc.x)))])
        print(f"wrote {path} ({len(p.locations)} stops)")
    lat0, lat1, lon0, lon1 = ZONE
    ring = [[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]
    zone = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {"name": "approximate miljözon klass 3 (City)",
                                          "note": "rectangle used by rich/voi.py; replace with the official boundary"},
        "geometry": {"type": "Polygon", "coordinates": [ring]}}]}
    (OUT / "zone_approx.geojson").write_text(json.dumps(zone, ensure_ascii=False, indent=1),
                                             encoding="utf-8")
    print(f"wrote {OUT / 'zone_approx.geojson'}")


if __name__ == "__main__":
    main()

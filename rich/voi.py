"""Synthetic Voi-style battery-swap day in Stockholm (rich instance, plan §8 tier 5).

Geography: real coordinates of central Stockholm. Scooters cluster around
public-transport hotspots (T-Centralen, Slussen, Odenplan, ...) or are spread
over land boxes (Norrmalm/Vasastan/Östermalm, Södermalm, Kungsholmen, the
southern suburbs). Two synthetic hubs (north and south). Road distance =
straight line x detour factor; water and the real street network are ignored
until the road-engine track provides matrices (Valhalla).

Work (morning shift 06:00-14:00, 30-min break starting 10:00-12:00):

* battery swaps (optional): one charged battery out, one depleted back.
  Priority class from battery level and hotspot demand; value = rides lost
  if left (1-4). CRITICAL hotspot swaps must be done before the 08:30 peak
  (hard window); HIGH hotspot swaps ideally before 09:00 (soft deadline);
* "swap any 3 of these 8" zones (groups, k of n);
* parking violations (required shipments): pick the scooter up before a
  deadline and park it legally a few hundred metres away;
* rebalancing (optional shipments): move a scooter from an oversupplied area
  to a demand hotspot before 09:00.

Fleet: electric vans, diesel vans and electric cargo bikes. Stops inside the
(approximate) environmental zone class 3 in City need a zero-emission vehicle
(skill). Bikes have their own profile (shorter, slower-but-no-parking legs) and
cannot carry scooters (capacity 0). Load dims: charged batteries, depleted
batteries, scooters. Vehicles reload at either hub.

Costs in points of 0.001 SEK: driver 300 SEK/h = 83 per second; van 2-4 per
metre; fixed day cost per vehicle. Soft lateness 20 per second.
"""

from __future__ import annotations

import math

import numpy as np

from schema.models import Location, PriorityClass

from .model import Break, Group, Hub, Job, Profile, RichProblem, Shipment, Step, Vehicle

LAT0, LON0 = 59.325, 18.05
KM_PER_DEG_LAT = 110.57
KM_PER_DEG_LON = 111.32 * math.cos(math.radians(LAT0))

HOTSPOTS = {  # name: (lat, lon)
    "T-Centralen": (59.3310, 18.0590), "Hötorget": (59.3355, 18.0630),
    "Slussen": (59.3195, 18.0720), "Odenplan": (59.3429, 18.0496),
    "Fridhemsplan": (59.3320, 18.0290), "Östermalmstorg": (59.3350, 18.0770),
    "Medborgarplatsen": (59.3143, 18.0735), "KTH": (59.3456, 18.0715),
    "St Eriksplan": (59.3395, 18.0370), "Gullmarsplan": (59.2990, 18.0810),
    "Liljeholmen": (59.3100, 18.0230), "Hammarby sjöstad": (59.3035, 18.1000),
}
DEMAND = ["T-Centralen", "Hötorget", "Slussen", "Odenplan", "Östermalmstorg"]
OVERSUPPLY = ["Hammarby sjöstad", "Liljeholmen", "Gullmarsplan", "Fridhemsplan"]
LAND = [  # (lat_min, lat_max, lon_min, lon_max, weight)
    (59.333, 59.350, 18.030, 18.095, 0.40), (59.309, 59.321, 18.030, 18.100, 0.30),
    (59.327, 59.338, 17.995, 18.050, 0.15), (59.295, 59.308, 18.010, 18.105, 0.15),
]
ZONE = (59.3305, 59.3375, 18.0560, 18.0760)   # approx. miljözon klass 3, City
HUBS = {"HUB_S": (59.2985, 18.0400), "HUB_N": (59.3490, 18.0320)}
CENTRE = (59.3330, 18.0650)
HOT = 0.75   # hotspot demand above which a spot counts as busy

SHIFT = (6 * 3600, 14 * 3600)
REST = Break(earliest=10 * 3600, latest=12 * 3600, duration=1800)
PEAK_END = 8 * 3600 + 1800
SOFT_DUE = 9 * 3600
HUB_SERVICE = 600
SWAP_SERVICE = 150
ZERO_EMISSION = "zero_emission"

# Vehicle archetypes: profile, capacity [charged, depleted, scooters],
# max reloads, fixed cost, cost per metre, skills.
FLEET_TYPES = {
    "evan": ("van", [30, 30, 3], 3, 250_000, 2, [ZERO_EMISSION]),
    "dvan": ("van", [40, 40, 5], 3, 250_000, 4, []),
    "bike": ("bike", [10, 10, 0], 6, 150_000, 1, [ZERO_EMISSION]),
}
DURATION_COST = 83
SOFT_LATE_COST = 20

SIZES = {  # swaps, (groups, n, k), violations, rebalancing, fleet
    "S": dict(swaps=150, groups=(2, 8, 3), violations=5, rebalance=6,
              fleet={"evan": 1, "dvan": 1, "bike": 1}),
    "M": dict(swaps=380, groups=(3, 8, 3), violations=10, rebalance=14,
              fleet={"evan": 2, "dvan": 1, "bike": 2}),
    "L": dict(swaps=780, groups=(5, 8, 3), violations=20, rebalance=30,
              fleet={"evan": 4, "dvan": 2, "bike": 4}),
}


def to_km(lat, lon):
    return np.stack([(np.asarray(lon) - LON0) * KM_PER_DEG_LON,
                     (np.asarray(lat) - LAT0) * KM_PER_DEG_LAT], axis=-1)


def _near(rng, latlon, sigma_m, size):
    lat, lon = latlon
    return np.stack([lat + rng.normal(0, sigma_m / 1000 / KM_PER_DEG_LAT, size),
                     lon + rng.normal(0, sigma_m / 1000 / KM_PER_DEG_LON, size)], axis=-1)


def _scattered(rng, size):
    w = np.array([b[4] for b in LAND])
    box = rng.choice(len(LAND), size=size, p=w / w.sum())
    return np.array([[rng.uniform(LAND[b][0], LAND[b][1]), rng.uniform(LAND[b][2], LAND[b][3])]
                     for b in box]).reshape(size, 2)


def in_zone(latlon) -> bool:
    lat, lon = latlon
    return ZONE[0] <= lat <= ZONE[1] and ZONE[2] <= lon <= ZONE[3]


def zone_skill_of(latlon) -> list[str]:
    return [ZERO_EMISSION] if in_zone(latlon) else []


def hotspot_demand(latlon) -> float:
    """1 at a hotspot, decaying with distance (700 m scale)."""
    p = to_km(*latlon)
    d = min(np.hypot(*(p - to_km(*h))) for h in HOTSPOTS.values())
    return float(math.exp(-(d / 0.7) ** 2))


def matrices(latlon: np.ndarray) -> dict[str, Profile]:
    km = to_km(latlon[:, 0], latlon[:, 1])
    diff = km[:, None, :] - km[None, :, :]
    straight = np.hypot(diff[..., 0], diff[..., 1]) * 1000          # m
    mid = (km[:, None, :] + km[None, :, :]) / 2
    centre = to_km(*CENTRE)
    central = np.hypot(mid[..., 0] - centre[0], mid[..., 1] - centre[1]) < 1.8
    same = straight < 1
    out = {}
    # Van: road detour 1.35; 16 km/h in the centre, 26 km/h outside; one
    # minute per stop to find a place to stop.
    van_d = np.floor(straight * 1.35 + 0.5)
    van_t = 60 + van_d / np.where(central, 16 / 3.6, 26 / 3.6)
    # Cargo bike: bike lanes and shortcuts (detour 1.2), 15 km/h, parks anywhere.
    bike_d = np.floor(straight * 1.2 + 0.5)
    bike_t = 15 + bike_d / (15 / 3.6)
    for name, d, t in (("van", van_d, van_t), ("bike", bike_d, bike_t)):
        d = np.where(same, 0, d).astype(int)
        t = np.where(same, 0, np.floor(t + 0.5)).astype(int)
        out[name] = Profile(distance_matrix=d.tolist(), duration_matrix=t.tolist())
    return out


def _classify(rng, demand: float) -> tuple[PriorityClass, int]:
    """Class from battery level and demand at the spot (``hot`` = busiest
    third); value = rides lost if the scooter stays flat."""
    battery, hot = rng.uniform(0, 0.25), demand > HOT
    if battery < 0.05 and hot:
        cls = PriorityClass.CRITICAL
    elif battery < 0.05 or (battery < 0.12 and hot):
        cls = PriorityClass.HIGH
    elif battery < 0.15 or demand > 0.5:
        cls = PriorityClass.NORMAL
    else:
        cls = PriorityClass.LOW
    return cls, 1 + int(round(3 * demand))


def build(size: str = "S", seed: int = 0) -> RichProblem:
    spec = SIZES[size]
    rng = np.random.default_rng(50_000 + 97 * seed + {"S": 0, "M": 7, "L": 13}[size])
    pts: list[tuple[float, float]] = [HUBS["HUB_S"], HUBS["HUB_N"]]
    names = ["HUB_S", "HUB_N"]

    def add(latlon, name) -> int:
        pts.append((float(latlon[0]), float(latlon[1])))
        names.append(name)
        return len(pts) - 1

    def zone_skill(*locs) -> list[str]:
        return [ZERO_EMISSION] if any(in_zone(pts[i]) for i in locs) else []

    jobs: list[Job] = []
    hot = list(HOTSPOTS.values())
    n_clustered = int(spec["swaps"] * 0.65)
    swap_pts = np.vstack([
        np.vstack([_near(rng, hot[h], 400, 1) for h in rng.integers(0, len(hot), n_clustered)]),
        _scattered(rng, spec["swaps"] - n_clustered)])
    for k, p in enumerate(swap_pts):
        loc = add(p, f"swap{k}")
        demand = hotspot_demand(p)
        cls, value = _classify(rng, demand)
        tw = soft = None
        if cls is PriorityClass.CRITICAL and rng.random() < 0.5:
            tw = (SHIFT[0], PEAK_END)
        if cls is PriorityClass.HIGH and demand > HOT:
            soft = SOFT_DUE
        jobs.append(Job(id=f"swap{k}", location=loc, service=SWAP_SERVICE, delivery=[1, 0, 0],
                        pickup=[0, 1, 0], time_window=tw, soft_due=soft, priority_class=cls,
                        value=value, skills=zone_skill(loc)))

    groups = []
    n_groups, n_members, k_of = spec["groups"]
    for g, h in enumerate(rng.choice(len(hot), n_groups, replace=False)):
        gid = f"zone{g}"
        groups.append(Group(id=gid, k=k_of))
        for m, p in enumerate(_near(rng, hot[h], 250, n_members)):
            loc = add(p, f"{gid}_{m}")
            jobs.append(Job(id=f"{gid}_{m}", location=loc, service=SWAP_SERVICE,
                            delivery=[1, 0, 0], pickup=[0, 1, 0], priority_class=PriorityClass.NORMAL,
                            value=2, group=gid, skills=zone_skill(loc)))

    shipments = []
    for k in range(spec["violations"]):
        p = _near(rng, hot[rng.integers(0, len(hot))], 500, 1)[0]
        angle, metres = rng.uniform(0, 2 * math.pi), rng.uniform(300, 700)
        q = (p[0] + metres * math.sin(angle) / 1000 / KM_PER_DEG_LAT,
             p[1] + metres * math.cos(angle) / 1000 / KM_PER_DEG_LON)
        a, b = add(p, f"viol{k}_from"), add(q, f"viol{k}_to")
        deadline = int(rng.integers(8 * 3600, 11 * 3600))
        shipments.append(Shipment(
            id=f"viol{k}", pickup=Step(location=a, service=180, time_window=(SHIFT[0], deadline)),
            delivery=Step(location=b, service=60), amount=[0, 0, 1], required=True,
            priority_class=PriorityClass.HIGH, skills=zone_skill(a, b)))
    for k in range(spec["rebalance"]):
        src = HOTSPOTS[OVERSUPPLY[rng.integers(0, len(OVERSUPPLY))]]
        dst = HOTSPOTS[DEMAND[rng.integers(0, len(DEMAND))]]
        a, b = add(_near(rng, src, 300, 1)[0], f"reb{k}_from"), add(_near(rng, dst, 200, 1)[0], f"reb{k}_to")
        high = rng.random() < 0.4
        shipments.append(Shipment(
            id=f"reb{k}", pickup=Step(location=a, service=120),
            delivery=Step(location=b, service=60, time_window=(SHIFT[0], SOFT_DUE)),
            amount=[0, 0, 1], priority_class=PriorityClass.HIGH if high else PriorityClass.NORMAL,
            value=3 if high else 2, skills=zone_skill(a, b)))

    vehicles = []
    k = 0
    for kind, count in spec["fleet"].items():
        profile, cap, reloads, fixed, per_m, skills = FLEET_TYPES[kind]
        for _ in range(count):
            hub = ["HUB_S", "HUB_N"][k % 2]
            vehicles.append(Vehicle(
                id=f"{kind}{k}", profile=profile, capacity=cap, start_hub=hub, end_hub=hub,
                reload_hubs=["HUB_S", "HUB_N"], max_reloads=reloads, shift=SHIFT,
                fixed_cost=fixed, distance_cost=per_m, duration_cost=DURATION_COST,
                skills=skills, rest=REST))
            k += 1

    latlon = np.array(pts)
    return RichProblem(
        name=f"voi_{size}{seed:02d}",
        meta={"generator": "rich.voi", "size": size, "seed": seed, "point_names": names,
              "coords": "x=lon, y=lat (WGS84)"},
        dims=["charged", "depleted", "scooters"],
        locations=[Location(id=n, x=lon, y=lat) for n, (lat, lon) in zip(names, pts)],
        profiles=matrices(latlon),
        hubs=[Hub(id=h, location=i, service=HUB_SERVICE) for i, h in enumerate(HUBS)],
        vehicles=vehicles, jobs=jobs, shipments=shipments, groups=groups,
        soft_late_cost=SOFT_LATE_COST)


if __name__ == "__main__":
    from collections import Counter

    for size in SIZES:
        p = build(size, 0)
        classes = Counter(j.priority_class.value for j in p.jobs)
        print(p.name, len(p.locations), "locations,", len(p.jobs), "jobs,", len(p.shipments),
              "shipments,", dict(classes), "zone jobs:", sum(1 for j in p.jobs if j.skills),
              "hard tw:", sum(1 for j in p.jobs if j.time_window),
              "soft due:", sum(1 for j in p.jobs if j.soft_due))

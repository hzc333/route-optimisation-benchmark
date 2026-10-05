"""Synthetic time-dependent travel times (plan §16, Q3).

Ichoua, Gendreau & Potvin (2003) model: an arc has a length and a speed that
is piecewise constant over BUCKET_S time buckets; the travel time is obtained
by driving through the buckets, which guarantees FIFO (leaving later never
means arriving earlier). Speeds:

    v(arc, t) = V_FREE * (1 - (A + B * c_arc) * p(t))

* p(t) in [0, 1]: day profile - morning and evening peaks;
* c_arc in [0, 1]: congestion exposure of the arc, high near the city
  centre (Gaussian in the arc midpoint's distance to the centre).

Python and the Java (Timefold) side implement exactly this function; leg
times are rounded with floor(x + 0.5) on both sides.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

BUCKET_S = 900                 # 15-minute buckets
N_BUCKETS = 24 * 3600 // BUCKET_S
V_FREE = 50 / 3.6              # m/s free-flow speed
A, B = 0.25, 0.45              # slowdown at full peak: outskirts 25 %, centre 70 %


def day_profile() -> list[float]:
    """Peak intensity per 15-min bucket: morning 07:00-09:30 (max 08:00),
    evening 15:30-18:30 (max 17:00), smooth ramps, 0 at night."""
    def bump(t_h: float, centre: float, half_width: float) -> float:
        x = abs(t_h - centre) / half_width
        return max(0.0, 1.0 - x) ** 1.5

    out = []
    for k in range(N_BUCKETS):
        t = (k + 0.5) * BUCKET_S / 3600
        out.append(round(min(1.0, bump(t, 8.0, 1.5) + 0.9 * bump(t, 17.0, 1.75)), 4))
    return out


@dataclass
class TDModel:
    length_m: np.ndarray        # (n, n) arc lengths in metres
    congestion: np.ndarray      # (n, n) exposure c_arc in [0, 1]
    profile: list[float] = field(default_factory=day_profile)
    v_free: float = V_FREE
    a: float = A
    b: float = B
    bucket_s: int = BUCKET_S

    def speed(self, i: int, j: int, bucket: int) -> float:
        p = self.profile[bucket % len(self.profile)]
        return self.v_free * (1.0 - (self.a + self.b * self.congestion[i, j]) * p)

    def travel_time(self, i: int, j: int, t: float) -> int:
        """Seconds to drive i -> j departing at time t (seconds since 00:00)."""
        d = float(self.length_m[i, j])
        if d <= 0:
            return 0
        t0, k = t, int(t // self.bucket_s)
        while True:
            v = self.speed(i, j, k)
            end = (k + 1) * self.bucket_s
            if d <= v * (end - t):
                return int(math.floor(t + d / v - t0 + 0.5))
            d -= v * (end - t)
            t, k = end, k + 1

    def matrix_at(self, t: float) -> np.ndarray:
        """Travel times for departures at time t, all arcs (int seconds)."""
        n = self.length_m.shape[0]
        return np.array([[self.travel_time(i, j, t) for j in range(n)] for i in range(n)])

    def freeflow(self) -> np.ndarray:
        return np.floor(self.length_m / self.v_free + 0.5).astype(int)

    def mean_matrix(self, t0: float, t1: float, step_s: int = 1800) -> np.ndarray:
        times = np.arange(t0, t1, step_s)
        return np.floor(np.mean([self.matrix_at(t) for t in times], axis=0) + 0.5).astype(int)

    def peak_matrix(self) -> np.ndarray:
        peak_t = int(np.argmax(self.profile)) * self.bucket_s
        return self.matrix_at(peak_t)

    def to_json(self) -> dict:
        return {"length_m": self.length_m.astype(int).tolist(),
                "congestion": np.round(self.congestion, 4).tolist(),
                "profile": list(self.profile), "v_free": self.v_free, "a": self.a,
                "b": self.b, "bucket_s": self.bucket_s}

    @classmethod
    def from_json(cls, d: dict) -> TDModel:
        return cls(np.asarray(d["length_m"], dtype=float), np.asarray(d["congestion"]),
                   d["profile"], d["v_free"], d["a"], d["b"], d["bucket_s"])

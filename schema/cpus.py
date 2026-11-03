"""CPUs that benchmark worker processes are pinned to.

The reported results ran on 0, 2, 4, 6: one thread per performance core of an
i5-13500H. On another machine set ROUTE_OPTI_CPUS, e.g. ``0,1,2,3``; listed
CPUs the machine does not have are dropped (falling back to its first four).
"""

from __future__ import annotations

import os

import psutil

DEFAULT = (0, 2, 4, 6)


def bench_cpus(default=DEFAULT) -> list[int]:
    raw = os.environ.get("ROUTE_OPTI_CPUS")
    want = [int(c) for c in raw.split(",") if c.strip()] if raw else list(default)
    have = sorted(psutil.Process().cpu_affinity())
    return [c for c in want if c in have] or have[:4]

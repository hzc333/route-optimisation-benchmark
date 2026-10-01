"""Run one solver x instance x time limit x seed in this process.

Invoked by run_benchmark.py as a subprocess so that every run gets a fresh
interpreter, its own CPU pin and an independent peak-memory reading. Always
writes an output JSON unless the process itself dies; solver exceptions
(incl. UnsupportedFeature) become an ERROR solution with the reason in notes.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from time import perf_counter

import psutil


def peak_rss_mb() -> float:
    mem = psutil.Process().memory_info()
    peak = getattr(mem, "peak_wset", None)  # Windows
    if peak is None:
        import resource  # POSIX: ru_maxrss is KiB on Linux

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    return peak / 2**20


def on_ac_power() -> bool | None:
    battery = psutil.sensors_battery()
    return None if battery is None else battery.power_plugged


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--solver", required=True)
    ap.add_argument("--instance", required=True, type=Path)
    ap.add_argument("--time-limit", required=True, type=float)
    ap.add_argument("--seed", required=True, type=int)
    ap.add_argument("--cpu", type=int)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--options", default="{}", help="JSON dict of adapter options")
    ap.add_argument("--max-vehicles", type=int,
                    help="keep only the first N vehicles (fleet-size sensitivity)")
    args = ap.parse_args()

    # Pin before importing solver libraries so every thread they start
    # inherits the affinity.
    if args.cpu is not None:
        psutil.Process().cpu_affinity([args.cpu])

    t0 = perf_counter()
    ac_at_start = on_ac_power()
    from adapters import UnsupportedFeature, get_adapter
    from schema.models import Problem, Solution, SolverStatus

    adapter = get_adapter(args.solver)
    problem = Problem.model_validate_json(args.instance.read_text(encoding="utf-8"))
    if args.max_vehicles:
        problem = problem.model_copy(update={"vehicles": problem.vehicles[:args.max_vehicles]})
    load_s = perf_counter() - t0

    try:
        solution = adapter.solve(problem, time_limit_s=args.time_limit, seed=args.seed,
                                 threads=1, **json.loads(args.options))
    except Exception as exc:  # recorded, never silently dropped (plan §17)
        kind = "unsupported" if isinstance(exc, UnsupportedFeature) else "exception"
        detail = str(exc) if kind == "unsupported" else traceback.format_exc(limit=5)
        solution = Solution(
            problem_name=problem.name, solver=adapter.NAME, solver_version=adapter.VERSION,
            seed=args.seed, time_limit_s=args.time_limit, threads=1,
            status=SolverStatus.ERROR, unserved=[j.id for j in problem.jobs],
            notes=f"{kind}: {detail}")

    record = {
        "solution": solution.model_dump(mode="json"),
        "run": {
            "instance_path": args.instance.as_posix(),
            "cpu": args.cpu,
            "load_s": load_s,
            "process_wall_s": perf_counter() - t0,
            "peak_rss_mb": peak_rss_mb(),
            "options": json.loads(args.options),
            "max_vehicles": args.max_vehicles,
            # False if on battery at start or end: timings not comparable.
            "on_ac": None if ac_at_start is None else bool(ac_at_start and on_ac_power()),
            "python": sys.version.split()[0],
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_suffix(".tmp")
    tmp.write_text(json.dumps(record), encoding="utf-8")
    tmp.replace(args.out)  # atomic: a partial file never looks like a finished run
    return 0


if __name__ == "__main__":
    sys.exit(main())

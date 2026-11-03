"""Timefold Solver adapter (plan §11): runs the Java adapter jar per solve.

The Java side (adapters/timefold_java, Timefold 2.7.0 community edition, list
variable model) reads the shared Problem JSON and mirrors the validator's
semantics. Score = BendableScore with 1 hard and 5 soft levels
[CRITICAL, HIGH, NORMAL, LOW, cost]:

* mode "weighted" (default): unassigned optional jobs cost
  penalties[class] * value on the cost level - same model as OR-Tools/PyVRP;
* mode "lexicographic": unassigned value is charged on the class's own soft
  level, i.e. Timefold's *native* strict priority.

Construction: "first_fit_decreasing" (default) inserts the hardest visits
first - required, then higher class, then larger demand. Timefold's default
construction inserts in input order; with tight capacity, small low-priority
visits then fill the vehicles and no single local-search move can fit a bulky
critical visit later, so critical jobs stay unassigned even after 20 s.
"default" keeps Timefold's own phases. The standard-benchmark configs use
"default": their jobs are all required NORMAL, so the sorted order reduces
to largest-demand-first, which ignores geography and time windows (Solomon
10 s: 44.7 % gap vs default construction; see results/summary).

JVM handling (plan §11): every solve starts a fresh JVM. ``warmup_s`` first
runs a discarded solve on the same instance in that JVM so the timed solve is
JIT-warm; JVM start-up and warm-up are reported separately and are not part of
``solver_runtime_s``. Build the jar with ``mvn -q package`` in timefold_java
after ``source environments/java_env.sh``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from time import perf_counter

from schema.models import PriorityClass, Problem, Solution

from .base import UnsupportedFeature, build_solution, default_penalties

NAME = "timefold"
VERSION = "2.7.0"
UNSUPPORTED: frozenset[str] = frozenset()
# Used by the "native" priority strategy: strict class levels in the score.
NATIVE_PRIORITY_OPTIONS = {"mode": "lexicographic"}

ROOT = Path(__file__).resolve().parents[1]
JAR = ROOT / "adapters" / "timefold_java" / "target" / "timefold-adapter.jar"
TOOLS = ROOT.parent / "tools"
DEFAULT_WARMUP_S = 5.0


def java_executable() -> str:
    """JAVA_HOME, else a portable JDK in tools/, else ``java`` on PATH (as
    environments/java_env.sh; e.g. Ubuntu's openjdk-21-jdk)."""
    home = os.environ.get("JAVA_HOME")
    if not home:
        jdk = next(TOOLS.glob("jdk-21*"), None)
        if jdk is None:
            on_path = shutil.which("java")
            if on_path is None:
                raise UnsupportedFeature("JDK 21 not found (set JAVA_HOME, install to tools/ or put java on PATH)")
            return on_path
        home = str(jdk)
    exe = Path(home) / "bin" / ("java.exe" if os.name == "nt" else "java")
    return str(exe)


def solve(
    problem: Problem,
    *,
    time_limit_s: float,
    seed: int = 0,
    threads: int = 1,
    penalties: dict[PriorityClass, int] | None = None,
    initial_routes: list[tuple[str, list[str]]] | None = None,
    mode: str = "weighted",
    warmup_s: float | None = None,
    construction: str = "first_fit_decreasing",
    td: dict | None = None,
    heap: str = "2g",
) -> Solution:
    t_wall = perf_counter()
    jar = Path(os.environ.get("ROB_TIMEFOLD_JAR", JAR))  # override for experiments
    if not jar.exists():
        raise UnsupportedFeature(f"{JAR.name} not built (mvn package in adapters/timefold_java)")
    if warmup_s is None:  # env override lets tests skip the warm-up
        warmup_s = float(os.environ.get("ROB_TIMEFOLD_WARMUP_S", DEFAULT_WARMUP_S))
    penalties = penalties or default_penalties(problem)
    options = {
        "time_limit_s": time_limit_s, "seed": seed, "mode": mode, "warmup_s": warmup_s,
        "construction": construction,
        # Time-dependent travel (traffic/model.py TDModel.to_json()): arrival
        # times and leg costs use it inside the search instead of the matrices.
        "td": td,
        "penalties": {c.value: int(p) for c, p in penalties.items()},
        "initial_routes": [[v, list(js)] for v, js in initial_routes] if initial_routes else None,
    }
    with tempfile.TemporaryDirectory(prefix="tf_") as tmp:
        src, dst = Path(tmp) / "in.json", Path(tmp) / "out.json"
        src.write_text(json.dumps({"problem": problem.model_dump(mode="json"), "options": options}),
                       encoding="utf-8")
        cmd = [java_executable(), f"-Xmx{heap}", "-jar", str(jar), str(src), str(dst)]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=time_limit_s + warmup_s + 60)
        if proc.returncode != 0 or not dst.exists():
            raise RuntimeError(f"timefold jar exit {proc.returncode}: {proc.stderr[-2000:]}")
        out = json.loads(dst.read_text(encoding="utf-8"))

    return build_solution(
        problem, solver=NAME, solver_version=VERSION,
        routes=[(r["vehicle_id"], r["job_ids"]) for r in out["routes"]],
        seed=seed, time_limit_s=time_limit_s, threads=1,
        solver_runtime_s=out["solver_runtime_s"], time_to_best_s=out["time_to_best_s"],
        wall_runtime_s=perf_counter() - t_wall,
        notes=(f"mode={mode}; score={out['score']}; warmup_s={warmup_s:g}; "
               f"jvm_startup_s={out['jvm_startup_s']:.2f}; load_s={out['load_s']:.2f}; "
               f"java_peak_heap_mb={out['java_peak_heap_mb']:.0f}; "
               f"move_eval_per_s={out.get('move_evaluation_speed')}"))

"""Benchmark runner (plan §17).

    python -m experiments.run_benchmark experiments/configs/solomon.yaml

Expands solvers x instances x time limits x seeds, converts instances on
demand, shuffles the run order (fixed seed) so every solver sees the same
mix of thermal / background conditions, and runs each case as a pinned
subprocess on one of ``cpus``. Finished runs are skipped on restart.
Crashes and timeouts still produce a result file. Aggregation runs at the end.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import random
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from queue import Queue

import yaml

from data.convert import converted_path, instance_names, write_converted

ROOT = Path(__file__).resolve().parents[1]
RAW_RESULTS = ROOT / "results" / "raw"


@dataclass(frozen=True)
class Case:
    label: str    # result directory / name in reports, e.g. "ortools_pca"
    adapter: str  # adapter module name, e.g. "ortools"
    family: str
    instance: str
    time_limit_s: float
    seed: int
    options: str  # JSON, part of the identity of a run

    @property
    def out(self) -> Path:
        tl = f"{self.time_limit_s:g}"
        return Path(self.label) / self.family / f"{self.instance}__tl{tl}__s{self.seed}.json"


def resolve_instances(patterns: list[str]) -> list[tuple[str, str]]:
    out = []
    for pat in patterns:
        family, name_pat = pat.split("/", 1)
        if family == "smoke":
            names = sorted(p.stem for p in converted_path("smoke", "x").parent.glob(name_pat + ".json"))
        else:
            names = [n for n in instance_names(family) if fnmatch.fnmatch(n, name_pat)]
        if not names:
            raise SystemExit(f"no instances match {pat!r}")
        out += [(family, n) for n in names]
    return list(dict.fromkeys(out))


def solver_variants(cfg: dict) -> list[tuple[str, str, dict]]:
    """``solvers`` entries are an adapter name or {label, adapter, options}."""
    out = []
    for entry in cfg["solvers"]:
        if isinstance(entry, str):
            entry = {"label": entry, "adapter": entry}
        out.append((entry["label"], entry.get("adapter", entry["label"]), entry.get("options", {})))
    return out


def expand(cfg: dict) -> list[Case]:
    cases = [
        Case(label, adapter, fam, name, float(tl), int(seed), json.dumps(opts, sort_keys=True))
        for label, adapter, opts in solver_variants(cfg)
        for fam, name in resolve_instances(cfg["instances"])
        for tl in cfg["time_limits_s"]
        for seed in cfg["seeds"]
    ]
    random.Random(cfg.get("order_seed", 0)).shuffle(cases)
    return cases


def run_case(case: Case, cpu: int, out_dir: Path) -> str:
    out = out_dir / case.out
    cmd = [sys.executable, "-m", "experiments.run_one", "--solver", case.adapter,
           "--instance", str(converted_path(case.family, case.instance)),
           "--time-limit", str(case.time_limit_s), "--seed", str(case.seed),
           "--cpu", str(cpu), "--out", str(out), "--options", case.options]
    timeout = case.time_limit_s * 2 + 60
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        status, err = ("OK", "") if proc.returncode == 0 and out.exists() else (
            "ERROR", f"exit {proc.returncode}: {proc.stderr[-2000:]}")
    except subprocess.TimeoutExpired:
        status, err = "TIMEOUT", f"killed after {timeout:.0f}s"
    if status != "OK":
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "solution": {
                "problem_name": case.instance, "solver": case.adapter, "solver_version": "?",
                "seed": case.seed, "time_limit_s": case.time_limit_s, "threads": 1,
                "status": status, "notes": err,
            },
            "run": {"cpu": cpu, "process_wall_s": time.perf_counter() - t0,
                    "options": json.loads(case.options)},
        }), encoding="utf-8")
    return status


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("config", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    cfg = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    name = cfg.get("name", args.config.stem)
    out_dir = RAW_RESULTS / name

    cases = expand(cfg)
    todo = [c for c in cases if not (out_dir / c.out).exists()]
    budget = sum(c.time_limit_s for c in todo) / len(cfg["cpus"])
    print(f"[{name}] {len(cases)} runs, {len(todo)} to do, "
          f"~{budget / 60:.0f} min on {len(cfg['cpus'])} cpus {cfg['cpus']}", flush=True)
    if args.dry_run:
        return

    for fam, inst in {(c.family, c.instance) for c in todo}:
        if not converted_path(fam, inst).exists():
            write_converted(fam, inst)

    cpus: Queue[int] = Queue()
    for cpu in cfg["cpus"]:
        cpus.put(cpu)
    lock, done, t_start = threading.Lock(), [0], time.time()

    def worker(case: Case) -> None:
        cpu = cpus.get()
        try:
            status = run_case(case, cpu, out_dir)
        finally:
            cpus.put(cpu)
        with lock:
            done[0] += 1
            if status != "OK" or done[0] % 20 == 0 or done[0] == len(todo):
                el = time.time() - t_start
                print(f"[{name}] {done[0]}/{len(todo)} {el / 60:.1f} min"
                      + ("" if status == "OK" else f"  {status}: {case}"), flush=True)

    with ThreadPoolExecutor(len(cfg["cpus"])) as pool:
        list(pool.map(worker, todo))

    from experiments.aggregate import aggregate

    aggregate(name)


if __name__ == "__main__":
    main()

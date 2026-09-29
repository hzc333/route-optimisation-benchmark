"""Validate + score every raw run of an experiment and write CSVs.

    python -m experiments.aggregate <experiment-name>

Outputs (results/summary/):
  <exp>_runs.csv       one row per run (plan §17 fields) - the raw record
  <exp>_instances.csv  per solver x instance x time limit: seed statistics
  <exp>_families.csv   per solver x family x time limit: headline numbers

Validation happens here, from the saved solutions, independently of the
solver process. Gap statistics only use feasible runs; the feasible count is
reported next to them so nothing is dropped silently.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

from data.convert import load_bks
from evaluator import gap_to_bks, objective_vector, validate
from schema.models import Problem, Solution

ROOT = Path(__file__).resolve().parents[1]
RAW_RESULTS, SUMMARY = ROOT / "results" / "raw", ROOT / "results" / "summary"


def _load_problem(family: str, instance: str, run: dict) -> Problem:
    path = Path(run.get("instance_path") or ROOT / "data" / "converted" / family / f"{instance}.json")
    if not path.is_absolute():
        path = ROOT / path
    return Problem.model_validate_json(path.read_text(encoding="utf-8"))


def collect_rows(exp: str) -> list[dict]:
    bks = load_bks()
    # Layout: <exp>/<label>/<family>/<instance>__tl<T>__s<seed>.json
    by_instance: dict[tuple[str, str], list[Path]] = defaultdict(list)
    for f in (RAW_RESULTS / exp).glob("*/*/*.json"):
        by_instance[(f.parent.name, f.name.split("__")[0])].append(f)

    rows = []
    for (family, instance), files in sorted(by_instance.items()):
        problem = None
        for f in sorted(files):
            rec = json.loads(f.read_text(encoding="utf-8"))
            s, run = rec["solution"], rec["run"]
            row = {
                "solver": f.parts[-3], "adapter": s["solver"], "version": s.get("solver_version"),
                "family": family, "instance": instance,
                "time_limit_s": s["time_limit_s"], "seed": s["seed"], "threads": s.get("threads"),
                "status": s["status"], "cpu": run.get("cpu"),
                "wall_time_s": s.get("wall_runtime_s"), "solver_time_s": s.get("solver_runtime_s"),
                "time_to_best_s": s.get("time_to_best_s"), "process_wall_s": run.get("process_wall_s"),
                "load_s": run.get("load_s"), "peak_rss_mb": run.get("peak_rss_mb"),
                "native_objective": s.get("native_objective"), "notes": s.get("notes", ""),
            }
            if s.get("solver_version") != "?":  # "?" = runner-written crash/timeout record
                problem = problem or _load_problem(family, instance, run)
                solution = Solution.model_validate(s)
                rep = validate(problem, solution)
                row |= {"n_jobs": len(problem.jobs), "feasible": rep.feasible,
                        "violations": ";".join(sorted({v.kind for v in rep.violations}))}
                row |= objective_vector(problem, rep)
                if rep.feasible and instance in bks:
                    row["bks"] = int(bks[instance]["bks_scaled"])
                    row["gap_to_bks"] = gap_to_bks(row["distance"], row["bks"])
            else:
                row |= {"feasible": False, "violations": s["status"]}
            rows.append(row)
    return rows


def aggregate(exp: str) -> pd.DataFrame:
    df = pd.DataFrame(collect_rows(exp))
    if df.empty:
        raise SystemExit(f"no runs under {RAW_RESULTS / exp}")
    for col in ("gap_to_bks", "bks", "n_jobs", "distance"):
        if col not in df:
            df[col] = pd.NA
    SUMMARY.mkdir(parents=True, exist_ok=True)
    df.sort_values(["family", "instance", "solver", "time_limit_s", "seed"]).to_csv(
        SUMMARY / f"{exp}_runs.csv", index=False, lineterminator="\n")

    keys = ["solver", "family", "instance", "time_limit_s"]
    inst = df.groupby(keys).agg(
        n_runs=("seed", "size"), n_feasible=("feasible", "sum"), n_jobs=("n_jobs", "first"),
        bks=("bks", "first"),
        gap_mean=("gap_to_bks", "mean"), gap_median=("gap_to_bks", "median"),
        gap_best=("gap_to_bks", "min"), gap_worst=("gap_to_bks", "max"),
        gap_std=("gap_to_bks", "std"),
        dist_best=("distance", "min"),
        wall_mean=("wall_time_s", "mean"), ttb_mean=("time_to_best_s", "mean"),
        rss_max=("peak_rss_mb", "max"),
    ).reset_index()
    inst.to_csv(SUMMARY / f"{exp}_instances.csv", index=False, lineterminator="\n",
                float_format="%.4f")

    fam = inst.groupby(["solver", "family", "time_limit_s"]).agg(
        n_instances=("instance", "size"), runs=("n_runs", "sum"), feasible=("n_feasible", "sum"),
        gap_mean=("gap_mean", "mean"), gap_median=("gap_median", "median"),
        gap_best_mean=("gap_best", "mean"), gap_std_mean=("gap_std", "mean"),
        wall_mean=("wall_mean", "mean"), ttb_mean=("ttb_mean", "mean"), rss_max=("rss_max", "max"),
    ).reset_index()
    fam.to_csv(SUMMARY / f"{exp}_families.csv", index=False, lineterminator="\n",
               float_format="%.4f")
    with pd.option_context("display.width", 200, "display.max_columns", 20):
        print(fam.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("experiment")
    aggregate(ap.parse_args().experiment)

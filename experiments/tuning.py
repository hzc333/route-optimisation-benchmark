"""Fair parameter tuning for OR-Tools and PyVRP (equal tuning budget).

    python -m experiments.tuning sample   # write configs/tune_train.yaml
    python -m experiments.run_benchmark experiments/configs/tune_train.yaml
    python -m experiments.tuning select   # pick best per solver, write tune_test_*.yaml
    python -m experiments.run_benchmark experiments/configs/tune_test_*.yaml
    python -m experiments.tuning compare  # tuned vs default on the test runs
    python -m experiments.tuning ofat     # one-change-at-a-time follow-up (tune_ofat.yaml)
    python -m experiments.tuning ofat-report

Protocol:
* Each solver gets the same budget: N_CONFIGS configurations (config 0 is the
  solver default used in the main benchmark), each run on the same TRAIN
  instances x TRAIN_SEEDS at TRAIN_TIME_S.
* Score = mean over training instances of the mean gap to BKS; an infeasible
  run counts as INFEASIBLE_GAP so robustness is part of the score.
* The best configuration is then evaluated on held-out TEST instances (the
  main benchmark sets minus the training instances), seeds 0-4, and compared
  with the default runs of the same seeds from the main benchmark.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import pandas as pd
import yaml

from data.convert import instance_names
from schema.cpus import bench_cpus

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = ROOT / "experiments" / "configs"
SUMMARY = ROOT / "results" / "summary"

N_CONFIGS = 24
TRAIN_TIME_S = 10
TRAIN_SEEDS = [0, 1]
SAMPLE_SEED = 20261005
INFEASIBLE_GAP = 100.0
CPUS = bench_cpus()

TRAIN = ["solomon/C103", "solomon/C204", "solomon/R106", "solomon/R209",
         "solomon/RC104", "solomon/RC207",
         "x/X-n129-k18", "x/X-n228-k23", "x/X-n317-k53"]
TEST_SEEDS = [0, 1, 2, 3, 4]
X_TEST = ["x/X-n101-k25", "x/X-n148-k46", "x/X-n200-k36", "x/X-n251-k28", "x/X-n303-k21",
          "x/X-n351-k40", "x/X-n401-k29", "x/X-n459-k26", "x/X-n502-k39", "x/X-n701-k44",
          "x/X-n1001-k43"]
HG_TEST = ["hg1000/C1_10_1", "hg1000/C2_10_1", "hg1000/R1_10_1",
           "hg1000/R2_10_1", "hg1000/RC1_10_1", "hg1000/RC2_10_1"]
# test experiment name -> (instances, time limits, main-benchmark experiment)
TESTS = {
    "tune_test_solomon": (None, [10], "solomon"),
    "tune_test_x": (X_TEST, [10, 60], "x"),
    "tune_test_hg": (HG_TEST, [60], "hg1000"),
}

# ---------------------------------------------------------- search spaces ---

def _ruin(kind: str) -> dict:
    """OR-Tools 9.15 iterated local search with one ruin strategy (recreate =
    local cheapest insertion, the 9.15 default)."""
    strategy = {
        "sisr": {"sisr": {"max_removed_sequence_size": 10, "avg_num_removed_visits": 10,
                          "bypass_factor": 0.01}},
        "random_walk": {"random_walk": {"num_removed_visits": 10}},
        "close_routes": {"spatially_close_routes": {"num_ruined_routes": 2}},
    }[kind]
    return {"use_iterated_local_search": True,
            "iterated_local_search_parameters": {
                "ruin_recreate_parameters": {"ruin_strategies": [strategy]}}}


LNS_BUNDLE = {f: "BOOL_TRUE" for f in (
    "use_path_lns", "use_inactive_lns", "use_relocate_neighbors", "use_cross_exchange",
    "use_global_cheapest_insertion_close_nodes_lns", "use_local_cheapest_insertion_close_nodes_lns")}

ORTOOLS_SPACE = {
    "first_solution": ["PARALLEL_CHEAPEST_INSERTION", "LOCAL_CHEAPEST_INSERTION", "SAVINGS"],
    "metaheuristic": ["GUIDED_LOCAL_SEARCH", "SIMULATED_ANNEALING", "TABU_SEARCH",
                      "GENERIC_TABU_SEARCH"],
    "ils": [None, "sisr", "random_walk", "close_routes"],
    "neighbors_ratio": [1.0, 0.3, 0.1],
    "gls_lambda": [0.05, 0.1, 0.2, 0.5],
    "lns_bundle": [False, True],
}
PYVRP_SPACE = {
    "num_neighbours": [20, 30, 50, 70],
    "weight_wait_time": [0.1, 0.2, 0.5],
    "history_length": [100, 300, 600],
    "num_iters_no_improvement": [20_000, 150_000, 500_000],
    "max_perturbations": [10, 25, 50],
    "exhaustive_on_best": [True, False],
    "target_feasible": [0.5, 0.65, 0.8],
}


def ortools_options(choice: dict) -> dict:
    sp: dict = {"guided_local_search_lambda_coefficient": choice["gls_lambda"],
                "ls_operator_neighbors_ratio": choice["neighbors_ratio"],
                "ls_operator_min_neighbors": 10}
    if choice["ils"]:
        sp.update(_ruin(choice["ils"]))
    if choice["lns_bundle"]:
        sp["local_search_operators"] = dict(LNS_BUNDLE)
    return {"first_solution": choice["first_solution"],
            "metaheuristic": choice["metaheuristic"], "search_params": sp}


def sample_space(space: dict, n: int, rng: random.Random) -> list[dict]:
    seen, out = set(), []
    while len(out) < n:
        choice = {k: rng.choice(v) for k, v in space.items()}
        key = json.dumps(choice, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(choice)
    return out


def variants() -> list[dict]:
    """Config 0 of each solver = the main-benchmark default."""
    rng = random.Random(SAMPLE_SEED)
    out = [{"label": "ortools_c00", "adapter": "ortools", "options": {}},
           {"label": "pyvrp_c00", "adapter": "pyvrp", "options": {}}]
    for i, c in enumerate(sample_space(ORTOOLS_SPACE, N_CONFIGS - 1, rng), start=1):
        out.append({"label": f"ortools_c{i:02d}", "adapter": "ortools",
                    "options": ortools_options(c), "choice": c})
    for i, c in enumerate(sample_space(PYVRP_SPACE, N_CONFIGS - 1, rng), start=1):
        out.append({"label": f"pyvrp_c{i:02d}", "adapter": "pyvrp",
                    "options": {"solve_params": c}, "choice": c})
    return out

# ------------------------------------------------------------- commands ---

def _write_yaml(name: str, cfg: dict, header: str) -> Path:
    path = CONFIGS / f"{name}.yaml"
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(header)
        yaml.safe_dump(cfg, fh, sort_keys=False, allow_unicode=True, width=120)
    return path


def cmd_sample() -> None:
    solvers = [{k: v for k, v in var.items() if k != "choice"} for var in variants()]
    path = _write_yaml("tune_train", {
        "name": "tune_train", "solvers": solvers, "instances": TRAIN,
        "time_limits_s": [TRAIN_TIME_S], "seeds": TRAIN_SEEDS, "cpus": CPUS,
    }, "# GENERATED by experiments/tuning.py sample - do not edit.\n"
       f"# {N_CONFIGS} configs per solver (c00 = default), equal budget.\n")
    print(f"wrote {path.relative_to(ROOT)} ({len(solvers)} variants)")


def train_scores() -> pd.DataFrame:
    runs = pd.read_csv(SUMMARY / "tune_train_runs.csv")
    runs["score_gap"] = runs.gap_to_bks.where(runs.feasible, INFEASIBLE_GAP)
    per_inst = runs.groupby(["solver", "instance"]).agg(
        gap=("score_gap", "mean"), feasible=("feasible", "mean")).reset_index()
    scores = per_inst.groupby("solver").agg(
        score=("gap", "mean"), feasible_rate=("feasible", "mean")).reset_index()
    scores["adapter"] = scores.solver.str.split("_").str[0]
    return scores.sort_values(["adapter", "score"])


def cmd_select() -> None:
    scores = train_scores()
    by_label = {v["label"]: v for v in variants()}
    scores["options"] = scores.solver.map(lambda s: json.dumps(by_label[s].get("choice", "default")))
    scores.to_csv(SUMMARY / "tuning_train_scores.csv", index=False, lineterminator="\n",
                  float_format="%.4f")
    best = scores.groupby("adapter").head(1).set_index("adapter")
    print(scores.groupby("adapter").head(5).to_string(index=False))
    solvers = [{"label": f"{a}_tuned", "adapter": a, "options": by_label[best.loc[a, "solver"]]["options"]}
               for a in ("ortools", "pyvrp")]
    # Same-day control: OR-Tools results drift between days (timing-sensitive
    # search), so tuned runs are compared with the default re-run in the same
    # session. Not needed when the best config *is* the default.
    solvers += [{"label": f"{a}_default", "adapter": a, "options": {}}
                for a in ("ortools", "pyvrp") if not best.loc[a, "solver"].endswith("_c00")]
    for name, (instances, tls, _) in TESTS.items():
        if instances is None:  # all Solomon minus the training ones
            instances = [f"solomon/{n}" for n in instance_names("solomon")
                         if f"solomon/{n}" not in TRAIN]
        path = _write_yaml(name, {
            "name": name, "solvers": solvers, "instances": instances,
            "time_limits_s": tls, "seeds": TEST_SEEDS, "cpus": CPUS,
        }, "# GENERATED by experiments/tuning.py select - do not edit.\n"
           f"# Best training configs: {dict(best.solver)}\n")
        print(f"wrote {path.relative_to(ROOT)}")


def ofat_variants() -> list[dict]:
    """One change at a time from each default (same count per solver): the
    random sample happened to contain no 'default + one change' point."""
    default_sp = {"guided_local_search_lambda_coefficient": 0.1,
                  "ls_operator_neighbors_ratio": 1.0, "ls_operator_min_neighbors": 1}
    ort = {
        "ils_sisr": {"search_params": {**default_sp, **_ruin("sisr")}},
        "ils_close_routes": {"search_params": {**default_sp, **_ruin("close_routes")}},
        "simulated_annealing": {"metaheuristic": "SIMULATED_ANNEALING"},
        "lns_bundle": {"search_params": {**default_sp, "local_search_operators": dict(LNS_BUNDLE)}},
    }
    pyv = {
        "num_neighbours_20": {"num_neighbours": 20},
        "history_length_600": {"history_length": 600},
        "exhaustive_off": {"exhaustive_on_best": False},
        "target_feasible_0.8": {"target_feasible": 0.8},
    }
    return ([{"label": f"ortools_ofat_{k}", "adapter": "ortools", "options": v} for k, v in ort.items()]
            + [{"label": f"pyvrp_ofat_{k}", "adapter": "pyvrp", "options": {"solve_params": v}}
               for k, v in pyv.items()])


def cmd_ofat() -> None:
    path = _write_yaml("tune_ofat", {
        "name": "tune_ofat", "solvers": ofat_variants(), "instances": TRAIN,
        "time_limits_s": [TRAIN_TIME_S], "seeds": TRAIN_SEEDS, "cpus": CPUS,
    }, "# GENERATED by experiments/tuning.py ofat - do not edit.\n"
       "# One change at a time from each solver's default, same budget per solver.\n")
    print(f"wrote {path.relative_to(ROOT)}")


def cmd_ofat_report() -> None:
    frames = []
    for exp in ("tune_train", "tune_ofat"):
        runs = pd.read_csv(SUMMARY / f"{exp}_runs.csv")
        if exp == "tune_train":
            runs = runs[runs.solver.isin(["ortools_c00", "pyvrp_c00"])]
        frames.append(runs)
    runs = pd.concat(frames)
    runs["score_gap"] = runs.gap_to_bks.where(runs.feasible, INFEASIBLE_GAP)
    per_inst = runs.groupby(["solver", "instance"]).score_gap.mean().reset_index()
    out = per_inst.groupby("solver").score_gap.mean().rename("score").reset_index()
    out["adapter"] = out.solver.str.split("_").str[0]
    out = out.sort_values(["adapter", "score"])
    out.to_csv(SUMMARY / "tuning_ofat_scores.csv", index=False, lineterminator="\n",
               float_format="%.4f")
    print(out.to_string(index=False, float_format=lambda x: f"{x:.3f}"))


def cmd_compare() -> None:
    """Per adapter: default re-run today (same-day control), tuned, and the
    main-benchmark default (other day) to show day-to-day drift."""
    scores = pd.read_csv(SUMMARY / "tuning_train_scores.csv")
    best = scores.groupby("adapter").head(1).set_index("adapter").solver
    rows = []
    for name, (_, _, main) in TESTS.items():
        test = pd.read_csv(SUMMARY / f"{name}_runs.csv")
        base = pd.read_csv(SUMMARY / f"{main}_runs.csv")
        base = base[base.seed.isin(TEST_SEEDS) & base.instance.isin(set(test.instance))
                    & base.time_limit_s.isin(set(test.time_limit_s))]
        for a in ("ortools", "pyvrp"):
            tuned = test[test.solver == f"{a}_tuned"]
            today = tuned if best[a].endswith("_c00") else test[test.solver == f"{a}_default"]
            arms = {"default_today": today, "tuned": tuned,
                    "default_other_day": base[base.solver == a]}
            for arm, d in arms.items():
                for tl, g in d.groupby("time_limit_s"):
                    rows.append({"test_set": name.removeprefix("tune_test_"), "adapter": a,
                                 "arm": arm, "time_limit_s": tl, "runs": len(g),
                                 "feasible": g.feasible.mean(), "gap_mean": g.gap_to_bks.mean(),
                                 "gap_median": g.gap_to_bks.median(),
                                 "best_config": best[a] if arm == "tuned" else ""})
    out = pd.DataFrame(rows)
    out.to_csv(SUMMARY / "tuning_comparison.csv", index=False, lineterminator="\n",
               float_format="%.4f")
    print(out.to_string(index=False, float_format=lambda x: f"{x:.3f}"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    commands = {"sample": cmd_sample, "select": cmd_select, "compare": cmd_compare,
                "ofat": cmd_ofat, "ofat-report": cmd_ofat_report}
    ap.add_argument("command", choices=list(commands))
    commands[ap.parse_args().command]()

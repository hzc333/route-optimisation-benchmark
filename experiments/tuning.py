"""Fair parameter tuning for OR-Tools and PyVRP (equal tuning budget).

    python -m experiments.tuning sample   # write configs/tune_train.yaml
    python -m experiments.run_benchmark experiments/configs/tune_train.yaml
    python -m experiments.tuning select   # pick best per solver, write tune_test_*.yaml
    python -m experiments.run_benchmark experiments/configs/tune_test_*.yaml
    python -m experiments.tuning compare  # tuned vs default on the test runs

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

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = ROOT / "experiments" / "configs"
SUMMARY = ROOT / "results" / "summary"

N_CONFIGS = 24
TRAIN_TIME_S = 10
TRAIN_SEEDS = [0, 1]
SAMPLE_SEED = 20261005
INFEASIBLE_GAP = 100.0
CPUS = [0, 2, 4, 6]

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


def cmd_compare() -> None:
    rows = []
    for name, (_, _, main) in TESTS.items():
        tuned = pd.read_csv(SUMMARY / f"{name}_runs.csv")
        base = pd.read_csv(SUMMARY / f"{main}_runs.csv")
        base = base[base.solver.isin(["ortools", "pyvrp"]) & base.seed.isin(TEST_SEEDS)
                    & base.instance.isin(set(tuned.instance))
                    & base.time_limit_s.isin(set(tuned.time_limit_s))]
        both = pd.concat([base, tuned])
        both["variant"] = both.solver.where(~both.solver.str.endswith("_tuned"), "tuned")
        both["variant"] = both.variant.where(both.variant == "tuned", "default")
        both["adapter"] = both.solver.str.split("_").str[0]
        g = both.groupby(["adapter", "variant", "time_limit_s"]).agg(
            runs=("seed", "size"), feasible=("feasible", "mean"),
            gap_mean=("gap_to_bks", "mean"), gap_median=("gap_to_bks", "median")).reset_index()
        g.insert(0, "test_set", name.removeprefix("tune_test_"))
        rows.append(g)
    out = pd.concat(rows)
    out.to_csv(SUMMARY / "tuning_comparison.csv", index=False, lineterminator="\n",
               float_format="%.4f")
    print(out.to_string(index=False, float_format=lambda x: f"{x:.3f}"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["sample", "select", "compare"])
    {"sample": cmd_sample, "select": cmd_select, "compare": cmd_compare}[ap.parse_args().command]()

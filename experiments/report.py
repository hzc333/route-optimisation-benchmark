"""Figures + markdown tables from results/summary/*.csv.

    python -m experiments.report

Writes results/plots/*.png and results/summary/report_tables.md. Every
number in the tables is computed from the per-run CSVs; nothing is typed in.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SUMMARY, PLOTS = ROOT / "results" / "summary", ROOT / "results" / "plots"

# Reference palette, categorical slots in fixed order (light mode).
COLORS = {"ortools": "#2a78d6", "pyvrp": "#eb6834", "vroom": "#1baf7a"}
LABELS = {"ortools": "OR-Tools (PCI+GLS)", "pyvrp": "PyVRP", "vroom": "VROOM (x=5)"}
MAIN = list(COLORS)  # solvers shown in figures, in palette order


def _present(df: pd.DataFrame) -> list[str]:
    return [s for s in MAIN if s in set(df.solver)]


def _bar_offsets(n: int, width: float) -> list[float]:
    return [(k - (n - 1) / 2) * (width + 0.02) for k in range(n)]
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.grid": True, "axes.grid.axis": "y",
    "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False, "axes.axisbelow": True,
    "font.size": 10, "axes.titlesize": 11, "legend.frameon": False,
})


def _read(name: str) -> pd.DataFrame | None:
    path = SUMMARY / name
    return pd.read_csv(path) if path.exists() else None


def solomon_class(instance: str) -> str:
    head = instance.rstrip("0123456789")
    return head + instance[len(head)]  # C101 -> C1, RC205 -> RC2


def fig_solomon(runs: pd.DataFrame) -> None:
    solvers = _present(runs)
    runs = runs[runs.solver.isin(solvers)].copy()
    runs["cls"] = runs.instance.map(solomon_class)
    per_inst = runs.groupby(["solver", "time_limit_s", "cls", "instance"]).gap_to_bks.mean()
    agg = per_inst.groupby(["solver", "time_limit_s", "cls"]).mean().reset_index()
    classes = ["C1", "C2", "R1", "R2", "RC1", "RC2"]
    tls = sorted(agg.time_limit_s.unique())
    fig, axes = plt.subplots(1, len(tls), figsize=(5.2 * len(tls), 3.6), sharey=True)
    for ax, tl in zip(axes if len(tls) > 1 else [axes], tls):
        width = 0.8 / len(solvers)
        for off, solver in zip(_bar_offsets(len(solvers), width), solvers):
            d = agg[(agg.solver == solver) & (agg.time_limit_s == tl)].set_index("cls")
            xs = [i + off for i in range(len(classes))]
            ax.bar(xs, [d.gap_to_bks.get(c, float("nan")) for c in classes], width,
                   color=COLORS[solver], label=LABELS[solver])
        ax.set_xticks(range(len(classes)), classes)
        ax.set_title(f"{tl:g} s per run")
    axes[0].set_ylabel("mean gap to BKS (%)")
    axes[0].legend(loc="upper left")
    fig.suptitle("Solomon VRPTW (100 customers): gap by instance class, feasible runs", x=0.01,
                 ha="left", fontsize=12)
    fig.tight_layout()
    fig.savefig(PLOTS / "solomon_gap_by_class.png", dpi=150)
    plt.close(fig)


def fig_x(inst: pd.DataFrame) -> None:
    tls = sorted(inst.time_limit_s.unique())
    fig, axes = plt.subplots(1, len(tls), figsize=(5.2 * len(tls), 3.6), sharey=True)
    for ax, tl in zip(axes if len(tls) > 1 else [axes], tls):
        for solver in _present(inst):
            d = inst[(inst.solver == solver) & (inst.time_limit_s == tl)].sort_values("n_jobs")
            ax.fill_between(d.n_jobs, d.gap_best, d.gap_worst, color=COLORS[solver], alpha=0.15,
                            linewidth=0)
            ax.plot(d.n_jobs, d.gap_mean, color=COLORS[solver], linewidth=2, marker="o",
                    markersize=5, label=LABELS[solver])
        ax.set_title(f"{tl:g} s per run")
        ax.set_xlabel("customers")
    axes[0].set_ylabel("gap to BKS (%)")
    axes[0].legend(loc="upper left")
    fig.suptitle("CVRPLIB X: gap vs instance size (line = mean of 10 seeds, band = best to worst)",
                 x=0.01, ha="left", fontsize=12)
    fig.tight_layout()
    fig.savefig(PLOTS / "x_gap_vs_size.png", dpi=150)
    plt.close(fig)


def fig_hg(inst: pd.DataFrame) -> None:
    names = sorted(inst.instance.unique())
    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    solvers = _present(inst)
    width = 0.8 / len(solvers)
    for off, solver in zip(_bar_offsets(len(solvers), width), solvers):
        d = inst[inst.solver == solver].set_index("instance")
        xs = [i + off for i in range(len(names))]
        ax.bar(xs, [d.gap_mean.get(n, float("nan")) for n in names], width,
               color=COLORS[solver], label=LABELS[solver])
    ax.set_xticks(range(len(names)), names)
    ax.set_ylabel("mean gap to BKS (%)")
    ax.legend(loc="upper left")
    ax.set_title("Gehring & Homberger 1000 customers, 60 s per run", loc="left")
    fig.tight_layout()
    fig.savefig(PLOTS / "hg1000_gap.png", dpi=150)
    plt.close(fig)


def _md(df: pd.DataFrame, floatfmt: str = ".2f") -> str:
    return df.to_markdown(index=False, floatfmt=floatfmt)


def tables() -> str:
    out = ["# Benchmark tables (generated by experiments/report.py)\n"]
    for exp in ["solomon", "solomon_60s", "x", "hg1000", "hg1000_fleet"]:
        fam = _read(f"{exp}_families.csv")
        runs = _read(f"{exp}_runs.csv")
        if fam is None:
            continue
        status = runs.groupby(["solver", "time_limit_s"]).agg(
            runs=("seed", "size"), feasible=("feasible", "sum"),
            no_solution=("status", lambda s: (s == "NO_SOLUTION").sum()),
            errors=("status", lambda s: s.isin(["ERROR", "TIMEOUT"]).sum())).reset_index()
        out += [f"## {exp}\n", _md(fam[["solver", "time_limit_s", "n_instances", "runs",
                                        "feasible", "gap_mean", "gap_median", "gap_best_mean",
                                        "gap_std_mean", "ttb_mean", "rss_max"]]), "",
                "Run status:\n", _md(status, ".0f"), ""]
        inst = _read(f"{exp}_instances.csv")
        both = inst.pivot_table(index="instance", columns=["solver", "time_limit_s"],
                                values="gap_mean")
        rows = []
        for a, b in (("pyvrp", "ortools"), ("pyvrp", "vroom"), ("vroom", "ortools")):
            for tl in sorted(inst.time_limit_s.unique()):
                if (a, tl) not in both or (b, tl) not in both:
                    continue
                ga, gb = both[(a, tl)], both[(b, tl)]
                rows.append({"pair": f"{a} vs {b}", "time_limit_s": tl,
                             "first_better": int((ga < gb - 1e-9).sum()),
                             "tie": int(((ga - gb).abs() <= 1e-9).sum()),
                             "second_better": int((gb < ga - 1e-9).sum())})
        if rows:
            out += ["Per-instance comparison of mean gap:\n", _md(pd.DataFrame(rows), ".0f"), ""]

    pc = _read("priority_cases.csv")
    if pc is not None:
        t = pc.pivot_table(index=["instance", "solver"], columns="strategy",
                           values="strict_ok", aggfunc="mean").reset_index()
        out += ["## Strict priority: share of runs hitting the strict-optimal vector\n",
                _md(t, ".0%"), ""]
    pr = _read("priority_random_summary.csv")
    if pr is not None:
        out += ["## Strict priority: random stress instances\n", _md(pr, ".3f"), ""]
    return "\n".join(out)


def main() -> None:
    PLOTS.mkdir(parents=True, exist_ok=True)
    if (runs := _read("solomon_runs.csv")) is not None:
        fig_solomon(runs)
    if (inst := _read("x_instances.csv")) is not None:
        fig_x(inst)
    if (inst := _read("hg1000_instances.csv")) is not None:
        fig_hg(inst)
    (SUMMARY / "report_tables.md").write_text(tables(), encoding="utf-8")
    print("wrote results/plots/*.png and results/summary/report_tables.md")


if __name__ == "__main__":
    main()

"""Guarded, resumable experiment runs shared by the rich follow-up studies.

Each job is a tuple ending in its time budget; ``run_fn(job + (cpu,))`` returns
a row dict with t_start / t_end / on_ac. Rows are appended to a JSONL journal
as they finish; a restart resumes, and runs that overlapped a Windows standby
or battery power are redone (experiments.standby_check).
"""

from __future__ import annotations

import datetime as dt
import json
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import psutil

CPUS = [0, 2, 4, 6]


def start_row(**fields) -> dict:
    return fields | {"t_start": time.time()}


def finish_row(row: dict, t0: float) -> dict:
    battery = psutil.sensors_battery()
    return row | {"wall_s": time.perf_counter() - t0, "t_end": time.time(),
                  "on_ac": battery is None or battery.power_plugged}


def pin(cpu: int) -> None:
    psutil.Process().cpu_affinity([cpu])
    from experiments.run_benchmark import wait_for_ac

    wait_for_ac()


def load_journal(journal: Path, key: list[str]) -> pd.DataFrame:
    if not journal.exists():
        return pd.DataFrame(columns=key)
    rows = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines() if line]
    return pd.DataFrame(rows).drop_duplicates(key, keep="last").reset_index(drop=True)


def contaminated(df: pd.DataFrame, since: dt.datetime) -> pd.Series:
    from experiments.standby_check import standby_intervals

    intervals = standby_intervals(since)
    hit = df.apply(lambda r: any(a <= r.t_end and r.t_start - 5 <= b for a, b in intervals), axis=1)
    return hit | ~df.on_ac.astype(bool)


def run_guarded(jobs: list[tuple], run_fn: Callable, journal: Path, key: list[str],
                budget_index: int = -1) -> pd.DataFrame:
    """Run every job not yet cleanly recorded; return the journal rows of ``jobs``."""
    journal.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(4):
        df = load_journal(journal, key)
        good = set()
        if len(df):
            since = dt.datetime.fromtimestamp(df.t_start.min() - 60).astimezone()
            bad = contaminated(df, since)
            good = {tuple(r) for r in df[~bad][key].itertuples(index=False)}
            print(f"pass {attempt + 1}: {len(df)} recorded, {int(bad.sum())} hit standby/battery",
                  flush=True)
        todo = [j for j in jobs if tuple(j[:len(key)]) not in good]
        if not todo:
            break
        print(f"pass {attempt + 1}: running {len(todo)} of {len(jobs)}", flush=True)
        todo.sort(key=lambda j: -j[budget_index])
        tagged = [j + (CPUS[i % len(CPUS)],) for i, j in enumerate(todo)]
        with ProcessPoolExecutor(len(CPUS)) as pool, open(journal, "a", encoding="utf-8") as fh:
            futures = [pool.submit(run_fn, t) for t in tagged]
            for n, fut in enumerate(as_completed(futures), start=1):
                fh.write(json.dumps(fut.result(), default=str) + "\n")
                fh.flush()
                if n % 10 == 0 or n == len(futures):
                    print(f"{n}/{len(futures)} runs", flush=True)
    df = load_journal(journal, key)
    wanted = {tuple(j[:len(key)]) for j in jobs}
    return df[[tuple(r) in wanted for r in df[key].itertuples(index=False)]].reset_index(drop=True)

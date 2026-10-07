"""Find benchmark runs contaminated by system standby or battery power.

    python -m experiments.standby_check wait-ac
    python -m experiments.standby_check window --since 2026-10-01T16:30:00
    python -m experiments.standby_check runs --since 2026-10-01T16:30:00 [--delete] EXP...

Windows Modern Standby (Kernel-Power events 506 enter / 507 exit) pauses
desktop processes mid-solve, which corrupts both timings and time-limited
results; battery power changes CPU behaviour (plan §3). A run is flagged when
its [end - process_wall, end] interval overlaps a standby period, or when it
recorded ``on_ac == False``. With --delete the flagged result files are
removed so a resumed run_benchmark redoes exactly those runs. Prints the
number of flagged runs on the last line.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "results" / "raw"
MARGIN_S = 5.0


def standby_intervals(since: dt.datetime) -> list[tuple[float, float]]:
    """(enter, exit) epoch seconds of Modern Standby periods since ``since``."""
    if sys.platform != "win32":
        return []
    local = since.astimezone().replace(tzinfo=None)  # PowerShell [datetime] = local time
    ps = (
        "Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-Kernel-Power';"
        f" Id=506,507; StartTime=[datetime]'{local.isoformat(timespec='seconds')}'}}"
        " -ErrorAction SilentlyContinue | Sort-Object TimeCreated"
        " | ForEach-Object { \"$($_.Id) $(([DateTimeOffset]$_.TimeCreated).ToUnixTimeMilliseconds())\" }"
    )
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                         capture_output=True, text=True, timeout=60).stdout
    intervals, entered = [], None
    events = [tuple(map(int, ln.split())) for ln in out.strip().splitlines() if ln.strip()]
    for k, (event_id, ms) in enumerate(events):
        t = ms / 1000.0
        if event_id == 506:
            entered = t
        elif event_id == 507:
            # An exit with no entry in the window: standby began before
            # `since`, so the interval covers the window's start.
            start = entered if entered is not None else (since.timestamp() if k == 0 else None)
            if start is not None:
                intervals.append((start, t))
            entered = None
    if entered is not None:  # still in standby (cannot happen while we run)
        intervals.append((entered, float("inf")))
    return intervals


def flagged_runs(experiments: list[str], since: dt.datetime) -> list[tuple[Path, str]]:
    intervals = standby_intervals(since)
    since_ts = since.timestamp()
    out = []
    for exp in experiments:
        for f in (RAW / exp).glob("*/*/*.json"):
            end = f.stat().st_mtime
            if end < since_ts:
                continue
            run = json.loads(f.read_text(encoding="utf-8")).get("run", {})
            start = end - (run.get("process_wall_s") or 0) - MARGIN_S
            if run.get("on_ac") is False:
                out.append((f, "battery"))
            elif any(a <= end and start <= b for a, b in intervals):
                out.append((f, "standby"))
    return out


def on_ac() -> bool:
    import psutil

    battery = psutil.sensors_battery()
    return battery is None or battery.power_plugged


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("wait-ac", help="block until on AC power")
    win = sub.add_parser("window", help="print 1 if standby or battery since --since, else 0")
    win.add_argument("--since", required=True)
    runs = sub.add_parser("runs", help="list (and --delete) contaminated benchmark runs")
    runs.add_argument("experiments", nargs="+")
    runs.add_argument("--since", required=True, help="ISO local time; older files are ignored")
    runs.add_argument("--delete", action="store_true")
    args = ap.parse_args()

    if args.cmd == "wait-ac":
        if not on_ac():
            print("waiting for AC power ...", flush=True)
            while not on_ac():
                time.sleep(15)
            print("on AC power", flush=True)
        return

    since = dt.datetime.fromisoformat(args.since)
    if since.tzinfo is None:
        since = since.astimezone()
    if args.cmd == "window":
        print(int(bool(standby_intervals(since)) or not on_ac()))
        return
    flagged = flagged_runs(args.experiments, since)
    for f, why in flagged:
        print(f"{why}: {f.relative_to(RAW)}")
        if args.delete:
            f.unlink()
    print(len(flagged))


if __name__ == "__main__":
    main()

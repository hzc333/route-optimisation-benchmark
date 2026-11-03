"""Find benchmark runs contaminated by system standby or battery power.

    python -m experiments.standby_check wait-ac
    python -m experiments.standby_check window --since 2026-10-01T16:30:00
    python -m experiments.standby_check runs --since 2026-10-01T16:30:00 [--delete] EXP...

Windows Modern Standby (Kernel-Power events 506 enter / 507 exit) and Linux
suspend (kernel "PM: suspend entry / exit" in the systemd journal) pause
processes mid-solve, which corrupts both timings and time-limited results;
battery power changes CPU behaviour (plan §3). A run is flagged when
its [end - process_wall, end] interval overlaps a standby period, or when it
recorded ``on_ac == False``. With --delete the flagged result files are
removed so a resumed run_benchmark redoes exactly those runs. Prints the
number of flagged runs on the last line.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "results" / "raw"
MARGIN_S = 5.0


def standby_intervals(since: dt.datetime) -> list[tuple[float, float]]:
    """(enter, exit) epoch seconds of standby / suspend periods since ``since``
    (Windows: Modern Standby events; Linux: kernel suspend and hibernation
    messages in the systemd journal; elsewhere none)."""
    if sys.platform == "win32":
        return pair_events(_windows_events(since), since)
    if sys.platform.startswith("linux"):
        return pair_events(_linux_events(since), since)
    return []


def _windows_events(since: dt.datetime) -> list[tuple[bool, float]]:
    local = since.astimezone().replace(tzinfo=None)  # PowerShell [datetime] = local time
    ps = (
        "Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-Kernel-Power';"
        f" Id=506,507; StartTime=[datetime]'{local.isoformat(timespec='seconds')}'}}"
        " -ErrorAction SilentlyContinue | Sort-Object TimeCreated"
        " | ForEach-Object { \"$($_.Id) $(([DateTimeOffset]$_.TimeCreated).ToUnixTimeMilliseconds())\" }"
    )
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                         capture_output=True, text=True, timeout=60).stdout
    events = [tuple(map(int, ln.split())) for ln in out.strip().splitlines() if ln.strip()]
    return [(event_id == 506, ms / 1000.0) for event_id, ms in events if event_id in (506, 507)]


# Kernel messages around s2idle / deep suspend and hibernation.
LINUX_PM = re.compile(r"^PM: (suspend|hibernation) (entry|exit)\b")


def _linux_events(since: dt.datetime) -> list[tuple[bool, float]]:
    try:
        res = subprocess.run(
            ["journalctl", "_TRANSPORT=kernel", f"--since=@{int(since.timestamp())}",
             "--grep=^PM: (suspend|hibernation) (entry|exit)", "--output=json",
             "--output-fields=MESSAGE", "--no-pager"],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"standby_check: cannot read the journal ({exc}); suspends go undetected",
              file=sys.stderr)
        return []
    # Without journal access (groups adm / systemd-journal) kernel messages
    # are silently missing; journalctl says so on stderr.
    if "not seeing messages" in res.stderr:
        print("standby_check: no access to system journal messages (join group adm or"
              " systemd-journal); suspends go undetected", file=sys.stderr)
    return parse_journal(res.stdout)


def parse_journal(out: str) -> list[tuple[bool, float]]:
    """journalctl --output=json lines -> (is_entry, epoch seconds), in order.

    The kernel logs an exit even when suspending fails, so an entry without
    the next event being its exit in the same boot means the machine died
    while suspended (e.g. flat battery). No process survives that, so the
    entry is dropped rather than read as a standby that never ends."""
    raw = []
    for line in out.splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        m = LINUX_PM.match(rec.get("MESSAGE") or "")
        if m:
            raw.append((int(rec["__REALTIME_TIMESTAMP"]) / 1e6, m.group(2) == "entry",
                        rec.get("_BOOT_ID")))
    raw.sort(key=lambda e: e[0])
    events = []
    for k, (t, is_entry, boot) in enumerate(raw):
        nxt = raw[k + 1] if k + 1 < len(raw) else None
        if is_entry and (nxt is None or nxt[1] or nxt[2] != boot):
            continue
        events.append((is_entry, t))
    return events


def pair_events(events: list[tuple[bool, float]], since: dt.datetime) -> list[tuple[float, float]]:
    """(is_entry, t) events in time order -> (enter, exit) intervals."""
    intervals, entered = [], None
    for k, (is_entry, t) in enumerate(events):
        if is_entry:
            entered = t
        else:
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

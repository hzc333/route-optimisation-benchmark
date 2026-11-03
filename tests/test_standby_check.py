"""Standby / suspend detection: Linux journal parsing and interval pairing
(synthetic journal lines, so it runs on any OS)."""

import datetime as dt
import json

from experiments.standby_check import pair_events, parse_journal

SINCE = dt.datetime.fromtimestamp(1_000).astimezone()


def _line(t_s, message, boot="b1"):
    return json.dumps({"__REALTIME_TIMESTAMP": str(int(t_s * 1e6)), "MESSAGE": message,
                       "_BOOT_ID": boot})


def test_suspend_and_hibernation_pairs():
    out = "\n".join([
        _line(2_000, "PM: suspend entry (s2idle)"),
        _line(2_600, "PM: suspend exit"),
        _line(5_000, "PM: hibernation entry"),
        _line(9_000, "PM: hibernation exit"),
        _line(9_500, "PM: suspend devices took 0.120 seconds"),  # not an entry / exit
    ])
    assert pair_events(parse_journal(out), SINCE) == [(2_000, 2_600), (5_000, 9_000)]


def test_exit_without_entry_starts_at_window():
    out = _line(1_500, "PM: suspend exit")
    assert pair_events(parse_journal(out), SINCE) == [(SINCE.timestamp(), 1_500)]


def test_entry_without_exit_is_dropped():
    """A machine that died while suspended must not flag every later run."""
    out = "\n".join([
        _line(2_000, "PM: suspend entry (s2idle)", boot="b1"),   # battery died
        _line(3_000, "PM: suspend entry (deep)", boot="b2"),
        _line(3_100, "PM: suspend exit", boot="b2"),
        _line(4_000, "PM: suspend entry (s2idle)", boot="b2"),   # last event, never resumed
    ])
    assert pair_events(parse_journal(out), SINCE) == [(3_000, 3_100)]


def test_windows_style_events_pair_the_same_way():
    events = [(True, 2_000.0), (False, 2_100.0), (True, 3_000.0)]
    assert pair_events(events, SINCE) == [(2_000.0, 2_100.0), (3_000.0, float("inf"))]

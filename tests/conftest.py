import os
from pathlib import Path

import pytest

# Tests check semantics, not speed: skip Timefold's JIT warm-up solve.
os.environ.setdefault("ROB_TIMEFOLD_WARMUP_S", "0")

TIMEFOLD_JAR = Path(os.environ.get(
    "ROB_TIMEFOLD_JAR",
    Path(__file__).resolve().parents[1] / "adapters" / "timefold_java" / "target" / "timefold-adapter.jar"))


def pytest_collection_modifyitems(config, items):
    """Without the Timefold jar (built with Java, not kept in git) skip the
    tests that run Timefold instead of failing them."""
    if TIMEFOLD_JAR.exists():
        return
    skip = pytest.mark.skip(reason="Timefold jar not built: see README, 'Timefold needs JDK 21 and Maven'")
    for item in items:
        if "timefold" in item.nodeid.lower():
            item.add_marker(skip)

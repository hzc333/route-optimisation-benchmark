import os

# Tests check semantics, not speed: skip Timefold's JIT warm-up solve.
os.environ.setdefault("ROB_TIMEFOLD_WARMUP_S", "0")

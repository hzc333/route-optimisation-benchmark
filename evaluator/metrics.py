"""Benchmark metrics: BKS gap and multi-seed summary statistics (plan §7)."""

from __future__ import annotations

import statistics
from collections.abc import Sequence


def gap_to_bks(cost: float, bks: float) -> float:
    """Percentage gap (cost - BKS) / BKS * 100. Costs must use the BKS's units."""
    if bks <= 0:
        raise ValueError("BKS must be positive")
    return (cost - bks) / bks * 100.0


def seed_summary(values: Sequence[float]) -> dict[str, float]:
    """mean / median / best / worst / std over seeds (minimisation)."""
    if not values:
        raise ValueError("no values")
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "best": min(values),
        "worst": max(values),
        "std": statistics.stdev(values) if len(values) > 1 else 0.0,
    }

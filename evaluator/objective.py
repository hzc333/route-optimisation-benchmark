"""Common objective vector (plan §15).

Every solver's result is re-scored here; native objectives are recorded for
reference only. Rich-instance comparisons use ``lex_key``: hard violations,
then unserved jobs per priority class (most important first), then one soft
cost term.
"""

from __future__ import annotations

from schema.models import PRIORITY_ORDER, Problem

from .validate import ValidationReport

UNSERVED_FIELDS = tuple(f"unserved_{c.value.lower()}" for c in PRIORITY_ORDER)


def objective_vector(problem: Problem, report: ValidationReport) -> dict[str, int]:
    jobs = problem.job_by_id()
    vehicles = problem.vehicle_by_id()
    used = [r for r in report.routes if r.job_ids]

    vec: dict[str, int] = {"hard_violations": len(report.violations)}
    for cls, fname in zip(PRIORITY_ORDER, UNSERVED_FIELDS):
        vec[fname] = sum(jobs[j].priority_class is cls for j in report.unserved)
    vec.update(
        distance=sum(r.distance for r in used),
        travel_time=sum(r.travel_time for r in used),
        # Route duration under the earliest-start schedule (depart at shift
        # start), so it includes waiting. Round 1 does not optimise departure.
        duration=sum(r.duration for r in used),
        vehicles_used=len(used),
        fixed_cost=sum(vehicles[r.vehicle_id].fixed_cost for r in used),
        lateness=sum(r.lateness for r in used),
        overtime=sum(r.overtime for r in used),
    )
    return vec


def lex_key(vec: dict[str, int], soft: str = "distance") -> tuple[int, ...]:
    """Smaller is better, compared strictly left to right."""
    return (vec["hard_violations"], *(vec[f] for f in UNSERVED_FIELDS), vec[soft])

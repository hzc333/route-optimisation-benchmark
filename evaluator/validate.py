"""Solver-independent solution validator (plan §3, §7).

The validator never trusts solver-reported times or loads: it re-simulates
every route from the problem data using the earliest-start schedule
(depart at shift start, wait if early, serve, drive on). Any violation makes
the solution infeasible; infeasible solutions are excluded from quality
comparisons.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from schema.models import Problem, Solution, SolverStatus


@dataclass(frozen=True)
class Violation:
    kind: str
    detail: str
    vehicle_id: str | None = None
    job_id: str | None = None


@dataclass
class RouteStats:
    vehicle_id: str
    job_ids: list[str]
    distance: int = 0
    travel_time: int = 0
    start: int = 0
    end: int = 0
    load: int = 0
    lateness: int = 0
    overtime: int = 0
    service_starts: list[int] = field(default_factory=list)

    @property
    def duration(self) -> int:
        return self.end - self.start


@dataclass
class ValidationReport:
    violations: list[Violation]
    routes: list[RouteStats]
    served: set[str]
    unserved: set[str]

    @property
    def feasible(self) -> bool:
        return not self.violations


def _simulate(problem: Problem, vehicle, job_ids, jobs) -> tuple[RouteStats, list[Violation]]:
    dist, dur, depot = problem.distance_matrix, problem.duration_matrix, problem.depot
    stats = RouteStats(vehicle.id, list(job_ids), start=vehicle.shift[0])
    out: list[Violation] = []

    t, prev = vehicle.shift[0], depot
    for jid in job_ids:
        job = jobs[jid]
        stats.distance += dist[prev][job.location]
        stats.travel_time += dur[prev][job.location]
        t += dur[prev][job.location]
        if job.time_window:
            open_, close = job.time_window
            t = max(t, open_)
            if t > close:
                stats.lateness += t - close
                out.append(Violation(
                    "TIME_WINDOW", f"service starts {t} > window end {close}",
                    vehicle.id, jid))
        stats.service_starts.append(t)
        t += job.service
        stats.load += job.demand
        if job.skills and not set(job.skills) <= set(vehicle.skills):
            out.append(Violation(
                "SKILL", f"needs {job.skills}, vehicle has {vehicle.skills}",
                vehicle.id, jid))
        prev = job.location

    stats.distance += dist[prev][depot]
    stats.travel_time += dur[prev][depot]
    t += dur[prev][depot]
    stats.end = t

    if stats.load > vehicle.capacity:
        out.append(Violation(
            "CAPACITY", f"load {stats.load} > capacity {vehicle.capacity}", vehicle.id))
    if t > vehicle.shift[1]:
        stats.overtime = t - vehicle.shift[1]
        out.append(Violation(
            "SHIFT_END", f"returns at {t} > shift end {vehicle.shift[1]}", vehicle.id))
    return stats, out


def validate(problem: Problem, solution: Solution) -> ValidationReport:
    jobs = problem.job_by_id()
    vehicles = problem.vehicle_by_id()
    violations: list[Violation] = []
    routes: list[RouteStats] = []

    if solution.status is not SolverStatus.SOLVED:
        violations.append(Violation("NO_SOLUTION", f"solver status {solution.status.value}"))
        return ValidationReport(violations, [], set(), set(jobs))

    if solution.problem_name != problem.name:
        violations.append(Violation(
            "PROBLEM_MISMATCH", f"{solution.problem_name!r} != {problem.name!r}"))

    vehicle_uses = Counter(r.vehicle_id for r in solution.routes)
    for vid, n in vehicle_uses.items():
        if vid not in vehicles:
            violations.append(Violation("UNKNOWN_VEHICLE", f"vehicle {vid!r}", vid))
        elif n > 1:
            violations.append(Violation("DUPLICATE_VEHICLE", f"used by {n} routes", vid))

    visits = Counter(jid for r in solution.routes for jid in r.job_ids)
    for jid, n in visits.items():
        if jid not in jobs:
            violations.append(Violation("UNKNOWN_JOB", f"job {jid!r}", job_id=jid))
        elif n > 1:
            violations.append(Violation("DUPLICATE_JOB", f"visited {n} times", job_id=jid))

    for route in solution.routes:
        if not route.job_ids or route.vehicle_id not in vehicles:
            continue
        known = [j for j in route.job_ids if j in jobs]
        stats, route_violations = _simulate(problem, vehicles[route.vehicle_id], known, jobs)
        routes.append(stats)
        violations.extend(route_violations)

    served = {j for j in visits if j in jobs}
    unserved = set(jobs) - served
    for jid in sorted(unserved):
        if jobs[jid].required:
            violations.append(Violation("UNSERVED_REQUIRED", "required job not served", job_id=jid))

    reported = set(solution.unserved)
    if reported != unserved:
        violations.append(Violation(
            "UNSERVED_MISMATCH",
            f"reported-only {sorted(reported - unserved)}, "
            f"missing {sorted(unserved - reported)}"))

    return ValidationReport(violations, routes, served, unserved)

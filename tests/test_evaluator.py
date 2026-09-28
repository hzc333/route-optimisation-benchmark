"""Validator / objective tests on a hand-computable instance.

Layout (1-D, distance == duration):

    depot=0 ---10--- A ---10--- B ---10--- C
    loc 0            1          2          3
"""

import pytest
from pydantic import ValidationError

from evaluator import gap_to_bks, lex_key, objective_vector, seed_summary, validate
from schema.models import Job, Location, PriorityClass, Problem, Route, Solution, SolverStatus, Vehicle

POS = [0, 10, 20, 30]
M = [[abs(a - b) for b in POS] for a in POS]


def make_problem(**job_overrides) -> Problem:
    jobs = {
        "A": dict(location=1, demand=4, service=5, time_window=(0, 100)),
        "B": dict(location=2, demand=4, service=5, time_window=(40, 60)),
        "C": dict(location=3, demand=4, service=5, time_window=(0, 1000)),
    }
    for jid, extra in job_overrides.items():
        jobs[jid].update(extra)
    return Problem(
        name="line",
        locations=[Location(id=f"L{i}") for i in range(4)],
        depot=0,
        vehicles=[
            Vehicle(id="v0", capacity=10, shift=(0, 200), skills=[1]),
            Vehicle(id="v1", capacity=10, shift=(0, 200), fixed_cost=50),
        ],
        jobs=[Job(id=k, **v) for k, v in jobs.items()],
        distance_matrix=M,
        duration_matrix=M,
    )


def sol(routes, unserved=(), status=SolverStatus.SOLVED, name="line") -> Solution:
    return Solution(
        problem_name=name, solver="test", solver_version="0", status=status,
        routes=[Route(vehicle_id=v, job_ids=list(js)) for v, js in routes],
        unserved=list(unserved),
    )


def kinds(report):
    return sorted(v.kind for v in report.violations)


def test_feasible_solution_schedule_and_objective():
    p = make_problem()
    rep = validate(p, sol([("v0", ["A", "B"]), ("v1", ["C"])]))
    assert rep.feasible, rep.violations

    r0, r1 = rep.routes
    # v0: arrive A@10 serve->15, arrive B@25 wait to 40 serve->45, back @65.
    assert r0.service_starts == [10, 40]
    assert (r0.distance, r0.travel_time, r0.end, r0.load) == (40, 40, 65, 8)
    # v1: C@30 serve->35, back @65.
    assert (r1.distance, r1.end) == (60, 65)

    vec = objective_vector(p, rep)
    assert vec == {
        "hard_violations": 0,
        "unserved_critical": 0, "unserved_high": 0, "unserved_normal": 0, "unserved_low": 0,
        "distance": 100, "travel_time": 100, "duration": 130,
        "vehicles_used": 2, "fixed_cost": 50, "lateness": 0, "overtime": 0,
    }


def test_capacity_violation():
    rep = validate(make_problem(), sol([("v0", ["A", "B", "C"])]))
    assert kinds(rep) == ["CAPACITY"]


def test_time_window_violation_records_lateness():
    # C first: C@30 serve->35, B@45 fine, A@55 fine -> make B close at 20 instead.
    p = make_problem(B={"time_window": (0, 20)})
    rep = validate(p, sol([("v0", ["C", "B"]), ("v1", ["A"])]))
    assert kinds(rep) == ["TIME_WINDOW"]
    assert rep.routes[0].lateness == 45 - 20
    assert objective_vector(p, rep)["lateness"] == 25


def test_shift_end_violation():
    p = make_problem()
    p.vehicles[0].shift = (0, 60)
    rep = validate(p, sol([("v0", ["A", "B"]), ("v1", ["C"])]))
    assert kinds(rep) == ["SHIFT_END"]
    assert rep.routes[0].overtime == 5


def test_skill_violation():
    p = make_problem(C={"skills": [1]})
    rep = validate(p, sol([("v0", ["A", "B"]), ("v1", ["C"])]))
    assert kinds(rep) == ["SKILL"]
    assert validate(p, sol([("v1", ["A", "B"]), ("v0", ["C"])])).feasible


def test_structural_violations():
    p = make_problem()
    rep = validate(p, sol([("v0", ["A", "A"]), ("v0", ["B"]), ("vX", ["C"]), ("v1", ["Z"])]))
    assert kinds(rep) == ["DUPLICATE_JOB", "DUPLICATE_VEHICLE", "UNKNOWN_JOB", "UNKNOWN_VEHICLE"]


def test_unserved_required_and_mismatch():
    p = make_problem()
    rep = validate(p, sol([("v0", ["A", "B"])]))          # C missing, not reported
    assert kinds(rep) == ["UNSERVED_MISMATCH", "UNSERVED_REQUIRED"]
    rep = validate(p, sol([("v0", ["A", "B"])], unserved=["C"]))
    assert kinds(rep) == ["UNSERVED_REQUIRED"]


def test_optional_unserved_counted_by_class():
    p = make_problem(
        B={"required": False, "priority_class": PriorityClass.HIGH},
        C={"required": False, "priority_class": PriorityClass.LOW},
    )
    rep = validate(p, sol([("v0", ["A"])], unserved=["B", "C"]))
    assert rep.feasible
    vec = objective_vector(p, rep)
    assert (vec["unserved_high"], vec["unserved_low"], vec["unserved_normal"]) == (1, 1, 0)
    assert vec["vehicles_used"] == 1


def test_no_solution_status():
    rep = validate(make_problem(), sol([], status=SolverStatus.NO_SOLUTION))
    assert kinds(rep) == ["NO_SOLUTION"]
    assert rep.unserved == {"A", "B", "C"}


def test_problem_name_mismatch():
    rep = validate(make_problem(), sol([("v0", ["A", "B"]), ("v1", ["C"])], name="other"))
    assert kinds(rep) == ["PROBLEM_MISMATCH"]


def test_lex_key_one_high_beats_many_normal():
    base = {"hard_violations": 0, "unserved_critical": 0, "distance": 0}
    one_high = {**base, "unserved_high": 1, "unserved_normal": 0, "unserved_low": 0}
    many_normal = {**base, "unserved_high": 0, "unserved_normal": 20, "unserved_low": 0,
                   "distance": 10**9}
    assert lex_key(many_normal) < lex_key(one_high)


@pytest.mark.parametrize("mutate, msg", [
    (lambda d: d["distance_matrix"].pop(), "distance_matrix"),
    (lambda d: d["jobs"].append({**d["jobs"][0]}), "duplicate job"),
    (lambda d: d["jobs"][0].update(location=0), "at the depot"),
    (lambda d: d["jobs"][0].update(time_window=(9, 1)), "window start > end"),
])
def test_problem_rejects_inconsistent_input(mutate, msg):
    data = make_problem().model_dump()
    mutate(data)
    with pytest.raises(ValidationError, match=msg):
        Problem.model_validate(data)


def test_metrics():
    assert gap_to_bks(101.0, 100.0) == pytest.approx(1.0)
    s = seed_summary([3, 1, 2])
    assert (s["best"], s["worst"], s["median"], s["mean"]) == (1, 3, 2, 2)
    assert s["std"] == pytest.approx(1.0)

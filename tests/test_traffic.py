"""Traffic model and experiment plumbing (Q3)."""

import re

import numpy as np
import pytest

from adapters import get_adapter
from schema.models import Route, Solution, SolverStatus
from traffic.evaluate import simulate
from traffic.instances import build
from traffic.model import TDModel
from traffic.strategies import STRATEGIES


@pytest.fixture(scope="module")
def instance():
    return build(0, "H")


def test_fifo_and_free_flow_at_night(instance):
    _, td = instance
    rng = np.random.default_rng(0)
    for i, j in rng.integers(1, 101, size=(30, 2)):
        times = range(6 * 3600, 20 * 3600, 300)
        arrivals = [t + td.travel_time(int(i), int(j), t) for t in times]
        assert all(b >= a for a, b in zip(arrivals, arrivals[1:])), "FIFO violated"
        assert td.travel_time(int(i), int(j), 3 * 3600) == td.freeflow()[i, j]


def test_peak_is_slower_than_free_flow(instance):
    _, td = instance
    assert td.peak_matrix().sum() > 1.5 * td.freeflow().sum()


def test_json_round_trip(instance):
    _, td = instance
    back = TDModel.from_json(td.to_json())
    assert back.travel_time(0, 5, 8 * 3600) == td.travel_time(0, 5, 8 * 3600)


def test_simulate_flags_late_arrival(instance):
    problem, td = instance
    job = next(j for j in problem.jobs if j.time_window)
    late = problem.model_copy(update={"jobs": [
        j.model_copy(update={"time_window": (0, 1)}) if j.id == job.id else j
        for j in problem.jobs]})
    routes = [Route(vehicle_id=problem.vehicles[0].id, job_ids=[job.id])]
    sol = Solution(problem_name=problem.name, solver="t", solver_version="0",
                   status=SolverStatus.SOLVED, routes=routes)
    r = simulate(late, td, sol)
    assert r["late_jobs"] == 1 and not r["on_time"] and r["unserved"] == len(problem.jobs) - 1


def test_timefold_td_search_matches_python_model(instance):
    """Java TravelTime and Python TDModel must agree to the second."""
    problem, td = instance
    sol, _ = STRATEGIES["td_search"](get_adapter("timefold"), problem, td, time_limit_s=2,
                                     seed=0, construction="default")
    soft_cost = -int(re.search(r"/(-?\d+)\]soft", sol.notes).group(1))
    assert soft_cost == simulate(problem, td, sol)["travel_time_s"]


def test_bucket_expansion_is_conservative(instance):
    from traffic.bucketed import expand

    problem, td = instance
    exp = expand(problem, td, 5400)
    s0, s1 = problem.vehicles[0].shift
    assert all(len(g) >= 1 for g in exp.groups)
    rng = np.random.default_rng(0)
    for c in rng.integers(0, len(exp.copies), size=40):
        cp = exp.copies[c]
        job = problem.jobs[cp.job_index]
        a, b = job.time_window or (s0, s1)
        assert a <= cp.lo <= cp.hi <= b
        # Leg cost covers every departure the copy allows (random check).
        for t in rng.integers(cp.lo + job.service, cp.hi + job.service + 1, size=5):
            for d in rng.integers(0, len(exp.copies), size=5):
                dest = problem.jobs[exp.copies[d].job_index].location
                assert td.travel_time(job.location, dest, int(t)) <= exp.matrix[c + 1, d + 1]


@pytest.mark.parametrize("solver", ["pyvrp", "ortools"])
def test_bucketed_plan_on_time_under_td(instance, solver):
    problem, td = instance
    sol, extra = STRATEGIES["bucketed_90"](get_adapter(solver), problem, td, time_limit_s=3, seed=0)
    r = simulate(problem, td, sol, min_start=extra["min_start"])
    assert r["valid"] and r["on_time"], r


def test_td_search_rejects_static_solvers(instance):
    problem, td = instance
    with pytest.raises(ValueError, match="TD search needs Timefold"):
        STRATEGIES["td_search"](get_adapter("pyvrp"), problem, td, time_limit_s=1, seed=0)

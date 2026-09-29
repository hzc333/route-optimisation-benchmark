"""Strict-priority strategy tests (plan §14)."""

import pytest

from adapters import ADAPTERS, get_adapter
from evaluator import objective_vector, validate
from experiments.run_priority_tests import CASES, PRIO_FIELDS, case_p1, random_instance
from priority import STRATEGIES, cost_upper_bound, stacked_penalties
from schema.models import PRIORITY_ORDER


def prio_vector(problem, solution):
    rep = validate(problem, solution)
    vec = objective_vector(problem, rep)
    return tuple(vec[f] for f in PRIO_FIELDS)


def test_stacked_penalties_dominate_lower_classes():
    p = random_instance(0)
    pens = stacked_penalties(p)
    ub = cost_upper_bound(p)
    lower_total = ub
    for cls in reversed(PRIORITY_ORDER):
        assert pens[cls] >= lower_total  # beats soft cost + every lower drop
        lower_total += pens[cls] * sum(
            j.value for j in p.jobs if not j.required and j.priority_class is cls)


def test_stacked_penalties_overflow_guard():
    p = random_instance(0)
    big = p.model_copy(update={"jobs": [j.model_copy(update={"value": 10**6}) for j in p.jobs]})
    with pytest.raises(OverflowError):
        stacked_penalties(big)


@pytest.mark.parametrize("solver", ADAPTERS)
@pytest.mark.parametrize("strategy", ["stacked", "sequential"])
@pytest.mark.parametrize("case", CASES, ids=lambda c: c.__name__)
def test_strict_strategies_meet_expected_vector(solver, strategy, case):
    problem, expected = case()
    sol = STRATEGIES[strategy](get_adapter(solver), problem, time_limit_s=1, seed=0)
    assert prio_vector(problem, sol) == expected


@pytest.mark.parametrize("solver", ADAPTERS)
def test_weighted_10x_fails_high_vs_many_normal(solver):
    """Documents the counterexample: 10x spacing gives up the HIGH job."""
    problem, expected = case_p1()
    sol = STRATEGIES["weighted"](get_adapter(solver), problem, time_limit_s=0.5, seed=0)
    got = prio_vector(problem, sol)
    assert got != expected and got[2] == 1  # unserved_high == 1

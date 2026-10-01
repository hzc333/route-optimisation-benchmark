"""Strict-priority strategy tests (plan §14)."""

import pytest

from adapters import ADAPTERS, get_adapter
from evaluator import objective_vector, validate
from experiments.run_priority_tests import CASES, PRIO_FIELDS, case_p1, random_instance
from priority import STRATEGIES, cost_upper_bound, stacked_penalties
from schema.models import PRIORITY_ORDER

# Strategies drive the solver through drop penalties (and warm starts).
PENALTY_ADAPTERS = [a for a in ADAPTERS
                    if not {"drop_penalty", "warm_start"} & get_adapter(a).UNSUPPORTED]


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


@pytest.mark.parametrize("solver", PENALTY_ADAPTERS)
@pytest.mark.parametrize("strategy", ["stacked", "sequential"])
@pytest.mark.parametrize("case", CASES, ids=lambda c: c.__name__)
def test_strict_strategies_meet_expected_vector(solver, strategy, case):
    problem, expected = case()
    sol = STRATEGIES[strategy](get_adapter(solver), problem, time_limit_s=1, seed=0)
    assert prio_vector(problem, sol) == expected


@pytest.mark.parametrize("solver", PENALTY_ADAPTERS)
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_sequential_feasible_on_tight_random(solver, seed):
    """Warm-started stages must keep the locked (tight) packing feasible."""
    problem = random_instance(seed, "adversarial")
    sol = STRATEGIES["sequential"](get_adapter(solver), problem, time_limit_s=1, seed=0)
    rep = validate(problem, sol)
    assert rep.feasible, (sol.notes, rep.violations[:3])


def test_vroom_native_priority_is_a_weighted_sum():
    """VROOM maximises the *sum* of 0-100 priorities: 20 NORMAL (1 each) beat
    1 HIGH (10) in P1, but serving everything servable passes P2 and P4."""
    vroom = get_adapter("vroom")
    for case, strict in ((CASES[0], False), (CASES[1], True), (CASES[3], True)):
        problem, expected = case()
        got = prio_vector(problem, STRATEGIES["native"](vroom, problem, time_limit_s=0.5))
        assert (got == expected) is strict, (problem.name, got)


# Timefold is excluded: its weighted objective also prefers dropping the HIGH
# job, but its construction heuristic inserts the bulky HIGH job first and
# local search does not find the "remove 1, insert 20" move, so it ends at the
# strict answer by accident. The priority experiment reports that behaviour.
@pytest.mark.parametrize("solver", ["ortools", "pyvrp"])
def test_weighted_10x_fails_high_vs_many_normal(solver):
    """Documents the counterexample: 10x spacing gives up the HIGH job."""
    problem, expected = case_p1()
    sol = STRATEGIES["weighted"](get_adapter(solver), problem, time_limit_s=0.5, seed=0)
    got = prio_vector(problem, sol)
    assert got != expected and got[2] == 1  # unserved_high == 1

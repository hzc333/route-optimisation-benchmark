"""Adapter contract tests: every adapter must return solutions that pass the
shared validator, and must map optional/priority/skills semantics correctly."""

import pytest

from adapters import ADAPTERS, UnsupportedFeature, get_adapter
from data.generate_smoke import smoke_cvrp, smoke_vrptw
from evaluator import objective_vector, validate
from schema.models import Job, Location, PriorityClass, Problem, Vehicle


def square_problem(**kw) -> Problem:
    """Depot (0,0); clients (0,10) (0,20) (10,0) (20,0), cap 2 -> optimum 80."""
    pts = [(0, 0), (0, 10), (0, 20), (10, 0), (20, 0)]
    m = [[round(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5) for b in pts] for a in pts]
    return Problem(
        name="square",
        locations=[Location(id=str(i), x=x, y=y) for i, (x, y) in enumerate(pts)],
        depot=0,
        vehicles=kw.get("vehicles") or [Vehicle(id=f"v{k}", capacity=2) for k in range(2)],
        jobs=kw.get("jobs") or [Job(id=f"c{i}", location=i, demand=1) for i in range(1, 5)],
        distance_matrix=m,
        duration_matrix=m,
    )


@pytest.fixture(params=ADAPTERS)
def adapter(request):
    return get_adapter(request.param)


@pytest.mark.parametrize("seed", [0, 3])
def test_known_optimum(adapter, seed):
    p = square_problem()
    s = adapter.solve(p, time_limit_s=0.5, seed=seed)
    rep = validate(p, s)
    assert rep.feasible, rep.violations
    assert objective_vector(p, rep)["distance"] == 80
    assert s.solver == adapter.NAME and s.seed == seed


@pytest.mark.parametrize("factory", [smoke_cvrp, smoke_vrptw])
def test_smoke_instances_feasible(adapter, factory):
    p = factory()
    s = adapter.solve(p, time_limit_s=1, seed=0)
    rep = validate(p, s)
    assert rep.feasible, rep.violations
    assert not rep.unserved
    assert s.wall_runtime_s >= s.solver_runtime_s > 0


def _far_optional_problem(cls) -> Problem:
    pts = [0, 10, 1000]
    m = [[abs(a - b) for b in pts] for a in pts]
    return Problem(
        name="drop", locations=[Location(id=str(i)) for i in range(3)], depot=0,
        vehicles=[Vehicle(id="v0", capacity=10)],
        jobs=[Job(id="near", location=1, demand=1),
              Job(id="far", location=2, demand=1, required=False, priority_class=cls)],
        distance_matrix=m, duration_matrix=m)


def test_optional_far_job_dropped_by_class(adapter):
    """A LOW job 1000 away is dropped; the same job as CRITICAL is served."""
    if "drop_penalty" in adapter.UNSUPPORTED:
        pytest.skip(f"{adapter.NAME}: no drop penalty")
    pts = [0, 10, 1000]
    m = [[abs(a - b) for b in pts] for a in pts]

    def prob(cls):
        return Problem(
            name="drop", locations=[Location(id=str(i)) for i in range(3)], depot=0,
            vehicles=[Vehicle(id="v0", capacity=10)],
            jobs=[Job(id="near", location=1, demand=1),
                  Job(id="far", location=2, demand=1, required=False, priority_class=cls)],
            distance_matrix=m, duration_matrix=m)

    penalties = {PriorityClass.CRITICAL: 10_000, PriorityClass.HIGH: 1000,
                 PriorityClass.NORMAL: 100, PriorityClass.LOW: 10}
    for cls, dropped in ((PriorityClass.LOW, True), (PriorityClass.CRITICAL, False)):
        p = prob(cls)
        rep = validate(p, adapter.solve(p, time_limit_s=0.5, penalties=penalties))
        assert rep.feasible, rep.violations
        assert (rep.unserved == {"far"}) is dropped


@pytest.mark.parametrize("factory", [smoke_cvrp, smoke_vrptw])
def test_timefold_score_matches_validator(factory):
    """The Java model's cost level must equal the validator's distance (+fixed):
    guards against the two implementations drifting apart."""
    import re

    p = factory()
    s = get_adapter("timefold").solve(p, time_limit_s=1)
    rep = validate(p, s)
    assert rep.feasible, rep.violations
    vec = objective_vector(p, rep)
    hard, *soft = map(int, re.findall(r"-?\d+", re.search(r"score=(\S+)", s.notes).group(1)))
    assert hard == 0 and soft[:4] == [0, 0, 0, 0]
    assert -soft[4] == vec["distance"] + vec["fixed_cost"]


def test_vroom_serves_every_servable_job():
    """VROOM maximises assigned jobs before cost: even a far LOW job is served."""
    p = _far_optional_problem(PriorityClass.LOW)
    rep = validate(p, get_adapter("vroom").solve(p, time_limit_s=0.5))
    assert rep.feasible and not rep.unserved


def test_time_windows_force_order(adapter):
    """c1 must be served before c3 even though c3-first is not worse by distance."""
    jobs = [Job(id="c1", location=1, demand=1, time_window=(0, 10)),
            Job(id="c3", location=3, demand=1, time_window=(50, 60))]
    vehicles = [Vehicle(id="v0", capacity=2, shift=(0, 200))]
    p = square_problem(jobs=jobs, vehicles=vehicles)
    s = adapter.solve(p, time_limit_s=0.5)
    rep = validate(p, s)
    assert rep.feasible, rep.violations
    assert s.routes[0].job_ids == ["c1", "c3"]


def test_skills(adapter):
    jobs = [Job(id="c1", location=1, demand=1, skills=[7]),
            Job(id="c2", location=2, demand=1)]
    vehicles = [Vehicle(id="plain", capacity=2), Vehicle(id="cool", capacity=2, skills=[7])]
    p = square_problem(jobs=jobs, vehicles=vehicles)
    if "skills" in adapter.UNSUPPORTED:
        with pytest.raises(UnsupportedFeature, match="skills"):
            adapter.solve(p, time_limit_s=0.5)
        return
    s = adapter.solve(p, time_limit_s=0.5)
    rep = validate(p, s)
    assert rep.feasible, rep.violations
    assert any(r.vehicle_id == "cool" and "c1" in r.job_ids for r in s.routes)


@pytest.mark.parametrize("required", [True, False])
def test_skill_nobody_has(adapter, required):
    """No vehicle has skill 9. Optional -> dropped. Required -> infeasible either
    way: OR-Tools returns no solution, VROOM leaves it unassigned, Timefold
    takes a skill mismatch. Guards against OR-Tools treating an empty
    allowed-set as 'all vehicles'."""
    if "skills" in adapter.UNSUPPORTED:
        pytest.skip(f"{adapter.NAME}: no skills")
    jobs = [Job(id="c1", location=1, demand=1, skills=[9], required=required),
            Job(id="c2", location=2, demand=1)]
    p = square_problem(jobs=jobs)
    s = adapter.solve(p, time_limit_s=0.5)
    rep = validate(p, s)
    if not required:
        assert rep.feasible and rep.unserved == {"c1"}
    elif adapter.NAME == "ortools":
        assert s.status == "NO_SOLUTION"
    else:
        # Every option breaks a hard rule: VROOM leaves it unassigned, Timefold
        # takes the cheaper hard violation (skill mismatch). Never "feasible".
        kinds = {v.kind for v in rep.violations}
        assert not rep.feasible and kinds <= {"UNSERVED_REQUIRED", "SKILL"}


def test_warm_start_from_feasible_routes(adapter):
    """A feasible (suboptimal) start is accepted and improved, never worsened."""
    p = square_problem()
    start = [("v0", ["c1", "c3"]), ("v1", ["c2", "c4"])]  # crosses quadrants: 2*(10+14+10)+...
    if "warm_start" in adapter.UNSUPPORTED:
        with pytest.raises(UnsupportedFeature):
            adapter.solve(p, time_limit_s=0.5, initial_routes=start)
        return
    s = adapter.solve(p, time_limit_s=0.5, initial_routes=start)
    rep = validate(p, s)
    assert rep.feasible, rep.violations
    assert objective_vector(p, rep)["distance"] == 80
    assert "warm=rejected" not in s.notes


def test_ortools_search_params_hook():
    """Tuning hook: ILS with a SISR ruin strategy must be valid (an empty ruin
    list makes OR-Tools reject the parameters as ROUTING_INVALID)."""
    from experiments.tuning import _ruin

    p = square_problem()
    s = get_adapter("ortools").solve(p, time_limit_s=0.5, search_params=_ruin("sisr"))
    assert "ROUTING_INVALID" not in s.notes
    assert validate(p, s).feasible


def test_pyvrp_solve_params_hook():
    p = square_problem()
    pyvrp = get_adapter("pyvrp")
    s = pyvrp.solve(p, time_limit_s=0.5, solve_params={"num_neighbours": 3, "history_length": 50})
    assert objective_vector(p, validate(p, s))["distance"] == 80
    with pytest.raises(ValueError, match="unknown PyVRP solve_params"):
        pyvrp.solve(p, time_limit_s=0.5, solve_params={"bogus": 1})


def test_huge_fixed_cost_stays_feasible(adapter):
    """Required load needs 2 vehicles with fixed cost 1e6 each. PyVRP's default
    penalty cap (1e5/unit) would make an overloaded single route 'cheaper'."""
    vehicles = [Vehicle(id=f"v{k}", capacity=3, fixed_cost=1_000_000) for k in range(2)]
    p = square_problem(vehicles=vehicles)
    rep = validate(p, adapter.solve(p, time_limit_s=0.5))
    assert rep.feasible, rep.violations
    assert objective_vector(p, rep)["vehicles_used"] == 2


@pytest.mark.parametrize("fixed_cost, expected_vehicles", [(0, 2), (1000, 1)])
def test_fixed_cost_trades_distance_for_vehicles(adapter, fixed_cost, expected_vehicles):
    """Non-metric matrix: a<->b costs 100, so two out-and-back routes (40) beat
    one tour (120) unless each vehicle carries a large fixed cost."""
    m = [[0, 10, 10], [10, 0, 100], [10, 100, 0]]
    p = Problem(
        name="fixed", locations=[Location(id=str(i)) for i in range(3)], depot=0,
        vehicles=[Vehicle(id=f"v{k}", capacity=2, fixed_cost=fixed_cost) for k in range(2)],
        jobs=[Job(id="a", location=1, demand=1), Job(id="b", location=2, demand=1)],
        distance_matrix=m, duration_matrix=m)
    rep = validate(p, adapter.solve(p, time_limit_s=0.5))
    assert rep.feasible
    assert objective_vector(p, rep)["vehicles_used"] == expected_vehicles

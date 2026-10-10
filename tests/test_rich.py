"""Rich (Voi-style) schema, validator and solver builders."""

import re

import pytest

from rich import ortools_rich, pyvrp_rich
from rich.common import WEIGHTED_PRIZE, insert_rest
from rich.model import (Break, Group, Hub, Job, Profile, RestPlan, RichProblem, RichRoute,
                        RichSolution, Shipment, Step, Vehicle, Visit)
from rich.priority import STRATEGIES
from rich.validate import simulate_route, validate
from rich.voi import ZERO_EMISSION, build, in_zone
from schema.models import Location, PriorityClass

C = PriorityClass


def _line(n=6, step=100):
    """Locations on a line, 100 m / 100 s apart; 0 and 1 are hubs."""
    d = [[abs(i - j) * step for j in range(n)] for i in range(n)]
    return [Location(id=f"l{i}", x=float(i), y=0.0) for i in range(n)], {
        "van": Profile(distance_matrix=d, duration_matrix=d)}


def tiny(**veh) -> RichProblem:
    locs, profiles = _line()
    v = dict(id="v", profile="van", capacity=[2, 2, 1], start_hub="H0", end_hub="H0",
             reload_hubs=["H1"], max_reloads=1, shift=(0, 10_000), duration_cost=1)
    v.update(veh)
    return RichProblem(
        name="tiny", dims=["c", "d", "s"], locations=locs, profiles=profiles,
        hubs=[Hub(id="H0", location=0, service=10), Hub(id="H1", location=1, service=10)],
        vehicles=[Vehicle(**v)],
        jobs=[Job(id=f"j{k}", location=k, service=5, delivery=[1, 0, 0], pickup=[0, 1, 0])
              for k in (2, 3, 4)],
        shipments=[Shipment(id="s", pickup=Step(location=5), delivery=Step(location=2),
                            amount=[0, 0, 1])],
        soft_late_cost=1)


def route(*visits, **kw):
    return RichRoute(vehicle_id="v", visits=[Visit(kind=k, id=i) for k, i in visits], **kw)


def test_schedule_and_costs():
    p = tiny()
    r = simulate_route(p, route(("job", "j2"), ("job", "j3")))
    # load 10, drive 200, serve 5, drive 100, serve 5, drive 300 back
    assert (r.distance, r.end, dict(r.violations)) == (600, 620, {})
    rep = validate(p, RichSolution(problem_name="tiny", solver="t", routes=[
        route(("job", "j2"), ("job", "j3"))]))
    assert rep.cost_parts["duration"] == 620 and rep.cost_parts["distance"] == 600
    assert rep.unserved["NORMAL"] == 2  # j4 and the shipment, value 1 each


def test_capacity_and_reload():
    p = tiny()
    three = [("job", "j2"), ("job", "j3"), ("job", "j4")]
    assert simulate_route(p, route(*three)).violations["capacity"] >= 1
    ok = simulate_route(p, route(("job", "j2"), ("job", "j3"), ("reload", "H1"), ("job", "j4")))
    assert not ok.violations and ok.reloads == 1
    bad = simulate_route(p, route(("job", "j2"), ("reload", "H0"), ("job", "j3")))
    assert bad.violations["reload_hub"] == 1


def test_shipment_rules():
    p = tiny()
    ok = simulate_route(p, route(("pickup", "s"), ("delivery", "s")))
    assert not ok.violations
    rev = simulate_route(p, route(("delivery", "s"), ("pickup", "s")))
    assert rev.violations["shipment_order"] >= 1
    # Shipments stay on board across a reload.
    across = simulate_route(p, route(("pickup", "s"), ("reload", "H1"), ("delivery", "s")))
    assert not across.violations
    no_room = tiny(capacity=[2, 2, 0])
    assert simulate_route(no_room, route(("pickup", "s"), ("delivery", "s"))).violations["capacity"]


def test_windows_skills_soft_due_groups():
    p = tiny()
    jobs = {j.id: j for j in p.jobs}
    jobs["j2"] = jobs["j2"].model_copy(update={"time_window": (0, 100), "skills": [ZERO_EMISSION]})
    jobs["j3"] = jobs["j3"].model_copy(update={"soft_due": 250, "group": "g"})
    jobs["j4"] = jobs["j4"].model_copy(update={"group": "g"})
    q = p.model_copy(update={"jobs": list(jobs.values()), "groups": [Group(id="g", k=1)]})
    r = simulate_route(q, route(("job", "j2"), ("job", "j3")))
    assert r.violations["time_window"] == 1 and r.violations["skills"] == 1
    assert r.soft_late_s == 315 - 250
    rep = validate(q, RichSolution(problem_name="tiny", solver="t", routes=[
        route(("job", "j3"), ("job", "j4"))]))
    assert rep.violations["group_k"] == 1


def test_break_rules():
    p = tiny(rest=Break(earliest=100, latest=300, duration=50))
    assert simulate_route(p, route(("job", "j2"))).violations["break_missing"] == 1
    # Break at 150 splits the drive to j3: arrival = max(215 + 100, 150) + 50.
    r = simulate_route(p, route(("job", "j2"), ("job", "j3"),
                                rest=RestPlan(position=1, start=150)))
    assert r.violations["break_before_ready"] == 1
    r = simulate_route(p, route(("job", "j2"), ("job", "j3"),
                                rest=RestPlan(position=1, start=215)))
    assert not r.violations and r.service_starts["job:j3"] == 365
    fixed = insert_rest(p, route(("job", "j2"), ("job", "j3")))
    assert not simulate_route(p, fixed).violations


def test_required_and_duplicates():
    p = tiny()
    req = p.model_copy(update={"shipments": [p.shipments[0].model_copy(update={"required": True})]})
    rep = validate(req, RichSolution(problem_name="tiny", solver="t", routes=[
        route(("job", "j2"), ("job", "j2"))]))
    assert rep.violations["required_unserved"] == 1 and rep.violations["duplicate_visit"] == 1


def test_voi_generator():
    a, b = build("S", 3), build("S", 3)
    assert a == b and build("S", 4) != a
    for j in a.jobs:
        loc = a.locations[j.location]
        assert (ZERO_EMISSION in j.skills) == in_zone((loc.y, loc.x))
    assert {v.profile for v in a.vehicles} == {"van", "bike"}
    assert any(not v.skills for v in a.vehicles)  # a diesel van


@pytest.fixture(scope="module")
def voi():
    return build("S", 1)


def _unserved_prize(problem, report):
    return sum(WEIGHTED_PRIZE[c] * report.unserved[c.value] for c in C)


def test_ortools_objective_matches_validator(voi):
    sol = ortools_rich.solve(voi, time_limit_s=3, prizes=WEIGHTED_PRIZE)
    rep = validate(voi, sol)
    assert rep.feasible, rep.violations
    native = int(re.search(r"objective=(\d+)", sol.notes).group(1))
    assert native == rep.soft_cost + _unserved_prize(voi, rep)


def test_pyvrp_cost_matches_validator(voi):
    """Without breaks, soft deadlines and groups the PyVRP model is exact."""
    plain = voi.model_copy(update={
        "vehicles": [v.model_copy(update={"rest": None}) for v in voi.vehicles],
        "jobs": [j.model_copy(update={"soft_due": None, "group": None}) for j in voi.jobs],
        "groups": []})
    sol = pyvrp_rich.solve(plain, time_limit_s=3, prizes=WEIGHTED_PRIZE)
    rep = validate(plain, sol)
    assert rep.feasible, rep.violations
    native = int(re.search(r"pyvrp_cost=(\d+)", sol.notes).group(1))
    assert native == rep.soft_cost + _unserved_prize(plain, rep)


def test_pyvrp_workarounds_hold(voi):
    sol = pyvrp_rich.solve(voi, time_limit_s=3, prizes=WEIGHTED_PRIZE)
    rep = validate(voi, sol)
    assert not {"skills", "group_k", "break_window", "break_missing"} & set(rep.violations)


@pytest.mark.parametrize("solver", [pyvrp_rich, ortools_rich])
def test_sequential_serves_critical_and_high(voi, solver):
    sol = STRATEGIES["sequential_full"](solver, voi, time_limit_s=8, seed=0)
    rep = validate(voi, sol)
    assert rep.feasible, rep.violations
    assert rep.unserved["CRITICAL"] == 0 and rep.unserved["HIGH"] == 0

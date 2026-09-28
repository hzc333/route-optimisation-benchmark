"""Checks on versioned artefacts: JSON Schema files and smoke instances."""

import math
from pathlib import Path

import pytest

from data.generate_smoke import OUT as SMOKE_DIR
from data.generate_smoke import smoke_cvrp, smoke_vrptw
from evaluator import validate
from schema.export_json_schema import HERE as SCHEMA_DIR
from schema.export_json_schema import TARGETS, render
from schema.models import Problem, Route, Solution, SolverStatus


@pytest.mark.parametrize("fname", TARGETS)
def test_json_schema_files_in_sync(fname):
    on_disk = (SCHEMA_DIR / fname).read_text(encoding="utf-8")
    assert on_disk == render(TARGETS[fname]), "run: python -m schema.export_json_schema"


@pytest.mark.parametrize("factory", [smoke_cvrp, smoke_vrptw])
def test_smoke_files_match_generator(factory):
    problem = factory()
    on_disk = Problem.model_validate_json((SMOKE_DIR / f"{problem.name}.json").read_text())
    assert on_disk == problem, "run: python -m data.generate_smoke"


def _singleton_solution(problem: Problem) -> Solution:
    routes = [Route(vehicle_id=v.id, job_ids=[j.id]) for v, j in zip(problem.vehicles, problem.jobs)]
    return Solution(problem_name=problem.name, solver="singleton", solver_version="0",
                    status=SolverStatus.SOLVED, routes=routes)


def test_vrptw_smoke_feasible_by_construction():
    p = smoke_vrptw()
    rep = validate(p, _singleton_solution(p))
    assert rep.feasible, rep.violations


def test_cvrp_smoke_fleet_sufficient():
    p = smoke_cvrp()
    total = sum(j.demand for j in p.jobs)
    assert len(p.vehicles) >= math.ceil(total / p.vehicles[0].capacity)
    assert all(j.demand <= p.vehicles[0].capacity for j in p.jobs)
    # Distance matrix symmetric with zero diagonal.
    m = p.distance_matrix
    assert all(m[i][i] == 0 and m[i][j] == m[j][i] for i in range(len(m)) for j in range(len(m)))

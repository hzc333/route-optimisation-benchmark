"""End-to-end check of converter + validator + rounding convention: every BKS
solution must be feasible on our converted instance and reproduce the BKS
cost exactly. Skipped when data/raw has not been downloaded."""

import pytest

from data.convert import FAMILIES, RAW, convert, instance_names, load_bks, parse_solution
from evaluator import objective_vector, validate
from schema.models import Route, Solution

CASES = [(f, n) for f in FAMILIES for n in instance_names(f)] if RAW.exists() else []


@pytest.mark.skipif(not CASES, reason="run: python -m data.download")
@pytest.mark.parametrize("family, name", CASES, ids=[n for _, n in CASES])
def test_bks_reproduced_exactly(family, name):
    problem = convert(family, name)
    routes, _ = parse_solution(RAW / family / f"{name}.sol")
    assert len(routes) <= len(problem.vehicles), "fleet smaller than BKS route count"
    sol = Solution(
        problem_name=name, solver="bks", solver_version="-", status="SOLVED",
        routes=[Route(vehicle_id=f"v{k}", job_ids=[str(c) for c in r]) for k, r in enumerate(routes)])
    rep = validate(problem, sol)
    assert rep.feasible, rep.violations[:5]
    assert objective_vector(problem, rep)["distance"] == int(load_bks()[name]["bks_scaled"])

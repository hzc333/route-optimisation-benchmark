"""Toolchain smoke tests: both solvers import at the pinned versions and solve a
tiny CVRP to the known optimum. These do not use the shared schema yet; they
only prove the environment is sane before adapters are written.
"""

from importlib import metadata

import pytest

# 1 depot + 4 clients on a line / square; capacity forces 2 routes.
#   depot (0,0); clients (0,10) (0,20) (10,0) (20,0), demand 1 each, cap 2.
# Optimal: 0-1-2-0 and 0-3-4-0, each length 10+10+20 = 40 -> total 80.
COORDS = [(0, 0), (0, 10), (0, 20), (10, 0), (20, 0)]
DEMANDS = [0, 1, 1, 1, 1]
CAPACITY = 2
NUM_VEHICLES = 2
OPTIMUM = 80


def _dist(a, b):
    return round(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5)


MATRIX = [[_dist(a, b) for b in COORDS] for a in COORDS]


def test_pinned_versions():
    assert metadata.version("ortools") == "9.15.6755"
    assert metadata.version("pyvrp") == "0.14.0"
    assert metadata.version("pyvroom") == "1.15.2"


def test_ortools_solves_tiny_cvrp():
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    manager = pywrapcp.RoutingIndexManager(len(MATRIX), NUM_VEHICLES, 0)
    routing = pywrapcp.RoutingModel(manager)

    def dist_cb(i, j):
        return MATRIX[manager.IndexToNode(i)][manager.IndexToNode(j)]

    transit = routing.RegisterTransitCallback(dist_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(transit)

    def demand_cb(i):
        return DEMANDS[manager.IndexToNode(i)]

    demand = routing.RegisterUnaryTransitCallback(demand_cb)
    routing.AddDimensionWithVehicleCapacity(
        demand, 0, [CAPACITY] * NUM_VEHICLES, True, "Capacity"
    )

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    params.time_limit.seconds = 1

    solution = routing.SolveWithParameters(params)
    assert solution is not None
    assert solution.ObjectiveValue() == OPTIMUM


def test_pyvrp_solves_tiny_cvrp():
    from pyvrp import Model
    from pyvrp.stop import MaxRuntime

    m = Model()
    m.add_vehicle_type(num_available=NUM_VEHICLES, capacity=CAPACITY)
    # 0.14 API: edges connect Locations; depots/clients sit on a Location.
    locs = [m.add_location(x=x, y=y) for x, y in COORDS]
    m.add_depot(locs[0])
    for loc, d in zip(locs[1:], DEMANDS[1:]):
        m.add_client(loc, delivery=d)
    for i, a in enumerate(locs):
        for j, b in enumerate(locs):
            m.add_edge(a, b, distance=MATRIX[i][j])

    res = m.solve(stop=MaxRuntime(1), seed=0, display=False)
    assert res.is_feasible()
    assert res.cost() == pytest.approx(OPTIMUM)

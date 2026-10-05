"""Score a plan under time-dependent ("real") traffic.

Same schedule rule as evaluator.validate (leave the depot at shift start,
wait if early, serve, drive on) but every leg uses TDModel.travel_time at the
actual departure time. A plan that was feasible on its planning matrix can
arrive late here - that is what the traffic experiment measures.
"""

from __future__ import annotations

from schema.models import Problem, Solution

from .model import TDModel


def simulate(problem: Problem, td: TDModel, solution: Solution,
             planning_matrix=None) -> dict:
    jobs = problem.job_by_id()
    vehicles = problem.vehicle_by_id()
    out = {"travel_time_s": 0, "lateness_s": 0, "late_jobs": 0, "overtime_s": 0,
           "late_routes": 0, "vehicles_used": 0, "distance_m": 0, "planned_travel_s": 0}
    for route in solution.routes:
        if not route.job_ids:
            continue
        veh = vehicles[route.vehicle_id]
        out["vehicles_used"] += 1
        t, prev, route_late = veh.shift[0], problem.depot, False
        for jid in route.job_ids:
            job = jobs[jid]
            leg = td.travel_time(prev, job.location, t)
            out["travel_time_s"] += leg
            out["distance_m"] += problem.distance_matrix[prev][job.location]
            if planning_matrix is not None:
                out["planned_travel_s"] += int(planning_matrix[prev][job.location])
            t += leg
            if job.time_window:
                t = max(t, job.time_window[0])
                if t > job.time_window[1]:
                    out["lateness_s"] += t - job.time_window[1]
                    out["late_jobs"] += 1
                    route_late = True
            t += job.service
            prev = job.location
        leg = td.travel_time(prev, problem.depot, t)
        out["travel_time_s"] += leg
        out["distance_m"] += problem.distance_matrix[prev][problem.depot]
        if planning_matrix is not None:
            out["planned_travel_s"] += int(planning_matrix[prev][problem.depot])
        t += leg
        if t > veh.shift[1]:
            out["overtime_s"] += t - veh.shift[1]
            route_late = True
        out["late_routes"] += route_late
        load = sum(jobs[j].demand for j in route.job_ids)
        out["capacity_excess"] = out.get("capacity_excess", 0) + max(0, load - veh.capacity)
    served = [j for r in solution.routes for j in r.job_ids]
    out["unserved"] = len(set(jobs) - set(served))
    out["duplicates"] = len(served) - len(set(served))
    out.setdefault("capacity_excess", 0)
    out["on_time"] = out["late_jobs"] == 0 and out["overtime_s"] == 0
    out["valid"] = out["unserved"] == 0 and out["duplicates"] == 0 and out["capacity_excess"] == 0
    return out


def departure_times(problem: Problem, td: TDModel, solution: Solution) -> dict[int, int]:
    """Location -> time the vehicle leaves it under TD traffic (for T2)."""
    jobs = problem.job_by_id()
    vehicles = problem.vehicle_by_id()
    dep: dict[int, int] = {}
    for route in solution.routes:
        veh = vehicles[route.vehicle_id]
        t, prev = veh.shift[0], problem.depot
        for jid in route.job_ids:
            job = jobs[jid]
            t += td.travel_time(prev, job.location, t)
            if job.time_window:
                t = max(t, job.time_window[0])
            t += job.service
            dep[job.location] = t
            prev = job.location
    return dep

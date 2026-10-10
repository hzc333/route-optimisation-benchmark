"""Rich problem / solution schema (round 2, plan §5 and tier 5 of §8).

The round-1 schema (schema/models.py) stays frozen for the standard
benchmarks. This one adds what a Voi-style operation needs:

* several load dimensions; a job delivers from the hub and/or picks up back to
  the hub (battery swap: one charged out, one depleted back);
* paired pickup-and-delivery shipments (move a scooter from A to B);
* several hubs, start/end hub per vehicle, reloads at hubs mid-shift;
* routing profiles (van / cargo bike matrices) and skills (e.g. only
  zero-emission vehicles may serve stops inside the environmental zone);
* hard windows, soft "ideally before" deadlines, one driver break per shift;
* "any k of these n" groups.

Units: metres, seconds, integer cost points. Objective (lexicographic):
hard violations, then unserved value per priority class (CRITICAL first),
then soft cost = fixed + distance + duration + soft lateness costs.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, model_validator

from schema.models import Location, PriorityClass

Window = tuple[NonNegativeInt, NonNegativeInt]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Profile(_Strict):
    """Travel matrices of one vehicle class, indexed by location."""
    distance_matrix: list[list[NonNegativeInt]]
    duration_matrix: list[list[NonNegativeInt]]


class Hub(_Strict):
    id: str
    location: NonNegativeInt
    # Load / unload time at the start of every trip from this hub.
    service: NonNegativeInt = 0


class Break(_Strict):
    """One uninterrupted break of ``duration`` starting in [earliest, latest]."""
    earliest: NonNegativeInt
    latest: NonNegativeInt
    duration: NonNegativeInt


class Vehicle(_Strict):
    id: str
    profile: str
    capacity: list[NonNegativeInt]
    start_hub: str
    end_hub: str
    reload_hubs: list[str] = Field(default_factory=list)
    max_reloads: NonNegativeInt = 0
    shift: Window
    fixed_cost: NonNegativeInt = 0
    distance_cost: NonNegativeInt = 1      # per metre
    duration_cost: NonNegativeInt = 0      # per second from route start to end
    skills: list[str] = Field(default_factory=list)
    rest: Break | None = None
    # Load on board at the start that occupies room until the first hub
    # visit (PyVRP semantics); used when re-planning mid-shift.
    initial_load: list[NonNegativeInt] = Field(default_factory=list)


class Job(_Strict):
    id: str
    location: NonNegativeInt
    service: NonNegativeInt = 0
    delivery: list[NonNegativeInt] = Field(default_factory=list)
    pickup: list[NonNegativeInt] = Field(default_factory=list)
    time_window: Window | None = None
    soft_due: NonNegativeInt | None = None   # "ideally start before"
    required: bool = False
    priority_class: PriorityClass = PriorityClass.NORMAL
    value: int = Field(default=1, ge=1)
    skills: list[str] = Field(default_factory=list)
    group: str | None = None


class Step(_Strict):
    location: NonNegativeInt
    service: NonNegativeInt = 0
    time_window: Window | None = None


class Shipment(_Strict):
    id: str
    pickup: Step
    delivery: Step
    amount: list[NonNegativeInt]
    required: bool = False
    priority_class: PriorityClass = PriorityClass.NORMAL
    value: int = Field(default=1, ge=1)
    skills: list[str] = Field(default_factory=list)


class Group(_Strict):
    """Serve at most ``k`` of the member jobs; each missing one (below k)
    costs one member's value in the members' class."""
    id: str
    k: int = Field(ge=1)


class RichProblem(_Strict):
    name: str
    meta: dict[str, Any] = Field(default_factory=dict)
    dims: list[str]
    locations: list[Location]
    profiles: dict[str, Profile]
    hubs: list[Hub]
    vehicles: list[Vehicle]
    jobs: list[Job] = Field(default_factory=list)
    shipments: list[Shipment] = Field(default_factory=list)
    groups: list[Group] = Field(default_factory=list)
    soft_late_cost: NonNegativeInt = 0       # per second after soft_due

    @model_validator(mode="after")
    def _consistent(self) -> RichProblem:
        n, d = len(self.locations), len(self.dims)
        for name, p in self.profiles.items():
            for m in (p.distance_matrix, p.duration_matrix):
                if len(m) != n or any(len(r) != n for r in m):
                    raise ValueError(f"profile {name}: matrices must be {n}x{n}")
        hubs = {h.id for h in self.hubs}
        ids = [j.id for j in self.jobs] + [s.id for s in self.shipments] + list(hubs)
        if len(ids) != len(set(ids)):
            raise ValueError("job, shipment and hub ids must be unique together")
        for v in self.vehicles:
            if v.profile not in self.profiles:
                raise ValueError(f"vehicle {v.id}: unknown profile {v.profile}")
            if len(v.capacity) != d or (v.initial_load and len(v.initial_load) != d):
                raise ValueError(f"vehicle {v.id}: capacity / initial load need {d} dims")
            if {v.start_hub, v.end_hub, *v.reload_hubs} - hubs:
                raise ValueError(f"vehicle {v.id}: unknown hub")
        groups = {g.id: [] for g in self.groups}
        for j in self.jobs:
            for vec in (j.delivery, j.pickup):
                if vec and len(vec) != d:
                    raise ValueError(f"job {j.id}: load vectors need {d} dims")
            if j.group is not None:
                if j.group not in groups:
                    raise ValueError(f"job {j.id}: unknown group {j.group}")
                groups[j.group].append(j)
        for gid, members in groups.items():
            if len({(j.priority_class, j.value) for j in members if not j.required}) > 1:
                raise ValueError(f"group {gid}: optional members need one class and value")
        for s in self.shipments:
            if len(s.amount) != d:
                raise ValueError(f"shipment {s.id}: amount needs {d} dims")
        return self

    # Helpers -------------------------------------------------------------
    def zeros(self) -> list[int]:
        return [0] * len(self.dims)

    def hub(self, hid: str) -> Hub:
        return next(h for h in self.hubs if h.id == hid)

    def group_members(self) -> dict[str, list[Job]]:
        out: dict[str, list[Job]] = {g.id: [] for g in self.groups}
        for j in self.jobs:
            if j.group is not None:
                out[j.group].append(j)
        return out


# Solutions --------------------------------------------------------------

VisitKind = Literal["job", "pickup", "delivery", "reload"]


class Visit(_Strict):
    kind: VisitKind
    id: str          # job / shipment / hub id


class RestPlan(_Strict):
    """Break taken after ``position`` visits (0 = before the first), starting
    at ``start``; it may split the following drive."""
    position: NonNegativeInt
    start: NonNegativeInt


class RichRoute(_Strict):
    vehicle_id: str
    visits: list[Visit]
    start_time: NonNegativeInt | None = None  # default: shift start
    rest: RestPlan | None = None


class RichSolution(_Strict):
    problem_name: str
    solver: str
    status: Literal["SOLVED", "NO_SOLUTION", "ERROR"] = "SOLVED"
    routes: list[RichRoute] = Field(default_factory=list)
    seed: int | None = None
    time_limit_s: float | None = None
    wall_runtime_s: float | None = None
    notes: str = ""

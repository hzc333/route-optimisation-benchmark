"""Shared Problem / Solution schema (plan §5).

These pydantic models are the single source of truth; the JSON Schema files in
this directory are generated from them by ``export_json_schema.py``.

Conventions (all adapters must follow them):

* All distances, durations and times are non-negative integers. Converters
  scale real-valued inputs (e.g. Solomon x10) and record the factor in
  ``Problem.meta``.
* ``duration_matrix[i][j]`` is pure travel time; service time is carried by
  the job and added at the job's location.
* A vehicle leaves the depot no earlier than ``shift[0]`` and must be back at
  the depot no later than ``shift[1]``. Waiting before a time window opens is
  allowed; starting service after it closes is a hard violation.
* Round 1 supports a single depot and a single capacity dimension with
  delivery-only demand. Pickup/delivery, soft windows, etc. come in round 2.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, model_validator

NonNegFloat = Annotated[float, Field(ge=0)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PriorityClass(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"


# Lexicographic order, most important first (plan §14).
PRIORITY_ORDER: tuple[PriorityClass, ...] = (
    PriorityClass.CRITICAL,
    PriorityClass.HIGH,
    PriorityClass.NORMAL,
    PriorityClass.LOW,
)


class Location(_Strict):
    """A row/column of the matrices. Coordinates are informational only."""

    id: str
    x: float | None = None
    y: float | None = None


class Vehicle(_Strict):
    id: str
    capacity: NonNegativeInt
    shift: tuple[NonNegativeInt, NonNegativeInt] = (0, 2**31 - 1)
    fixed_cost: NonNegativeInt = 0
    skills: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def _shift_ordered(self) -> Vehicle:
        if self.shift[0] > self.shift[1]:
            raise ValueError(f"vehicle {self.id}: shift start > end")
        return self


class Job(_Strict):
    id: str
    location: NonNegativeInt
    demand: NonNegativeInt = 0
    service: NonNegativeInt = 0
    time_window: tuple[NonNegativeInt, NonNegativeInt] | None = None
    required: bool = True
    priority_class: PriorityClass = PriorityClass.NORMAL
    skills: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def _window_ordered(self) -> Job:
        if self.time_window and self.time_window[0] > self.time_window[1]:
            raise ValueError(f"job {self.id}: time window start > end")
        return self


class Problem(_Strict):
    name: str
    meta: dict[str, Any] = Field(default_factory=dict)
    locations: list[Location]
    depot: NonNegativeInt
    vehicles: list[Vehicle]
    jobs: list[Job]
    distance_matrix: list[list[NonNegativeInt]]
    duration_matrix: list[list[NonNegativeInt]]

    @model_validator(mode="after")
    def _consistent(self) -> Problem:
        n = len(self.locations)
        for name in ("distance_matrix", "duration_matrix"):
            m = getattr(self, name)
            if len(m) != n or any(len(row) != n for row in m):
                raise ValueError(f"{name} must be {n}x{n}")
        if self.depot >= n:
            raise ValueError("depot index out of range")
        for label, ids in (
            ("location", [x.id for x in self.locations]),
            ("vehicle", [v.id for v in self.vehicles]),
            ("job", [j.id for j in self.jobs]),
        ):
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate {label} ids")
        for job in self.jobs:
            if job.location >= n:
                raise ValueError(f"job {job.id}: location index out of range")
            if job.location == self.depot:
                raise ValueError(f"job {job.id}: located at the depot")
        return self

    def job_by_id(self) -> dict[str, Job]:
        return {j.id: j for j in self.jobs}

    def vehicle_by_id(self) -> dict[str, Vehicle]:
        return {v.id: v for v in self.vehicles}


class SolverStatus(str, Enum):
    SOLVED = "SOLVED"            # solver returned a solution (feasibility checked separately)
    NO_SOLUTION = "NO_SOLUTION"  # solver finished without any solution
    TIMEOUT = "TIMEOUT"          # killed by the runner before returning
    ERROR = "ERROR"              # crash / exception


class Route(_Strict):
    vehicle_id: str
    job_ids: list[str]
    # Optional, as reported by the solver; the validator recomputes its own.
    arrival_times: list[int] | None = None
    loads: list[int] | None = None


class Solution(_Strict):
    problem_name: str
    solver: str
    solver_version: str
    seed: int | None = None
    time_limit_s: NonNegFloat | None = None
    threads: int | None = None
    status: SolverStatus
    routes: list[Route] = Field(default_factory=list)
    unserved: list[str] = Field(default_factory=list)
    solver_runtime_s: NonNegFloat | None = None
    wall_runtime_s: NonNegFloat | None = None
    native_objective: float | None = None
    notes: str = ""

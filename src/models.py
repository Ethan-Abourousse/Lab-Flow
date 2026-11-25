"""Typed data structures shared across LabFlow modules.

This module defines the data contracts used by every other component of the
simulation (data generation, resources, laboratory workflow, scheduling,
KPIs, export). Keeping these definitions in one place avoids duplicated or
inconsistent shapes across modules and makes the simulation's assumptions
explicit and type-checkable.

All time-related fields are expressed in **minutes**, measured from the
start of the simulated observation window (t=0), unless stated otherwise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar, Optional


class Department(str, Enum):
    """Laboratory department a sample is routed to."""

    BIOCHEMISTRY = "biochemistry"
    HEMATOLOGY = "hematology"
    IMMUNOLOGY = "immunology"


class Priority(str, Enum):
    """Clinical urgency assigned to a sample on arrival."""

    ROUTINE = "routine"
    URGENT = "urgent"


class ProcessingStage(str, Enum):
    """Sequential stages of the sample-processing workflow."""

    REGISTRATION = "registration"
    PREPARATION = "preparation"
    CENTRIFUGATION = "centrifugation"
    ANALYSIS = "analysis"
    VALIDATION = "validation"
    REPORTING = "reporting"


@dataclass
class Sample:
    """A single synthetic laboratory sample moving through the workflow."""

    sample_id: str
    arrival_time_minutes: float
    department: Department
    priority: Priority
    requires_centrifugation: bool
    target_turnaround_minutes: float
    requires_reprocessing: bool = False

    @property
    def is_urgent(self) -> bool:
        """Return True if the sample has urgent priority."""
        return self.priority is Priority.URGENT


@dataclass
class ProcessingEvent:
    """A timestamped record of a sample passing through one workflow stage.

    Captures the three timestamps needed to separately compute the waiting
    time (queued before the resource is available) and the service time
    (resource actively occupied) for a given stage.
    """

    sample_id: str
    stage: ProcessingStage
    resource_name: str
    queue_entry_time_minutes: float
    service_start_time_minutes: float
    service_end_time_minutes: float

    @property
    def waiting_time_minutes(self) -> float:
        """Time spent queued before the resource became available."""
        return self.service_start_time_minutes - self.queue_entry_time_minutes

    @property
    def service_time_minutes(self) -> float:
        """Time the resource was actively occupied by the sample."""
        return self.service_end_time_minutes - self.service_start_time_minutes


@dataclass
class LaboratoryResource:
    """Static configuration of a laboratory resource (equipment or staff).

    Describes capacity and processing-time bounds only; the runtime SimPy
    resource object is created from this configuration in
    ``src/resources.py``.
    """

    name: str
    capacity: int
    min_processing_minutes: float
    max_processing_minutes: float
    batch_capacity: Optional[int] = None

    def __post_init__(self) -> None:
        if self.capacity <= 0:
            raise ValueError(f"Resource '{self.name}' must have capacity > 0.")
        if self.min_processing_minutes <= 0 or self.max_processing_minutes <= 0:
            raise ValueError(
                f"Resource '{self.name}' processing times must be strictly positive."
            )
        if self.min_processing_minutes > self.max_processing_minutes:
            raise ValueError(
                f"Resource '{self.name}' min_processing_minutes cannot exceed "
                "max_processing_minutes."
            )


@dataclass
class SimulationConfiguration:
    """All parameters needed to reproduce a single simulation run.

    Instances are typically constructed by loading ``config/baseline.json``
    or ``config/scenarios.json``; no simulation parameter should be
    hardcoded elsewhere in the codebase.

    ``arrival_window_minutes`` and ``max_simulation_minutes`` are
    intentionally distinct: arrivals stop being generated after the former,
    while the simulation keeps running (up to the latter, as a safety cap)
    so that samples already in the pipeline can finish processing.
    """

    scenario_name: str
    random_seed: int
    arrival_window_minutes: float
    max_simulation_minutes: float
    arrival_rate_per_hour: float
    department_mix: dict[Department, float]
    urgent_probability: float
    centrifugation_required: dict[Department, bool]
    target_turnaround_minutes: dict[Priority, float]
    resources: dict[str, LaboratoryResource]
    scheduling_strategy: str = "fifo"
    centrifugation_strategy: str = "fixed_interval"
    centrifugation_batch_wait_threshold_minutes: float = 15.0
    centrifugation_fixed_interval_minutes: float = 20.0
    replications: int = 1
    resource_failures: dict[str, dict] = field(default_factory=dict)

    VALID_SCHEDULING_STRATEGIES: ClassVar[frozenset[str]] = frozenset(
        {"fifo", "priority", "edf"}
    )
    VALID_CENTRIFUGATION_STRATEGIES: ClassVar[frozenset[str]] = frozenset(
        {"fixed_interval", "adaptive"}
    )

    def __post_init__(self) -> None:
        mix_total = sum(self.department_mix.values())
        if not math.isclose(mix_total, 1.0, abs_tol=1e-6):
            raise ValueError(
                f"department_mix proportions must sum to 1.0, got {mix_total}."
            )
        if not 0.0 <= self.urgent_probability <= 1.0:
            raise ValueError("urgent_probability must be between 0.0 and 1.0.")
        if set(self.centrifugation_required) != set(Department):
            raise ValueError(
                "centrifugation_required must define a value for every Department."
            )
        if set(self.target_turnaround_minutes) != set(Priority):
            raise ValueError(
                "target_turnaround_minutes must define a value for every Priority."
            )
        if self.arrival_window_minutes > self.max_simulation_minutes:
            raise ValueError(
                "arrival_window_minutes cannot exceed max_simulation_minutes "
                "(the drain phase must have time to run after arrivals stop)."
            )
        if self.scheduling_strategy not in self.VALID_SCHEDULING_STRATEGIES:
            raise ValueError(
                f"Unknown scheduling_strategy '{self.scheduling_strategy}'. "
                f"Expected one of {sorted(self.VALID_SCHEDULING_STRATEGIES)}."
            )
        if self.centrifugation_strategy not in self.VALID_CENTRIFUGATION_STRATEGIES:
            raise ValueError(
                f"Unknown centrifugation_strategy '{self.centrifugation_strategy}'. "
                f"Expected one of {sorted(self.VALID_CENTRIFUGATION_STRATEGIES)}."
            )


@dataclass
class SimulationResult:
    """Aggregated raw output of a single simulation replication.

    Only raw observations are stored here; derived metrics (mean TAT,
    utilization, etc.) are computed from ``samples`` and ``events`` by
    ``src/kpi.py``, keeping this dataclass a simple, reusable container.
    """

    scenario_name: str
    replication_id: int
    samples: list[Sample] = field(default_factory=list)
    events: list[ProcessingEvent] = field(default_factory=list)

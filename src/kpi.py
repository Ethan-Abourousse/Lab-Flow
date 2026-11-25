"""Key performance indicator (KPI) calculation.

Computes the industrial performance indicators listed in the project
brief from a single :class:`~src.models.SimulationResult`, and aggregates
those indicators (mean + 95% confidence interval) across the multiple
replications required to compare scenarios reliably.

All KPIs are normalized to ``config.max_simulation_minutes`` (the full
configured simulation window: arrivals plus drain time), not just the time
samples happened to finish, so that throughput and utilization stay
comparable across scenarios with different loads or resource mixes.

Queue length and work-in-progress use Little's Law (L = lambda * W) rather
than continuous resource-occupancy sampling, since the discrete
:class:`~src.models.ProcessingEvent` timestamps already give an exact
throughput (lambda) and mean sojourn time (W) per stage and for the system
as a whole.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
from scipy import stats

from src.models import (
    Priority,
    ProcessingEvent,
    ProcessingStage,
    SimulationConfiguration,
    SimulationResult,
)

#: Resource name used for the instantaneous report-transmission stage; it
#: has no real capacity constraint, so it is excluded from stage KPIs.
_NON_RESOURCE_STAGE_NAMES = {"report_transmission"}

#: Percentile used for the "tail" turnaround time KPI.
_P95 = 95


@dataclass
class StageKPIs:
    """Per-resource KPIs: waiting time, utilization, and queue length."""

    resource_name: str
    stage: ProcessingStage
    sample_count: int
    mean_waiting_minutes: float
    utilization: float
    average_queue_length: float


@dataclass
class ScenarioKPIs:
    """All KPIs for a single simulation replication."""

    scenario_name: str
    replication_id: int
    observed_minutes: float
    samples_generated: int
    samples_completed: int
    samples_in_progress: int
    mean_turnaround_minutes: float
    median_turnaround_minutes: float
    p95_turnaround_minutes: float
    mean_urgent_turnaround_minutes: float
    mean_routine_turnaround_minutes: float
    throughput_per_hour: float
    work_in_progress: float
    deadline_compliance_rate: float
    reprocessing_rate: float
    stage_kpis: list[StageKPIs] = field(default_factory=list)


def _distinct_service_intervals(events: list[ProcessingEvent]) -> list[tuple[float, float]]:
    """De-duplicate centrifugation events sharing one batch's timestamps.

    Several samples share identical (service_start, service_end) timestamps
    when they were processed together in one centrifuge batch; utilization
    must count that shared interval once, not once per sample.
    """
    return list({(e.service_start_time_minutes, e.service_end_time_minutes) for e in events})


def _compute_stage_kpis(
    events: list[ProcessingEvent], config: SimulationConfiguration, observed_hours: float
) -> list[StageKPIs]:
    events_by_resource: dict[str, list[ProcessingEvent]] = defaultdict(list)
    for event in events:
        if event.resource_name in _NON_RESOURCE_STAGE_NAMES:
            continue
        events_by_resource[event.resource_name].append(event)

    stage_kpis = []
    for resource_name, resource_events in events_by_resource.items():
        spec = config.resources[resource_name]
        mean_waiting = float(
            np.mean([e.waiting_time_minutes for e in resource_events])
        )

        if resource_name == "centrifugation":
            busy_intervals = _distinct_service_intervals(resource_events)
            busy_minutes = sum(end - start for start, end in busy_intervals)
            throughput_per_hour = len(busy_intervals) / observed_hours
        else:
            busy_minutes = sum(e.service_time_minutes for e in resource_events)
            throughput_per_hour = len(resource_events) / observed_hours

        utilization = busy_minutes / (spec.capacity * observed_hours * 60.0)
        # Little's Law: average number waiting = arrival rate * mean wait.
        average_queue_length = (
            len(resource_events) / observed_hours
        ) * (mean_waiting / 60.0)

        stage_kpis.append(
            StageKPIs(
                resource_name=resource_name,
                stage=resource_events[0].stage,
                sample_count=len(resource_events),
                mean_waiting_minutes=mean_waiting,
                utilization=utilization,
                average_queue_length=average_queue_length,
            )
        )

    return stage_kpis


def compute_kpis(
    result: SimulationResult, config: SimulationConfiguration
) -> ScenarioKPIs:
    """Compute every KPI for one simulation replication."""
    observed_minutes = config.max_simulation_minutes
    observed_hours = observed_minutes / 60.0

    samples_by_id = {s.sample_id: s for s in result.samples}
    completion_time_by_sample: dict[str, float] = {
        e.sample_id: e.service_end_time_minutes
        for e in result.events
        if e.stage == ProcessingStage.REPORTING
    }

    turnaround_by_sample = {
        sample_id: completion_time - samples_by_id[sample_id].arrival_time_minutes
        for sample_id, completion_time in completion_time_by_sample.items()
    }
    turnarounds = list(turnaround_by_sample.values())

    urgent_turnarounds = [
        tat
        for sample_id, tat in turnaround_by_sample.items()
        if samples_by_id[sample_id].priority is Priority.URGENT
    ]
    routine_turnarounds = [
        tat
        for sample_id, tat in turnaround_by_sample.items()
        if samples_by_id[sample_id].priority is Priority.ROUTINE
    ]
    on_time = [
        tat <= samples_by_id[sample_id].target_turnaround_minutes
        for sample_id, tat in turnaround_by_sample.items()
    ]
    reprocessed = [s.requires_reprocessing for s in result.samples]

    samples_completed = len(turnarounds)
    throughput_per_hour = samples_completed / observed_hours
    mean_turnaround_minutes = float(np.mean(turnarounds)) if turnarounds else float("nan")

    return ScenarioKPIs(
        scenario_name=result.scenario_name,
        replication_id=result.replication_id,
        observed_minutes=observed_minutes,
        samples_generated=len(result.samples),
        samples_completed=samples_completed,
        samples_in_progress=len(result.samples) - samples_completed,
        mean_turnaround_minutes=mean_turnaround_minutes,
        median_turnaround_minutes=float(np.median(turnarounds)) if turnarounds else float("nan"),
        p95_turnaround_minutes=(
            float(np.percentile(turnarounds, _P95)) if turnarounds else float("nan")
        ),
        mean_urgent_turnaround_minutes=(
            float(np.mean(urgent_turnarounds)) if urgent_turnarounds else float("nan")
        ),
        mean_routine_turnaround_minutes=(
            float(np.mean(routine_turnarounds)) if routine_turnarounds else float("nan")
        ),
        throughput_per_hour=throughput_per_hour,
        # Little's Law for the whole system: WIP = throughput * mean sojourn time.
        work_in_progress=throughput_per_hour * (mean_turnaround_minutes / 60.0),
        deadline_compliance_rate=float(np.mean(on_time)) if on_time else float("nan"),
        reprocessing_rate=float(np.mean(reprocessed)) if reprocessed else 0.0,
        stage_kpis=_compute_stage_kpis(result.events, config, observed_hours),
    )


#: Scalar KPI fields summarized (mean + 95% CI) across replications.
SCALAR_KPI_FIELDS = [
    "mean_turnaround_minutes",
    "median_turnaround_minutes",
    "p95_turnaround_minutes",
    "mean_urgent_turnaround_minutes",
    "mean_routine_turnaround_minutes",
    "throughput_per_hour",
    "work_in_progress",
    "deadline_compliance_rate",
    "reprocessing_rate",
]


def _mean_and_confidence_interval(values: list[float], confidence: float = 0.95) -> dict:
    """Mean and a two-sided t-distribution confidence interval for ``values``.

    Falls back to a degenerate (zero-width) interval when fewer than two
    finite observations are available (CI is undefined with <2 samples).
    """
    finite_values = [v for v in values if not np.isnan(v)]
    if len(finite_values) < 2:
        mean = float(finite_values[0]) if finite_values else float("nan")
        return {"mean": mean, "ci_low": mean, "ci_high": mean, "n": len(finite_values)}

    mean = float(np.mean(finite_values))
    sem = stats.sem(finite_values)
    margin = sem * stats.t.ppf((1 + confidence) / 2.0, len(finite_values) - 1)
    return {
        "mean": mean,
        "ci_low": mean - margin,
        "ci_high": mean + margin,
        "n": len(finite_values),
    }


def summarize_kpis(kpis_list: list[ScenarioKPIs], confidence: float = 0.95) -> dict:
    """Aggregate scalar KPIs across replications: mean and confidence interval."""
    return {
        field_name: _mean_and_confidence_interval(
            [getattr(kpi, field_name) for kpi in kpis_list], confidence
        )
        for field_name in SCALAR_KPI_FIELDS
    }


def summarize_stage_kpis(kpis_list: list[ScenarioKPIs], confidence: float = 0.95) -> dict:
    """Aggregate per-resource stage KPIs across replications, keyed by resource name."""
    stage_values: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    stage_labels: dict[str, ProcessingStage] = {}

    for kpi in kpis_list:
        for stage_kpi in kpi.stage_kpis:
            stage_labels[stage_kpi.resource_name] = stage_kpi.stage
            stage_values[stage_kpi.resource_name]["mean_waiting_minutes"].append(
                stage_kpi.mean_waiting_minutes
            )
            stage_values[stage_kpi.resource_name]["utilization"].append(
                stage_kpi.utilization
            )
            stage_values[stage_kpi.resource_name]["average_queue_length"].append(
                stage_kpi.average_queue_length
            )

    return {
        resource_name: {
            "stage": stage_labels[resource_name],
            **{
                metric_name: _mean_and_confidence_interval(values, confidence)
                for metric_name, values in metrics.items()
            },
        }
        for resource_name, metrics in stage_values.items()
    }

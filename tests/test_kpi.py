"""Unit tests for src/kpi.py."""

import pytest

from src.kpi import compute_kpis, summarize_kpis, summarize_stage_kpis
from src.models import (
    Department,
    LaboratoryResource,
    Priority,
    ProcessingEvent,
    ProcessingStage,
    Sample,
    SimulationConfiguration,
    SimulationResult,
)


def make_config(max_simulation_minutes: float = 60.0) -> SimulationConfiguration:
    return SimulationConfiguration(
        scenario_name="unit_test",
        random_seed=1,
        arrival_window_minutes=max_simulation_minutes,
        max_simulation_minutes=max_simulation_minutes,
        arrival_rate_per_hour=10.0,
        department_mix={
            Department.BIOCHEMISTRY: 1.0,
            Department.HEMATOLOGY: 0.0,
            Department.IMMUNOLOGY: 0.0,
        },
        urgent_probability=0.1,
        centrifugation_required={
            Department.BIOCHEMISTRY: True,
            Department.HEMATOLOGY: False,
            Department.IMMUNOLOGY: True,
        },
        target_turnaround_minutes={Priority.ROUTINE: 240.0, Priority.URGENT: 60.0},
        resources={
            "registration": LaboratoryResource("registration", 1, 1.0, 3.0),
            "centrifugation": LaboratoryResource(
                "centrifugation", 1, 10.0, 15.0, batch_capacity=8
            ),
        },
    )


def make_sample(sample_id, priority, target_turnaround, requires_reprocessing=False) -> Sample:
    return Sample(
        sample_id=sample_id,
        arrival_time_minutes=0.0,
        department=Department.BIOCHEMISTRY,
        priority=priority,
        requires_centrifugation=True,
        target_turnaround_minutes=target_turnaround,
        requires_reprocessing=requires_reprocessing,
    )


def make_result() -> SimulationResult:
    samples = [
        make_sample("A", Priority.ROUTINE, target_turnaround=100.0),
        make_sample("B", Priority.URGENT, target_turnaround=50.0),
        make_sample("C", Priority.ROUTINE, target_turnaround=10.0, requires_reprocessing=True),
    ]

    registration_events = [
        ProcessingEvent("A", ProcessingStage.REGISTRATION, "registration", 0.0, 0.0, 5.0),
        ProcessingEvent("B", ProcessingStage.REGISTRATION, "registration", 0.0, 5.0, 8.0),
        ProcessingEvent("C", ProcessingStage.REGISTRATION, "registration", 0.0, 8.0, 10.0),
    ]
    # All three samples share one centrifuge batch: identical service window.
    centrifugation_events = [
        ProcessingEvent(sid, ProcessingStage.CENTRIFUGATION, "centrifugation", 10.0, 15.0, 25.0)
        for sid in ("A", "B", "C")
    ]
    reporting_events = [
        ProcessingEvent(sid, ProcessingStage.REPORTING, "report_transmission", 25.0, 25.0, 25.0)
        for sid in ("A", "B", "C")
    ]

    return SimulationResult(
        scenario_name="unit_test",
        replication_id=0,
        samples=samples,
        events=registration_events + centrifugation_events + reporting_events,
    )


def test_compute_kpis_turnaround_statistics():
    config = make_config()
    kpis = compute_kpis(make_result(), config)

    assert kpis.samples_generated == 3
    assert kpis.samples_completed == 3
    assert kpis.samples_in_progress == 0
    assert kpis.mean_turnaround_minutes == pytest.approx(25.0)
    assert kpis.median_turnaround_minutes == pytest.approx(25.0)
    assert kpis.p95_turnaround_minutes == pytest.approx(25.0)
    assert kpis.mean_urgent_turnaround_minutes == pytest.approx(25.0)
    assert kpis.mean_routine_turnaround_minutes == pytest.approx(25.0)


def test_compute_kpis_deadline_compliance_and_reprocessing():
    config = make_config()
    kpis = compute_kpis(make_result(), config)

    # A (target 100) and B (target 50) meet their deadline; C (target 10) misses it.
    assert kpis.deadline_compliance_rate == pytest.approx(2.0 / 3.0)
    assert kpis.reprocessing_rate == pytest.approx(1.0 / 3.0)


def test_compute_kpis_throughput_and_wip_use_full_observation_window():
    config = make_config(max_simulation_minutes=60.0)
    kpis = compute_kpis(make_result(), config)

    assert kpis.observed_minutes == pytest.approx(60.0)
    assert kpis.throughput_per_hour == pytest.approx(3.0)  # 3 completions / 1 hour
    # Little's Law: WIP = throughput (per hour) * mean turnaround (in hours).
    assert kpis.work_in_progress == pytest.approx(3.0 * (25.0 / 60.0))


def test_compute_kpis_deduplicates_shared_batch_for_centrifugation_utilization():
    config = make_config()
    kpis = compute_kpis(make_result(), config)

    stage_by_resource = {s.resource_name: s for s in kpis.stage_kpis}
    centrifugation = stage_by_resource["centrifugation"]

    # Only one 10-minute batch occurred, shared by 3 samples: busy time must
    # be counted once (10 min), not 3x (30 min).
    assert centrifugation.utilization == pytest.approx(10.0 / (1 * 60.0))
    assert centrifugation.sample_count == 3


def test_compute_kpis_registration_utilization_and_waiting_time():
    config = make_config()
    kpis = compute_kpis(make_result(), config)

    stage_by_resource = {s.resource_name: s for s in kpis.stage_kpis}
    registration = stage_by_resource["registration"]

    # Service times: 5 + 3 + 2 = 10 minutes of a 1-unit, 60-minute window.
    assert registration.utilization == pytest.approx(10.0 / (1 * 60.0))
    # Waits of 0, 5, 8 minutes (queued at t=0, served at t=0/5/8) -> mean 4.333.
    assert registration.mean_waiting_minutes == pytest.approx(13.0 / 3.0)


def test_compute_kpis_excludes_report_transmission_from_stage_kpis():
    config = make_config()
    kpis = compute_kpis(make_result(), config)

    resource_names = {s.resource_name for s in kpis.stage_kpis}
    assert "report_transmission" not in resource_names


def test_summarize_kpis_collapses_to_mean_for_identical_replications():
    config = make_config()
    kpis_list = [compute_kpis(make_result(), config) for _ in range(2)]

    summary = summarize_kpis(kpis_list)

    assert summary["mean_turnaround_minutes"]["mean"] == pytest.approx(25.0)
    assert summary["mean_turnaround_minutes"]["ci_low"] == pytest.approx(25.0)
    assert summary["mean_turnaround_minutes"]["ci_high"] == pytest.approx(25.0)


def test_summarize_stage_kpis_groups_by_resource_and_keeps_stage_label():
    config = make_config()
    kpis_list = [compute_kpis(make_result(), config) for _ in range(2)]

    stage_summary = summarize_stage_kpis(kpis_list)

    assert set(stage_summary) == {"registration", "centrifugation"}
    assert stage_summary["centrifugation"]["stage"] == ProcessingStage.CENTRIFUGATION
    assert stage_summary["centrifugation"]["utilization"]["mean"] == pytest.approx(
        10.0 / 60.0
    )

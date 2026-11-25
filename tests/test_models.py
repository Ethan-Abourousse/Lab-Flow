"""Unit tests for src/models.py data structures."""

import math

import pytest

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


def make_sample(**overrides) -> Sample:
    defaults = dict(
        sample_id="S-0001",
        arrival_time_minutes=0.0,
        department=Department.BIOCHEMISTRY,
        priority=Priority.ROUTINE,
        requires_centrifugation=True,
        target_turnaround_minutes=120.0,
    )
    defaults.update(overrides)
    return Sample(**defaults)


def test_sample_defaults_and_is_urgent():
    routine = make_sample()
    urgent = make_sample(priority=Priority.URGENT, sample_id="S-0002")

    assert routine.requires_reprocessing is False
    assert routine.is_urgent is False
    assert urgent.is_urgent is True


def test_processing_event_waiting_and_service_time():
    event = ProcessingEvent(
        sample_id="S-0001",
        stage=ProcessingStage.REGISTRATION,
        resource_name="registration_desk_1",
        queue_entry_time_minutes=10.0,
        service_start_time_minutes=12.5,
        service_end_time_minutes=15.0,
    )

    assert math.isclose(event.waiting_time_minutes, 2.5)
    assert math.isclose(event.service_time_minutes, 2.5)


@pytest.mark.parametrize(
    "overrides",
    [
        {"capacity": 0},
        {"min_processing_minutes": 0},
        {"max_processing_minutes": -1},
        {"min_processing_minutes": 10, "max_processing_minutes": 5},
    ],
)
def test_laboratory_resource_rejects_invalid_configuration(overrides):
    defaults = dict(
        name="registration",
        capacity=2,
        min_processing_minutes=1.0,
        max_processing_minutes=3.0,
    )
    defaults.update(overrides)

    with pytest.raises(ValueError):
        LaboratoryResource(**defaults)


def test_laboratory_resource_accepts_valid_configuration():
    resource = LaboratoryResource(
        name="centrifugation",
        capacity=2,
        min_processing_minutes=10.0,
        max_processing_minutes=15.0,
        batch_capacity=8,
    )

    assert resource.batch_capacity == 8


def make_configuration(**overrides) -> SimulationConfiguration:
    defaults = dict(
        scenario_name="S0_baseline",
        random_seed=42,
        arrival_window_minutes=480.0,
        max_simulation_minutes=960.0,
        arrival_rate_per_hour=20.0,
        department_mix={
            Department.BIOCHEMISTRY: 0.5,
            Department.HEMATOLOGY: 0.3,
            Department.IMMUNOLOGY: 0.2,
        },
        urgent_probability=0.1,
        centrifugation_required={
            Department.BIOCHEMISTRY: True,
            Department.HEMATOLOGY: False,
            Department.IMMUNOLOGY: True,
        },
        target_turnaround_minutes={
            Priority.ROUTINE: 240.0,
            Priority.URGENT: 60.0,
        },
        resources={
            "registration": LaboratoryResource(
                name="registration",
                capacity=2,
                min_processing_minutes=1.0,
                max_processing_minutes=3.0,
            )
        },
    )
    defaults.update(overrides)
    return SimulationConfiguration(**defaults)


def test_simulation_configuration_valid_department_mix():
    config = make_configuration()

    assert config.scheduling_strategy == "fifo"
    assert config.replications == 1


def test_simulation_configuration_rejects_department_mix_not_summing_to_one():
    with pytest.raises(ValueError):
        make_configuration(
            department_mix={
                Department.BIOCHEMISTRY: 0.5,
                Department.HEMATOLOGY: 0.3,
                Department.IMMUNOLOGY: 0.1,
            }
        )


def test_simulation_configuration_rejects_invalid_urgent_probability():
    with pytest.raises(ValueError):
        make_configuration(urgent_probability=1.5)


def test_simulation_configuration_rejects_arrival_window_past_max_duration():
    with pytest.raises(ValueError):
        make_configuration(arrival_window_minutes=1000.0, max_simulation_minutes=960.0)


def test_simulation_configuration_rejects_incomplete_centrifugation_mapping():
    with pytest.raises(ValueError):
        make_configuration(centrifugation_required={Department.BIOCHEMISTRY: True})


def test_simulation_result_default_lists_are_independent_instances():
    result_a = SimulationResult(scenario_name="S0_baseline", replication_id=0)
    result_b = SimulationResult(scenario_name="S0_baseline", replication_id=1)

    result_a.samples.append(make_sample())

    assert result_a.samples != result_b.samples
    assert result_b.samples == []

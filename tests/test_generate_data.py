"""Unit tests for src/generate_data.py."""

import math

import numpy as np

from src.generate_data import (
    load_configuration,
    load_scenario_configurations,
    generate_samples,
)
from src.models import Department, Priority


def test_load_configuration_reads_baseline():
    config = load_configuration()

    assert config.scenario_name == "S0_baseline"
    assert config.resources["registration"].capacity == 2
    assert math.isclose(sum(config.department_mix.values()), 1.0)


def test_load_scenario_configurations_merges_overrides_without_losing_siblings():
    scenarios = load_scenario_configurations()

    s2 = scenarios["S2_increased_analyzer_capacity"]
    assert s2.resources["biochemistry_analyzer"].capacity == 3
    # Unrelated resources and fields must be untouched by the override.
    assert s2.resources["registration"].capacity == 2
    assert s2.scheduling_strategy == "fifo"

    s3 = scenarios["S3_faster_registration"]
    assert s3.resources["registration"].min_processing_minutes == 0.5
    # Capacity (not overridden by S3) must still come from the baseline.
    assert s3.resources["registration"].capacity == 2


def test_generate_samples_is_reproducible_with_identical_seed():
    config = load_configuration()

    first_run = generate_samples(config, rng=np.random.default_rng(config.random_seed))
    second_run = generate_samples(config, rng=np.random.default_rng(config.random_seed))

    assert [s.sample_id for s in first_run] == [s.sample_id for s in second_run]
    assert [s.arrival_time_minutes for s in first_run] == [
        s.arrival_time_minutes for s in second_run
    ]
    assert [s.department for s in first_run] == [s.department for s in second_run]


def test_generate_samples_respects_arrival_window():
    config = load_configuration()
    samples = generate_samples(config)

    assert len(samples) > 0
    assert all(s.arrival_time_minutes <= config.arrival_window_minutes for s in samples)


def test_generate_samples_arrivals_are_chronologically_ordered():
    config = load_configuration()
    samples = generate_samples(config)

    arrival_times = [s.arrival_time_minutes for s in samples]
    assert arrival_times == sorted(arrival_times)


def test_generate_samples_routes_centrifugation_by_department():
    config = load_configuration()
    samples = generate_samples(config)

    for sample in samples:
        expected = config.centrifugation_required[sample.department]
        assert sample.requires_centrifugation == expected


def test_generate_samples_no_duplicate_sample_ids():
    config = load_configuration()
    samples = generate_samples(config)

    sample_ids = [s.sample_id for s in samples]
    assert len(sample_ids) == len(set(sample_ids))


def test_generate_samples_department_and_priority_values_are_valid_enums():
    config = load_configuration()
    samples = generate_samples(config)

    for sample in samples:
        assert sample.department in Department
        assert sample.priority in Priority

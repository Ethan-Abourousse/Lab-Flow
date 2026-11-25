"""Integration tests for src/simulation.py (end-to-end laboratory pipeline).

Covers the invariants explicitly required by the project brief:
reproducibility, conservation of sample counts, chronological ordering,
non-negative waiting times, resource capacity constraints, and correct
sample routing / priority scheduling.
"""

from collections import defaultdict

import pytest

from src.generate_data import load_configuration, load_scenario_configurations
from src.models import ProcessingStage
from src.simulation import run_simulation_replication

#: Expected order of stages for a sample requiring centrifugation.
STAGE_ORDER_WITH_CENTRIFUGATION = [
    ProcessingStage.REGISTRATION,
    ProcessingStage.PREPARATION,
    ProcessingStage.CENTRIFUGATION,
    ProcessingStage.ANALYSIS,
    ProcessingStage.VALIDATION,
    ProcessingStage.REPORTING,
]
STAGE_ORDER_WITHOUT_CENTRIFUGATION = [
    ProcessingStage.REGISTRATION,
    ProcessingStage.PREPARATION,
    ProcessingStage.ANALYSIS,
    ProcessingStage.VALIDATION,
    ProcessingStage.REPORTING,
]


def max_concurrent_intervals(intervals: list[tuple[float, float]]) -> int:
    """Sweep-line maximum number of simultaneously open [start, end) intervals."""
    boundaries = []
    for start, end in intervals:
        boundaries.append((start, 1))
        boundaries.append((end, -1))
    # Process interval ends before starts at the same instant, since a
    # resource unit freed at time t is immediately available to a request
    # that also becomes active at time t.
    boundaries.sort(key=lambda item: (item[0], item[1]))

    current = 0
    peak = 0
    for _, delta in boundaries:
        current += delta
        peak = max(peak, current)
    return peak


@pytest.fixture(scope="module")
def baseline_config():
    return load_configuration()


@pytest.fixture(scope="module")
def baseline_result(baseline_config):
    return run_simulation_replication(baseline_config, replication_index=0)


def test_reproducibility_with_identical_seed(baseline_config):
    result_a = run_simulation_replication(baseline_config, replication_index=0)
    result_b = run_simulation_replication(baseline_config, replication_index=0)

    assert [s.sample_id for s in result_a.samples] == [s.sample_id for s in result_b.samples]
    assert len(result_a.events) == len(result_b.events)
    events_a = sorted(
        (e.sample_id, e.stage, e.service_start_time_minutes, e.service_end_time_minutes)
        for e in result_a.events
    )
    events_b = sorted(
        (e.sample_id, e.stage, e.service_start_time_minutes, e.service_end_time_minutes)
        for e in result_b.events
    )
    assert events_a == events_b


def test_conservation_of_sample_counts(baseline_result):
    """Every generated sample must reach the reporting stage exactly once."""
    sample_ids = {s.sample_id for s in baseline_result.samples}
    reporting_sample_ids = [
        e.sample_id for e in baseline_result.events if e.stage == ProcessingStage.REPORTING
    ]

    assert len(reporting_sample_ids) == len(set(reporting_sample_ids)), "no duplicated completions"
    assert set(reporting_sample_ids) == sample_ids, "no samples lost or fabricated"


def test_non_negative_waiting_and_service_times(baseline_result):
    for event in baseline_result.events:
        assert event.waiting_time_minutes >= -1e-9
        assert event.service_time_minutes >= -1e-9


def test_chronological_ordering_per_sample(baseline_result):
    samples_by_id = {s.sample_id: s for s in baseline_result.samples}
    events_by_sample = defaultdict(list)
    for event in baseline_result.events:
        events_by_sample[event.sample_id].append(event)

    for sample_id, events in events_by_sample.items():
        sample = samples_by_id[sample_id]
        expected_order = (
            STAGE_ORDER_WITH_CENTRIFUGATION
            if sample.requires_centrifugation
            else STAGE_ORDER_WITHOUT_CENTRIFUGATION
        )
        events_by_stage = {e.stage: e for e in events}
        assert set(events_by_stage) == set(expected_order), sample_id
        ordered_events = [events_by_stage[stage] for stage in expected_order]

        for earlier, later in zip(ordered_events, ordered_events[1:]):
            assert earlier.service_end_time_minutes <= later.queue_entry_time_minutes + 1e-9
        assert ordered_events[0].queue_entry_time_minutes >= sample.arrival_time_minutes - 1e-9


def test_resource_capacity_is_never_exceeded(baseline_config, baseline_result):
    events_by_resource = defaultdict(list)
    for event in baseline_result.events:
        if event.stage == ProcessingStage.REPORTING:
            continue  # not a capacity-constrained resource
        events_by_resource[event.resource_name].append(event)

    for resource_name, events in events_by_resource.items():
        capacity = baseline_config.resources[resource_name].capacity
        if resource_name == "centrifugation":
            # Multiple samples sharing one batch report identical service
            # timestamps; only distinct batches consume a centrifuge unit.
            intervals = {
                (e.service_start_time_minutes, e.service_end_time_minutes) for e in events
            }
        else:
            intervals = [
                (e.service_start_time_minutes, e.service_end_time_minutes) for e in events
            ]
        assert max_concurrent_intervals(list(intervals)) <= capacity, resource_name


def test_centrifugation_routing_matches_department_configuration(baseline_config, baseline_result):
    samples_by_id = {s.sample_id: s for s in baseline_result.samples}
    centrifugation_sample_ids = {
        e.sample_id for e in baseline_result.events if e.stage == ProcessingStage.CENTRIFUGATION
    }

    for sample_id, sample in samples_by_id.items():
        expected = baseline_config.centrifugation_required[sample.department]
        assert (sample_id in centrifugation_sample_ids) == expected


def test_analysis_routes_to_the_matching_department_analyzer(baseline_result):
    samples_by_id = {s.sample_id: s for s in baseline_result.samples}
    for event in baseline_result.events:
        if event.stage != ProcessingStage.ANALYSIS:
            continue
        sample = samples_by_id[event.sample_id]
        assert event.resource_name == f"{sample.department.value}_analyzer"


def test_priority_strategy_reduces_mean_waiting_time_for_urgent_samples():
    scenarios = load_scenario_configurations()
    config = scenarios["S1_priority_scheduling"]
    result = run_simulation_replication(config, replication_index=0)

    samples_by_id = {s.sample_id: s for s in result.samples}
    waits_by_priority = defaultdict(list)
    for event in result.events:
        if event.stage == ProcessingStage.REPORTING:
            continue
        sample = samples_by_id[event.sample_id]
        waits_by_priority[sample.priority].append(event.waiting_time_minutes)

    from src.models import Priority

    mean_urgent_wait = sum(waits_by_priority[Priority.URGENT]) / len(waits_by_priority[Priority.URGENT])
    mean_routine_wait = sum(waits_by_priority[Priority.ROUTINE]) / len(waits_by_priority[Priority.ROUTINE])

    assert mean_urgent_wait < mean_routine_wait

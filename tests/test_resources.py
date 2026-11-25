"""Unit tests for src/resources.py."""

import simpy
import pytest

from src.generate_data import load_configuration
from src.models import Department, Priority, Sample
from src.resources import (
    CentrifugeBatchQueue,
    build_resources,
    request_resource,
    schedule_resource_failures,
)


def make_sample(sample_id: str, priority: Priority = Priority.ROUTINE) -> Sample:
    return Sample(
        sample_id=sample_id,
        arrival_time_minutes=0.0,
        department=Department.BIOCHEMISTRY,
        priority=priority,
        requires_centrifugation=True,
        target_turnaround_minutes=240.0,
    )


def test_build_resources_uses_configured_capacities():
    config = load_configuration()
    env = simpy.Environment()

    resources = build_resources(env, config)

    assert set(resources) == set(config.resources)
    for name, spec in config.resources.items():
        assert resources[name].capacity == spec.capacity


def test_build_resources_selects_fifo_resource_type_by_default():
    config = load_configuration()
    assert config.scheduling_strategy == "fifo"
    env = simpy.Environment()

    resources = build_resources(env, config)

    assert all(type(r) is simpy.Resource for r in resources.values())


def test_build_resources_selects_priority_resource_for_priority_strategy():
    config = load_configuration()
    config.scheduling_strategy = "priority"
    env = simpy.Environment()

    resources = build_resources(env, config)

    assert all(isinstance(r, simpy.PriorityResource) for r in resources.values())


def test_request_resource_works_for_both_resource_types():
    env = simpy.Environment()
    plain = simpy.Resource(env, capacity=1)
    priority = simpy.PriorityResource(env, capacity=1)

    def user():
        with request_resource(plain) as req:
            yield req
        with request_resource(priority, priority=5) as req:
            yield req

    env.process(user())
    env.run()


def test_centrifuge_batch_queue_rejects_non_positive_capacity():
    env = simpy.Environment()
    with pytest.raises(ValueError):
        CentrifugeBatchQueue(env, batch_capacity=0)


def test_centrifuge_batch_queue_is_full_and_has_urgent():
    env = simpy.Environment()
    queue = CentrifugeBatchQueue(env, batch_capacity=3)

    queue.add(make_sample("S-1"))
    assert not queue.is_full()
    assert not queue.has_urgent_sample()

    queue.add(make_sample("S-2"))
    queue.add(make_sample("S-3", priority=Priority.URGENT))
    assert queue.is_full()
    assert queue.has_urgent_sample()
    assert len(queue) == 3


def test_centrifuge_batch_queue_pull_batch_is_fifo_and_keeps_remainder():
    env = simpy.Environment()
    queue = CentrifugeBatchQueue(env, batch_capacity=2)

    for sample_id in ("S-1", "S-2", "S-3"):
        queue.add(make_sample(sample_id))

    batch = queue.pull_batch()

    assert [s.sample_id for s in batch] == ["S-1", "S-2"]
    assert len(queue) == 1


def test_centrifuge_batch_queue_oldest_wait_minutes_tracks_simulation_clock():
    env = simpy.Environment()
    queue = CentrifugeBatchQueue(env, batch_capacity=5)

    def arrival_process():
        queue.add(make_sample("S-1"))
        yield env.timeout(7)

    env.process(arrival_process())
    env.run(until=7)

    assert queue.oldest_wait_minutes() == pytest.approx(7.0)


def test_schedule_resource_failures_temporarily_reduces_available_capacity():
    env = simpy.Environment()
    resource = simpy.Resource(env, capacity=2)

    class FailureConfig:
        resource_failures = {
            "dummy": {
                "start_minutes": 5.0,
                "duration_minutes": 10.0,
                "capacity_reduction": 1,
            }
        }

    schedule_resource_failures(env, {"dummy": resource}, FailureConfig())

    env.run(until=4)
    assert resource.count == 0

    env.run(until=6)
    assert resource.count == 1

    env.run(until=16)
    assert resource.count == 0

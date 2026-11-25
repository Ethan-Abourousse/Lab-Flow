"""Unit tests for src/scheduling.py: queue discipline and batch dispatch."""

import simpy
import numpy as np
import pytest

from src.models import Department, Priority, Sample
from src.resources import CentrifugeBatchQueue, request_resource
from src.scheduling import (
    compute_request_priority,
    run_adaptive_centrifuge_dispatcher,
    run_fixed_interval_centrifuge_dispatcher,
)


def make_sample(sample_id: str, priority: Priority, arrival_time: float = 0.0, target_turnaround: float = 240.0) -> Sample:
    return Sample(
        sample_id=sample_id,
        arrival_time_minutes=arrival_time,
        department=Department.BIOCHEMISTRY,
        priority=priority,
        requires_centrifugation=True,
        target_turnaround_minutes=target_turnaround,
    )


class _FakeConfig:
    def __init__(self, scheduling_strategy):
        self.scheduling_strategy = scheduling_strategy


def test_compute_request_priority_fifo_is_always_zero():
    config = _FakeConfig("fifo")
    routine = make_sample("S-1", Priority.ROUTINE)
    urgent = make_sample("S-2", Priority.URGENT)

    assert compute_request_priority(routine, config) == 0.0
    assert compute_request_priority(urgent, config) == 0.0


def test_compute_request_priority_priority_strategy_favors_urgent():
    config = _FakeConfig("priority")
    routine = make_sample("S-1", Priority.ROUTINE)
    urgent = make_sample("S-2", Priority.URGENT)

    assert compute_request_priority(urgent, config) < compute_request_priority(routine, config)


def test_compute_request_priority_edf_favors_earlier_deadline():
    config = _FakeConfig("edf")
    tight_deadline = make_sample("S-1", Priority.ROUTINE, arrival_time=0.0, target_turnaround=60.0)
    loose_deadline = make_sample("S-2", Priority.URGENT, arrival_time=0.0, target_turnaround=240.0)

    # Even though S-2 is urgent, EDF only cares about the absolute deadline.
    assert compute_request_priority(tight_deadline, config) < compute_request_priority(loose_deadline, config)


def test_priority_strategy_serves_later_urgent_request_before_earlier_routine_request():
    """An urgent request made after a routine one must still be served first."""
    env = simpy.Environment()
    resource = simpy.PriorityResource(env, capacity=1)
    config = _FakeConfig("priority")
    serve_order: list[str] = []

    def hold_resource():
        with request_resource(resource, priority=0.0) as req:
            yield req
            yield env.timeout(5)

    def contender(sample_id: str, sample: Sample, arrival_delay: float):
        yield env.timeout(arrival_delay)
        priority = compute_request_priority(sample, config)
        with request_resource(resource, priority=priority) as req:
            yield req
            serve_order.append(sample_id)

    env.process(hold_resource())
    env.process(contender("routine-first", make_sample("routine-first", Priority.ROUTINE), 1))
    env.process(contender("urgent-second", make_sample("urgent-second", Priority.URGENT), 2))
    env.run()

    assert serve_order == ["urgent-second", "routine-first"]


def test_fixed_interval_dispatcher_only_pulls_on_the_configured_interval():
    env = simpy.Environment()
    queue = CentrifugeBatchQueue(env, batch_capacity=5)
    resource = simpy.Resource(env, capacity=1)
    rng = np.random.default_rng(0)
    dispatched_batches: list[list[Sample]] = []

    class Config:
        centrifugation_fixed_interval_minutes = 10.0
        resources = {
            "centrifugation": type(
                "Spec", (), {"min_processing_minutes": 1.0, "max_processing_minutes": 1.0}
            )()
        }

    def on_batch_complete(batch, start, end):
        dispatched_batches.append(batch)

    env.process(
        run_fixed_interval_centrifuge_dispatcher(
            env, queue, resource, rng, Config(), on_batch_complete
        )
    )

    def add_sample_at(delay):
        yield env.timeout(delay)
        queue.add(make_sample(f"S-{env.now}", Priority.ROUTINE))

    env.process(add_sample_at(1))
    env.run(until=9)
    assert len(dispatched_batches) == 0  # interval (10) hasn't elapsed yet

    env.run(until=11.5)  # margin past the batch's service completion at t=11
    assert len(dispatched_batches) == 1
    assert len(dispatched_batches[0]) == 1


def test_adaptive_dispatcher_triggers_on_full_batch():
    env = simpy.Environment()
    queue = CentrifugeBatchQueue(env, batch_capacity=2)
    resource = simpy.Resource(env, capacity=1)
    rng = np.random.default_rng(0)
    dispatched_batches: list[list[Sample]] = []

    class Config:
        centrifugation_batch_wait_threshold_minutes = 1000.0
        resources = {
            "centrifugation": type(
                "Spec", (), {"min_processing_minutes": 0.0, "max_processing_minutes": 0.0}
            )()
        }

    env.process(
        run_adaptive_centrifuge_dispatcher(
            env, queue, resource, rng, Config(), lambda b, s, e: dispatched_batches.append(b)
        )
    )

    def add_samples():
        queue.add(make_sample("S-1", Priority.ROUTINE))
        yield env.timeout(0)
        queue.add(make_sample("S-2", Priority.ROUTINE))

    env.process(add_samples())
    env.run(until=0.5)

    assert len(dispatched_batches) == 1
    assert len(dispatched_batches[0]) == 2


def test_adaptive_dispatcher_triggers_immediately_on_urgent_sample():
    env = simpy.Environment()
    queue = CentrifugeBatchQueue(env, batch_capacity=10)
    resource = simpy.Resource(env, capacity=1)
    rng = np.random.default_rng(0)
    dispatched_batches: list[list[Sample]] = []

    class Config:
        centrifugation_batch_wait_threshold_minutes = 1000.0
        resources = {
            "centrifugation": type(
                "Spec", (), {"min_processing_minutes": 0.0, "max_processing_minutes": 0.0}
            )()
        }

    env.process(
        run_adaptive_centrifuge_dispatcher(
            env, queue, resource, rng, Config(), lambda b, s, e: dispatched_batches.append(b)
        )
    )

    def add_urgent():
        queue.add(make_sample("S-urgent", Priority.URGENT))
        yield env.timeout(0)

    env.process(add_urgent())
    env.run(until=0.5)

    assert len(dispatched_batches) == 1


def test_adaptive_dispatcher_triggers_on_wait_threshold():
    env = simpy.Environment()
    queue = CentrifugeBatchQueue(env, batch_capacity=10)
    resource = simpy.Resource(env, capacity=1)
    rng = np.random.default_rng(0)
    dispatched_batches: list[list[Sample]] = []

    class Config:
        centrifugation_batch_wait_threshold_minutes = 5.0
        resources = {
            "centrifugation": type(
                "Spec", (), {"min_processing_minutes": 0.0, "max_processing_minutes": 0.0}
            )()
        }

    def add_sample():
        queue.add(make_sample("S-1", Priority.ROUTINE))
        yield env.timeout(0)

    env.process(add_sample())
    env.process(
        run_adaptive_centrifuge_dispatcher(
            env, queue, resource, rng, Config(), lambda b, s, e: dispatched_batches.append(b)
        )
    )

    env.run(until=4.9)
    assert len(dispatched_batches) == 0

    env.run(until=5.5)
    assert len(dispatched_batches) == 1


def test_adaptive_dispatcher_does_not_livelock_on_subepsilon_wait_remaining():
    """Regression test: a sub-float-resolution wait_remaining must not livelock.

    If ``threshold - oldest_wait_minutes()`` is a positive value smaller
    than floating-point resolution at the current simulation time,
    scheduling a timeout of that size never actually advances ``env.now``
    (it rounds back to the same float), spinning forever. The dispatcher
    must treat such a value as "threshold reached" instead.
    """
    env = simpy.Environment()
    queue = CentrifugeBatchQueue(env, batch_capacity=10)
    resource = simpy.Resource(env, capacity=1)
    rng = np.random.default_rng(0)
    dispatched_batches: list[list[Sample]] = []

    class Config:
        centrifugation_batch_wait_threshold_minutes = 5.0
        resources = {
            "centrifugation": type(
                "Spec", (), {"min_processing_minutes": 0.0, "max_processing_minutes": 0.0}
            )()
        }

    queue.add(make_sample("S-1", Priority.ROUTINE))
    queue.oldest_wait_minutes = lambda: (
        Config.centrifugation_batch_wait_threshold_minutes - 1e-14
    )

    env.process(
        run_adaptive_centrifuge_dispatcher(
            env, queue, resource, rng, Config(), lambda b, s, e: dispatched_batches.append(b)
        )
    )

    env.run(until=0.01)  # must terminate almost instantly, never hang

    assert len(dispatched_batches) == 1

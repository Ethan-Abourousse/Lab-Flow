"""SimPy resource construction, priority-aware requests, and batch queues.

This module turns the static :class:`~src.models.LaboratoryResource`
configuration into live SimPy resource objects, and provides the generic
mechanics needed by the scheduling strategies in ``src/scheduling.py``:

- Plain vs. priority-queued resources, selected uniformly from
  ``config.scheduling_strategy`` (FIFO vs. priority/EDF queueing).
- A :class:`CentrifugeBatchQueue` waiting area where samples needing
  centrifugation accumulate until a batch-dispatch policy pulls a batch out.
- Temporary equipment failures, modelled as a process that reserves (and
  holds) capacity units for a configured outage window.

Resource occupation times are not tracked here: each use is already
timestamped as a :class:`~src.models.ProcessingEvent` by
``src/laboratory.py``, which is sufficient to derive utilization and queue
KPIs in ``src/kpi.py`` without duplicating bookkeeping in this module.
"""

from __future__ import annotations

from dataclasses import dataclass

import simpy

from src.models import Sample, SimulationConfiguration

#: Resource types whose queue is served in FIFO order of arrival.
FIFO_STRATEGIES = {"fifo"}
#: Resource types whose queue is served by SimPy request priority.
PRIORITY_STRATEGIES = {"priority", "edf"}


def build_resources(
    env: simpy.Environment, config: SimulationConfiguration
) -> dict[str, simpy.Resource | simpy.PriorityResource]:
    """Create one SimPy resource per entry in ``config.resources``.

    ``simpy.PriorityResource`` is used uniformly for every resource
    (including the centrifuge machines) when the configuration's
    ``scheduling_strategy`` is ``"priority"`` or ``"edf"``; plain
    ``simpy.Resource`` (FIFO) is used for ``"fifo"``.
    """
    resource_cls = (
        simpy.PriorityResource
        if config.scheduling_strategy in PRIORITY_STRATEGIES
        else simpy.Resource
    )
    return {
        name: resource_cls(env, capacity=spec.capacity)
        for name, spec in config.resources.items()
    }


def request_resource(
    resource: simpy.Resource | simpy.PriorityResource, priority: int = 0
) -> simpy.events.Request:
    """Request one unit of ``resource``, passing ``priority`` only if supported.

    Lower ``priority`` values are served first (SimPy convention). Requests
    never preempt an already-running service: priority only reorders the
    waiting queue, it does not interrupt in-progress sample processing.
    """
    if isinstance(resource, simpy.PriorityResource):
        return resource.request(priority=priority, preempt=False)
    return resource.request()


@dataclass
class _PendingBatchItem:
    sample: Sample
    enqueued_at_minutes: float


class CentrifugeBatchQueue:
    """Waiting area where samples needing centrifugation accumulate.

    This class only tracks *what* is waiting; *when* to pull a batch out
    (fixed-interval vs. adaptive) is a scheduling policy decision, made in
    ``src/scheduling.py``.
    """

    def __init__(self, env: simpy.Environment, batch_capacity: int):
        if batch_capacity <= 0:
            raise ValueError("batch_capacity must be > 0.")
        self.env = env
        self.batch_capacity = batch_capacity
        self._pending: list[_PendingBatchItem] = []
        self._arrival_event: simpy.Event = env.event()

    def add(self, sample: Sample) -> None:
        """Enqueue a sample and wake up anyone waiting via ``wait_for_arrival``."""
        self._pending.append(_PendingBatchItem(sample, self.env.now))
        if not self._arrival_event.triggered:
            self._arrival_event.succeed()

    def wait_for_arrival(self) -> simpy.Event:
        """Return an event firing the next time a sample is added.

        If the previous signal was already consumed (triggered), a fresh
        event is created first, so repeated calls always look forward
        rather than returning an already-resolved event.
        """
        if self._arrival_event.triggered:
            self._arrival_event = self.env.event()
        return self._arrival_event

    def is_full(self) -> bool:
        """True once the waiting area holds a full batch."""
        return len(self._pending) >= self.batch_capacity

    def has_urgent_sample(self) -> bool:
        """True if any waiting sample is urgent priority."""
        return any(item.sample.is_urgent for item in self._pending)

    def oldest_wait_minutes(self) -> float:
        """Minutes the longest-waiting sample has been queued (0 if empty)."""
        if not self._pending:
            return 0.0
        return self.env.now - self._pending[0].enqueued_at_minutes

    def pull_batch(self) -> list[Sample]:
        """Remove and return up to ``batch_capacity`` samples, oldest first."""
        batch_items, self._pending = (
            self._pending[: self.batch_capacity],
            self._pending[self.batch_capacity :],
        )
        return [item.sample for item in batch_items]

    def __len__(self) -> int:
        return len(self._pending)


def schedule_resource_failures(
    env: simpy.Environment,
    resources: dict[str, simpy.Resource | simpy.PriorityResource],
    config: SimulationConfiguration,
) -> None:
    """Start one process per entry in ``config.resource_failures``.

    Each failure reserves ``capacity_reduction`` units of the named resource
    starting at ``start_minutes`` and holds them for ``duration_minutes``,
    making that capacity unavailable to samples for the outage window. As a
    modelling simplification, a failure does not interrupt a sample already
    being processed; it only prevents new samples from being assigned to the
    affected units once they next become free.
    """
    for resource_name, failure in config.resource_failures.items():
        env.process(
            _run_resource_failure(env, resources[resource_name], failure)
        )


def _run_resource_failure(
    env: simpy.Environment,
    resource: simpy.Resource | simpy.PriorityResource,
    failure: dict,
):
    yield env.timeout(failure["start_minutes"])
    requests = [
        request_resource(resource, priority=-1)
        for _ in range(failure["capacity_reduction"])
    ]
    yield simpy.AllOf(env, requests)
    yield env.timeout(failure["duration_minutes"])
    for req in requests:
        resource.release(req)

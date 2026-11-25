"""Scheduling strategies: queue discipline and centrifugation batch dispatch.

Two independent policy axes are implemented, matching
``config.scheduling_strategy`` and ``config.centrifugation_strategy``:

- **Queue discipline** for individually-processed resources (registration,
  preparation, analyzers, validation): First In First Out (FIFO),
  priority-based (urgent samples served first), or Earliest Deadline First
  (EDF, ordered by absolute deadline = arrival time + target turnaround).
  The resource *type* (plain vs. priority) is chosen in ``src/resources.py``;
  this module only computes the priority *value* attached to each request.

- **Centrifugation batching**: fixed-interval (a batch is pulled on a
  regular timer) or adaptive (a batch is pulled as soon as it is full, the
  oldest waiting sample exceeds its wait-time threshold, or an urgent
  sample is waiting). These decisions move samples out of a
  :class:`~src.resources.CentrifugeBatchQueue` and run the shared
  centrifuge resource for a single batch-processing duration.

These are simulated scheduling decisions only; nothing here controls real
laboratory equipment.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import simpy

from src.models import Sample, SimulationConfiguration
from src.resources import CentrifugeBatchQueue, request_resource

#: Callback invoked once a centrifuge batch finishes servicing, receiving
#: the batch's samples and the shared service start/end timestamps.
OnBatchComplete = Callable[[list[Sample], float, float], None]


def compute_request_priority(sample: Sample, config: SimulationConfiguration) -> float:
    """Return the SimPy request priority value for ``sample``.

    Lower values are served first. The value is only meaningful when the
    target resource was built as a ``simpy.PriorityResource`` (see
    ``build_resources`` in ``src/resources.py``); it is ignored by plain
    FIFO resources.
    """
    if config.scheduling_strategy == "priority":
        return 0.0 if sample.is_urgent else 1.0
    if config.scheduling_strategy == "edf":
        return sample.arrival_time_minutes + sample.target_turnaround_minutes
    return 0.0


def _run_centrifuge_batch(
    env: simpy.Environment,
    batch: list[Sample],
    centrifuge_resource: simpy.Resource | simpy.PriorityResource,
    rng: np.random.Generator,
    config: SimulationConfiguration,
    on_batch_complete: OnBatchComplete,
):
    """Service one already-pulled batch: reserve a machine, run it, report back."""
    centrifuge_spec = config.resources["centrifugation"]
    priority = 0.0 if any(sample.is_urgent for sample in batch) else 1.0
    with request_resource(centrifuge_resource, priority=priority) as req:
        yield req
        service_start = env.now
        duration = rng.uniform(
            centrifuge_spec.min_processing_minutes,
            centrifuge_spec.max_processing_minutes,
        )
        yield env.timeout(duration)
        service_end = env.now
    on_batch_complete(batch, service_start, service_end)


def run_fixed_interval_centrifuge_dispatcher(
    env: simpy.Environment,
    queue: CentrifugeBatchQueue,
    centrifuge_resource: simpy.Resource | simpy.PriorityResource,
    rng: np.random.Generator,
    config: SimulationConfiguration,
    on_batch_complete: OnBatchComplete,
):
    """Pull whatever is waiting every ``centrifugation_fixed_interval_minutes``.

    Represents a lab that runs the centrifuge on a fixed schedule regardless
    of how full the batch is or how long samples have been waiting.
    """
    while True:
        yield env.timeout(config.centrifugation_fixed_interval_minutes)
        if len(queue) > 0:
            batch = queue.pull_batch()
            env.process(
                _run_centrifuge_batch(
                    env, batch, centrifuge_resource, rng, config, on_batch_complete
                )
            )


#: Minimum scheduled timeout for the adaptive dispatcher's wait-threshold
#: check. Guards against computing a "remaining wait" so small it falls
#: below floating-point resolution at the current simulation time (which
#: would schedule a timeout that never actually advances ``env.now``,
#: livelocking the dispatcher); anything at or below this is treated as
#: "the threshold has been reached, dispatch now".
_MIN_WAIT_THRESHOLD_MINUTES = 1e-6


def run_adaptive_centrifuge_dispatcher(
    env: simpy.Environment,
    queue: CentrifugeBatchQueue,
    centrifuge_resource: simpy.Resource | simpy.PriorityResource,
    rng: np.random.Generator,
    config: SimulationConfiguration,
    on_batch_complete: OnBatchComplete,
):
    """Pull a batch as soon as one of three conditions is met.

    A batch is dispatched when: the waiting area is full, an urgent sample
    is waiting, or the oldest waiting sample has reached
    ``centrifugation_batch_wait_threshold_minutes``. ``pull_batch()`` is
    always called synchronously before spawning the servicing process, so
    the same items can never be dispatched twice.
    """
    while True:
        if len(queue) == 0:
            yield queue.wait_for_arrival()
            continue

        if queue.is_full() or queue.has_urgent_sample():
            batch = queue.pull_batch()
            env.process(
                _run_centrifuge_batch(
                    env, batch, centrifuge_resource, rng, config, on_batch_complete
                )
            )
            continue

        wait_remaining = (
            config.centrifugation_batch_wait_threshold_minutes
            - queue.oldest_wait_minutes()
        )
        if wait_remaining <= _MIN_WAIT_THRESHOLD_MINUTES:
            batch = queue.pull_batch()
            env.process(
                _run_centrifuge_batch(
                    env, batch, centrifuge_resource, rng, config, on_batch_complete
                )
            )
            continue

        yield simpy.AnyOf(env, [env.timeout(wait_remaining), queue.wait_for_arrival()])


#: Maps ``config.centrifugation_strategy`` values to their dispatcher process.
CENTRIFUGE_DISPATCHERS = {
    "fixed_interval": run_fixed_interval_centrifuge_dispatcher,
    "adaptive": run_adaptive_centrifuge_dispatcher,
}

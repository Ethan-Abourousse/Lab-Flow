"""Laboratory architecture and sample-processing workflow.

Represents the physical workflow described in the project brief::

    Sample arrival -> Registration -> Preparation
        -> Centrifugation (if required) -> Analysis -> Validation
        -> Report transmission

Each stage reserves the corresponding SimPy resource (built in
``src/resources.py``), waits the configured processing duration, and
records a :class:`~src.models.ProcessingEvent`. Centrifugation is routed
through a shared :class:`~src.resources.CentrifugeBatchQueue` and dispatched
according to ``config.centrifugation_strategy`` (see ``src/scheduling.py``);
every other stage is an ordinary single-sample resource request, ordered per
``config.scheduling_strategy``.
"""

from __future__ import annotations

import simpy
import numpy as np

from src.models import ProcessingEvent, ProcessingStage, Sample, SimulationConfiguration
from src.resources import build_resources, request_resource, schedule_resource_failures, CentrifugeBatchQueue
from src.scheduling import CENTRIFUGE_DISPATCHERS, compute_request_priority

#: Resource name used to record the (instantaneous) report-transmission stage.
REPORT_TRANSMISSION_RESOURCE_NAME = "report_transmission"


class Laboratory:
    """SimPy-driven laboratory: owns resources and routes samples through them."""

    def __init__(
        self,
        env: simpy.Environment,
        config: SimulationConfiguration,
        rng: np.random.Generator,
    ):
        self.env = env
        self.config = config
        self.rng = rng
        self.resources = build_resources(env, config)
        self.events: list[ProcessingEvent] = []

        centrifuge_spec = config.resources["centrifugation"]
        self.centrifuge_queue = CentrifugeBatchQueue(
            env, batch_capacity=centrifuge_spec.batch_capacity
        )
        self._centrifuge_done_events: dict[str, simpy.Event] = {}

        schedule_resource_failures(env, self.resources, config)
        self._start_centrifuge_dispatcher()

    def _start_centrifuge_dispatcher(self) -> None:
        dispatcher = CENTRIFUGE_DISPATCHERS[self.config.centrifugation_strategy]
        self.env.process(
            dispatcher(
                self.env,
                self.centrifuge_queue,
                self.resources["centrifugation"],
                self.rng,
                self.config,
                self._complete_centrifuge_batch,
            )
        )

    def _complete_centrifuge_batch(
        self, batch: list[Sample], service_start: float, service_end: float
    ) -> None:
        for sample in batch:
            done_event = self._centrifuge_done_events.pop(sample.sample_id)
            done_event.succeed((service_start, service_end))

    def process_sample(self, sample: Sample):
        """SimPy process: route ``sample`` through every required stage.

        A :class:`~src.models.ProcessingEvent` is appended to ``self.events``
        after every stage, including the instantaneous report-transmission
        step, so the full chronological history of a sample can be
        reconstructed afterwards.
        """
        yield from self._process_stage(sample, ProcessingStage.REGISTRATION, "registration")
        yield from self._process_stage(sample, ProcessingStage.PREPARATION, "preparation")

        if sample.requires_centrifugation:
            yield from self._process_centrifugation(sample)

        analyzer_name = f"{sample.department.value}_analyzer"
        yield from self._process_stage(sample, ProcessingStage.ANALYSIS, analyzer_name)
        yield from self._process_stage(sample, ProcessingStage.VALIDATION, "validation")
        self._record_report_transmission(sample)

    def _process_stage(
        self, sample: Sample, stage: ProcessingStage, resource_name: str
    ):
        resource = self.resources[resource_name]
        spec = self.config.resources[resource_name]
        queue_entry_time = self.env.now
        priority = compute_request_priority(sample, self.config)

        with request_resource(resource, priority=priority) as req:
            yield req
            service_start_time = self.env.now
            duration = self.rng.uniform(
                spec.min_processing_minutes, spec.max_processing_minutes
            )
            yield self.env.timeout(duration)
            service_end_time = self.env.now

        self.events.append(
            ProcessingEvent(
                sample_id=sample.sample_id,
                stage=stage,
                resource_name=resource_name,
                queue_entry_time_minutes=queue_entry_time,
                service_start_time_minutes=service_start_time,
                service_end_time_minutes=service_end_time,
            )
        )

    def _process_centrifugation(self, sample: Sample):
        queue_entry_time = self.env.now
        done_event = self.env.event()
        self._centrifuge_done_events[sample.sample_id] = done_event
        self.centrifuge_queue.add(sample)

        service_start_time, service_end_time = yield done_event

        self.events.append(
            ProcessingEvent(
                sample_id=sample.sample_id,
                stage=ProcessingStage.CENTRIFUGATION,
                resource_name="centrifugation",
                queue_entry_time_minutes=queue_entry_time,
                service_start_time_minutes=service_start_time,
                service_end_time_minutes=service_end_time,
            )
        )

    def _record_report_transmission(self, sample: Sample) -> None:
        now = self.env.now
        self.events.append(
            ProcessingEvent(
                sample_id=sample.sample_id,
                stage=ProcessingStage.REPORTING,
                resource_name=REPORT_TRANSMISSION_RESOURCE_NAME,
                queue_entry_time_minutes=now,
                service_start_time_minutes=now,
                service_end_time_minutes=now,
            )
        )

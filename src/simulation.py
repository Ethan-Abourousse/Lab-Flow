"""Simulation orchestration: arrivals, simulation clock, and replications.

Ties together synthetic data generation (``src/generate_data.py``) and the
laboratory workflow (``src/laboratory.py``) into runnable replications:

- An arrivals process releases each pre-generated sample into the
  laboratory at its scheduled arrival time.
- The simulation clock runs until ``config.max_simulation_minutes``, which
  is deliberately later than ``config.arrival_window_minutes`` so that
  samples still in the pipeline when arrivals stop have time to finish.
- Each replication uses an independent-but-reproducible random stream,
  seeded from ``(config.random_seed, replication_index)``. Because the seed
  does not depend on ``config.scenario_name``, two configurations that
  share the same ``random_seed`` and differ only in resource/scheduling
  parameters receive *identical* arrival streams for the same replication
  index (common random numbers), reducing variance when comparing
  scenarios in ``src/optimization.py``.
"""

from __future__ import annotations

import numpy as np
import simpy

from src.generate_data import generate_samples
from src.laboratory import Laboratory
from src.models import SimulationConfiguration, SimulationResult


def _make_replication_rng(
    config: SimulationConfiguration, replication_index: int
) -> np.random.Generator:
    """Build a reproducible RNG for one replication of ``config``."""
    return np.random.default_rng((config.random_seed, replication_index))


def _run_arrivals(env: simpy.Environment, lab: Laboratory, samples: list) -> simpy.events.Process:
    def arrivals_process():
        for sample in samples:
            delay = sample.arrival_time_minutes - env.now
            if delay > 0:
                yield env.timeout(delay)
            env.process(lab.process_sample(sample))

    return env.process(arrivals_process())


def run_simulation_replication(
    config: SimulationConfiguration, replication_index: int = 0
) -> SimulationResult:
    """Run a single, reproducible replication of ``config`` to completion."""
    rng = _make_replication_rng(config, replication_index)
    samples = generate_samples(config, rng=rng)

    env = simpy.Environment()
    lab = Laboratory(env, config, rng)
    _run_arrivals(env, lab, samples)
    env.run(until=config.max_simulation_minutes)

    return SimulationResult(
        scenario_name=config.scenario_name,
        replication_id=replication_index,
        samples=samples,
        events=lab.events,
    )


def run_replications(
    config: SimulationConfiguration, replications: int | None = None
) -> list[SimulationResult]:
    """Run ``replications`` independent replications of ``config``.

    Defaults to ``config.replications`` when not given explicitly.
    """
    n_replications = replications if replications is not None else config.replications
    return [
        run_simulation_replication(config, replication_index)
        for replication_index in range(n_replications)
    ]

"""Configuration loading and synthetic sample generation.

This module owns two closely related responsibilities:

1. Parsing ``config/baseline.json`` and ``config/scenarios.json`` into typed
   :class:`~src.models.SimulationConfiguration` instances (scenario JSON
   files only specify *overrides* relative to the baseline, merged here).
2. Generating reproducible synthetic sample arrivals from a configuration,
   per the distributions described in the project brief: exponential
   interarrival times, a configurable department mix, and a fixed urgent
   sample probability.

No real patient data, clinical diagnoses, or manufacturer specifications are
used or produced; all values are illustrative assumptions documented in
``data/assumptions.md``.
"""

from __future__ import annotations

import copy
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.models import (
    Department,
    LaboratoryResource,
    Priority,
    Sample,
    SimulationConfiguration,
)

DEFAULT_BASELINE_CONFIG_PATH = Path("config/baseline.json")
DEFAULT_SCENARIOS_CONFIG_PATH = Path("config/scenarios.json")
DEFAULT_SAMPLES_OUTPUT_PATH = Path("data/synthetic_samples.csv")


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``overrides`` onto a copy of ``base``.

    Nested dictionaries are merged key-by-key rather than replaced wholesale,
    so a scenario can override e.g. only the capacity of one resource while
    leaving its processing-time bounds untouched.
    """
    merged = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _config_dict_to_dataclass(data: dict[str, Any]) -> SimulationConfiguration:
    """Convert a raw (JSON-shaped) configuration dict into a typed dataclass."""
    converted = dict(data)

    converted["department_mix"] = {
        Department(key): value for key, value in data["department_mix"].items()
    }
    converted["centrifugation_required"] = {
        Department(key): value
        for key, value in data["centrifugation_required"].items()
    }
    converted["target_turnaround_minutes"] = {
        Priority(key): value
        for key, value in data["target_turnaround_minutes"].items()
    }
    converted["resources"] = {
        name: LaboratoryResource(**resource_spec)
        for name, resource_spec in data["resources"].items()
    }

    return SimulationConfiguration(**converted)


def load_configuration(path: str | Path = DEFAULT_BASELINE_CONFIG_PATH) -> SimulationConfiguration:
    """Load a single :class:`SimulationConfiguration` from a JSON file."""
    with open(path, encoding="utf-8") as config_file:
        data = json.load(config_file)
    return _config_dict_to_dataclass(data)


def load_scenario_configurations(
    baseline_path: str | Path = DEFAULT_BASELINE_CONFIG_PATH,
    scenarios_path: str | Path = DEFAULT_SCENARIOS_CONFIG_PATH,
) -> dict[str, SimulationConfiguration]:
    """Load the baseline plus every scenario, as a name -> configuration map.

    Each scenario entry in ``scenarios_path`` supplies a ``scenario_name``,
    a human-readable ``description``, and an ``overrides`` dict that is
    deep-merged onto the raw baseline dict before being turned into a
    :class:`SimulationConfiguration`. The returned mapping always includes
    the baseline itself, keyed by its own ``scenario_name``.
    """
    with open(baseline_path, encoding="utf-8") as baseline_file:
        baseline_data = json.load(baseline_file)

    configurations: dict[str, SimulationConfiguration] = {
        baseline_data["scenario_name"]: _config_dict_to_dataclass(baseline_data)
    }

    with open(scenarios_path, encoding="utf-8") as scenarios_file:
        scenarios_data = json.load(scenarios_file)

    for scenario in scenarios_data.get("scenarios", []):
        merged = _deep_merge(baseline_data, scenario["overrides"])
        merged["scenario_name"] = scenario["scenario_name"]
        configurations[scenario["scenario_name"]] = _config_dict_to_dataclass(merged)

    return configurations


def generate_samples(
    config: SimulationConfiguration,
    rng: np.random.Generator | None = None,
) -> list[Sample]:
    """Generate a reproducible list of synthetic samples for one replication.

    Arrivals follow a Poisson process (exponentially distributed
    interarrival times) with mean rate ``config.arrival_rate_per_hour``,
    generated only within ``config.arrival_window_minutes`` (the laboratory
    keeps processing already-arrived samples after that point, but no new
    ones are created). Department and priority are drawn independently per
    sample from the configured categorical distributions.

    Passing an explicit ``rng`` allows generating independent-but-aligned
    arrival streams across scenarios sharing the same baseline arrivals
    (see ``src/optimization.py``); omitting it seeds a fresh generator from
    ``config.random_seed`` for standalone reproducibility.
    """
    if rng is None:
        rng = np.random.default_rng(config.random_seed)

    departments = list(config.department_mix.keys())
    department_probabilities = [config.department_mix[dept] for dept in departments]
    mean_interarrival_minutes = 60.0 / config.arrival_rate_per_hour

    samples: list[Sample] = []
    clock_minutes = 0.0
    sample_index = 0

    while True:
        clock_minutes += rng.exponential(scale=mean_interarrival_minutes)
        if clock_minutes > config.arrival_window_minutes:
            break

        department = departments[
            rng.choice(len(departments), p=department_probabilities)
        ]
        priority = (
            Priority.URGENT
            if rng.random() < config.urgent_probability
            else Priority.ROUTINE
        )

        samples.append(
            Sample(
                sample_id=f"S-{sample_index:06d}",
                arrival_time_minutes=round(clock_minutes, 3),
                department=department,
                priority=priority,
                requires_centrifugation=config.centrifugation_required[department],
                target_turnaround_minutes=config.target_turnaround_minutes[priority],
            )
        )
        sample_index += 1

    return samples


def samples_to_dataframe(samples: list[Sample]) -> pd.DataFrame:
    """Flatten a list of :class:`Sample` into a CSV/Excel/Power BI-friendly DataFrame."""
    rows = []
    for sample in samples:
        row = asdict(sample)
        row["department"] = sample.department.value
        row["priority"] = sample.priority.value
        rows.append(row)
    return pd.DataFrame(rows)


def export_samples_to_csv(
    samples: list[Sample], path: str | Path = DEFAULT_SAMPLES_OUTPUT_PATH
) -> Path:
    """Write generated samples to a CSV file, creating parent directories as needed."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    samples_to_dataframe(samples).to_csv(output_path, index=False)
    return output_path


def main() -> None:
    """Generate the baseline synthetic dataset and write it to CSV (CLI entry point)."""
    config = load_configuration(DEFAULT_BASELINE_CONFIG_PATH)
    samples = generate_samples(config)
    output_path = export_samples_to_csv(samples, DEFAULT_SAMPLES_OUTPUT_PATH)

    urgent_count = sum(1 for sample in samples if sample.is_urgent)
    print(
        f"Generated {len(samples)} synthetic samples "
        f"({urgent_count} urgent, {len(samples) - urgent_count} routine) "
        f"over a {config.arrival_window_minutes:.0f}-minute arrival window."
    )
    print(f"Written to {output_path}")


if __name__ == "__main__":
    main()

"""Scenario comparison, sensitivity analysis, and multi-objective optimization.

Two complementary tools are provided:

- :func:`evaluate_all_scenarios` / :func:`rank_scenarios` run the named
  S0-S8 scenarios from ``config/scenarios.json`` (each itself a point in a
  discrete configuration "grid") for ``replications`` runs each, then rank
  them with a single weighted, normalized composite score trading off mean
  TAT, P95 TAT, urgent TAT, bottleneck utilization, and relative
  operational cost.
- :func:`grid_search_resource_capacity` performs a genuine numeric sweep of
  one resource's capacity, for sensitivity analysis beyond the predefined
  scenarios (e.g. "how many immunology analyzer units would it take to
  halve P95 TAT?").

Relative operational cost is a simple, explicitly illustrative proxy: one
cost unit per resource-capacity unit added relative to the baseline (no
real staffing or equipment costs are known or claimed).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

import pandas as pd

from src.generate_data import load_scenario_configurations
from src.kpi import ScenarioKPIs, compute_kpis, summarize_kpis, summarize_stage_kpis
from src.models import SimulationConfiguration
from src.simulation import run_replications

#: Default weights for the composite multi-objective score. All objectives
#: are normalized to [0, 1] (min-max across the compared scenarios) before
#: weighting, so these must sum to 1.0 to keep the composite score in [0, 1].
DEFAULT_OBJECTIVE_WEIGHTS = {
    "mean_turnaround_minutes": 0.25,
    "p95_turnaround_minutes": 0.25,
    "mean_urgent_turnaround_minutes": 0.25,
    "max_utilization": 0.15,
    "relative_cost": 0.10,
}


@dataclass
class ScenarioEvaluation:
    """Everything computed for one scenario: raw replications and summaries."""

    scenario_name: str
    description: str
    config: SimulationConfiguration
    kpis_list: list[ScenarioKPIs]
    summary: dict = field(repr=False)
    stage_summary: dict = field(repr=False)
    relative_cost: float = 0.0
    max_utilization: float = 0.0


def compute_relative_cost(
    config: SimulationConfiguration,
    baseline_config: SimulationConfiguration,
    unit_cost_per_resource: dict[str, float] | None = None,
) -> float:
    """Relative operational cost vs. baseline: capacity added, weighted per resource.

    ``unit_cost_per_resource`` defaults to 1.0 for every resource (all
    capacity units treated as equally costly); pass a mapping to reflect
    e.g. a more expensive analyzer unit, if such an assumption is made
    explicit elsewhere (see ``data/assumptions.md``).
    """
    unit_cost_per_resource = unit_cost_per_resource or {}
    cost = 0.0
    for name, spec in config.resources.items():
        baseline_capacity = baseline_config.resources[name].capacity
        unit_cost = unit_cost_per_resource.get(name, 1.0)
        cost += max(0, spec.capacity - baseline_capacity) * unit_cost
    return cost


def evaluate_scenario(
    scenario_name: str,
    description: str,
    config: SimulationConfiguration,
    baseline_config: SimulationConfiguration,
    replications: int | None = None,
) -> ScenarioEvaluation:
    """Run ``replications`` of ``config`` and compute its KPI summaries."""
    results = run_replications(config, replications)
    kpis_list = [compute_kpis(result, config) for result in results]
    summary = summarize_kpis(kpis_list)
    stage_summary = summarize_stage_kpis(kpis_list)
    max_utilization = (
        max(stats_["utilization"]["mean"] for stats_ in stage_summary.values())
        if stage_summary
        else 0.0
    )

    return ScenarioEvaluation(
        scenario_name=scenario_name,
        description=description,
        config=config,
        kpis_list=kpis_list,
        summary=summary,
        stage_summary=stage_summary,
        relative_cost=compute_relative_cost(config, baseline_config),
        max_utilization=max_utilization,
    )


def evaluate_all_scenarios(
    baseline_path: str = "config/baseline.json",
    scenarios_path: str = "config/scenarios.json",
    replications: int | None = None,
) -> dict[str, ScenarioEvaluation]:
    """Evaluate the baseline and every scenario defined in ``scenarios_path``."""
    import json

    configurations = load_scenario_configurations(baseline_path, scenarios_path)
    baseline_config = configurations[next(iter(configurations))]

    with open(scenarios_path, encoding="utf-8") as scenarios_file:
        descriptions = {
            s["scenario_name"]: s["description"]
            for s in json.load(scenarios_file).get("scenarios", [])
        }
    descriptions.setdefault(baseline_config.scenario_name, "Baseline configuration (FIFO).")

    return {
        name: evaluate_scenario(
            name, descriptions.get(name, ""), config, baseline_config, replications
        )
        for name, config in configurations.items()
    }


def _normalize(values: dict[str, float]) -> dict[str, float]:
    """Min-max normalize a {name: value} mapping to [0, 1] (constant input -> all 0)."""
    low, high = min(values.values()), max(values.values())
    if high - low < 1e-12:
        return {name: 0.0 for name in values}
    return {name: (value - low) / (high - low) for name, value in values.items()}


def rank_scenarios(
    evaluations: dict[str, ScenarioEvaluation],
    weights: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Rank scenarios by a weighted, normalized multi-objective composite score.

    Every objective is a "lower is better" quantity (turnaround times,
    bottleneck utilization, relative cost), so the lowest composite score
    is the best trade-off under the given ``weights``.
    """
    weights = weights or DEFAULT_OBJECTIVE_WEIGHTS

    raw_objectives = {
        "mean_turnaround_minutes": {
            name: ev.summary["mean_turnaround_minutes"]["mean"] for name, ev in evaluations.items()
        },
        "p95_turnaround_minutes": {
            name: ev.summary["p95_turnaround_minutes"]["mean"] for name, ev in evaluations.items()
        },
        "mean_urgent_turnaround_minutes": {
            name: ev.summary["mean_urgent_turnaround_minutes"]["mean"]
            for name, ev in evaluations.items()
        },
        "max_utilization": {name: ev.max_utilization for name, ev in evaluations.items()},
        "relative_cost": {name: ev.relative_cost for name, ev in evaluations.items()},
    }
    normalized_objectives = {key: _normalize(values) for key, values in raw_objectives.items()}

    rows = []
    for name, ev in evaluations.items():
        composite_score = sum(
            weights[objective] * normalized_objectives[objective][name]
            for objective in weights
        )
        rows.append(
            {
                "scenario_name": name,
                "description": ev.description,
                "composite_score": composite_score,
                "mean_turnaround_minutes": raw_objectives["mean_turnaround_minutes"][name],
                "p95_turnaround_minutes": raw_objectives["p95_turnaround_minutes"][name],
                "mean_urgent_turnaround_minutes": raw_objectives["mean_urgent_turnaround_minutes"][
                    name
                ],
                "max_utilization": ev.max_utilization,
                "relative_cost": ev.relative_cost,
                "deadline_compliance_rate": ev.summary["deadline_compliance_rate"]["mean"],
            }
        )

    return pd.DataFrame(rows).sort_values("composite_score").reset_index(drop=True)


def grid_search_resource_capacity(
    base_config: SimulationConfiguration,
    resource_name: str,
    capacities: list[int],
    replications: int | None = None,
) -> pd.DataFrame:
    """Sensitivity analysis: sweep one resource's capacity, report mean KPIs.

    Uses the same ``random_seed`` as ``base_config`` for every capacity
    value (common random numbers), so differences across rows are
    attributable to the capacity change rather than arrival-stream noise.
    """
    rows = []
    for capacity in capacities:
        candidate = copy.deepcopy(base_config)
        candidate.resources[resource_name].capacity = capacity

        kpis_list = [
            compute_kpis(result, candidate)
            for result in run_replications(candidate, replications)
        ]
        summary = summarize_kpis(kpis_list)
        rows.append(
            {
                "resource_name": resource_name,
                "capacity": capacity,
                **{
                    f"{metric_name}_mean": stats_["mean"]
                    for metric_name, stats_ in summary.items()
                },
            }
        )

    return pd.DataFrame(rows)

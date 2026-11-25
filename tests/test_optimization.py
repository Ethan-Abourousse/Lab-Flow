"""Unit tests for src/optimization.py (pure computation, no simulation runs)."""

import pytest

from src.kpi import ScenarioKPIs
from src.models import Department, LaboratoryResource, Priority, SimulationConfiguration
from src.optimization import ScenarioEvaluation, compute_relative_cost, rank_scenarios


def make_config(registration_capacity: int, immunology_capacity: int) -> SimulationConfiguration:
    return SimulationConfiguration(
        scenario_name="test",
        random_seed=1,
        arrival_window_minutes=60.0,
        max_simulation_minutes=120.0,
        arrival_rate_per_hour=10.0,
        department_mix={
            Department.BIOCHEMISTRY: 0.5,
            Department.HEMATOLOGY: 0.3,
            Department.IMMUNOLOGY: 0.2,
        },
        urgent_probability=0.1,
        centrifugation_required={
            Department.BIOCHEMISTRY: True,
            Department.HEMATOLOGY: False,
            Department.IMMUNOLOGY: True,
        },
        target_turnaround_minutes={Priority.ROUTINE: 240.0, Priority.URGENT: 60.0},
        resources={
            "registration": LaboratoryResource("registration", registration_capacity, 1.0, 3.0),
            "immunology_analyzer": LaboratoryResource(
                "immunology_analyzer", immunology_capacity, 15.0, 30.0
            ),
        },
    )


def test_compute_relative_cost_is_zero_for_identical_configuration():
    baseline = make_config(registration_capacity=2, immunology_capacity=1)
    assert compute_relative_cost(baseline, baseline) == 0.0


def test_compute_relative_cost_counts_added_capacity_only():
    baseline = make_config(registration_capacity=2, immunology_capacity=2)
    # +1 registration unit, -1 immunology unit (reductions don't add cost).
    candidate = make_config(registration_capacity=3, immunology_capacity=1)

    assert compute_relative_cost(candidate, baseline) == pytest.approx(1.0)


def test_compute_relative_cost_respects_custom_unit_costs():
    baseline = make_config(registration_capacity=2, immunology_capacity=1)
    candidate = make_config(registration_capacity=2, immunology_capacity=3)

    cost = compute_relative_cost(
        candidate, baseline, unit_cost_per_resource={"immunology_analyzer": 5.0}
    )
    assert cost == pytest.approx(2 * 5.0)  # +2 immunology units at 5.0 each


def _make_evaluation(scenario_name, mean_tat, p95_tat, urgent_tat, max_utilization, relative_cost):
    def stat(value):
        return {"mean": value, "ci_low": value, "ci_high": value, "n": 1}

    summary = {
        "mean_turnaround_minutes": stat(mean_tat),
        "p95_turnaround_minutes": stat(p95_tat),
        "mean_urgent_turnaround_minutes": stat(urgent_tat),
        "deadline_compliance_rate": stat(0.95),
    }
    return ScenarioEvaluation(
        scenario_name=scenario_name,
        description=f"{scenario_name} description",
        config=None,
        kpis_list=[],
        summary=summary,
        stage_summary={},
        relative_cost=relative_cost,
        max_utilization=max_utilization,
    )


def test_rank_scenarios_orders_best_trade_off_first():
    evaluations = {
        "worse_everywhere": _make_evaluation("worse_everywhere", 100.0, 200.0, 100.0, 0.9, 5.0),
        "better_everywhere": _make_evaluation("better_everywhere", 10.0, 20.0, 10.0, 0.1, 0.0),
    }

    ranking = rank_scenarios(evaluations)

    assert ranking.iloc[0]["scenario_name"] == "better_everywhere"
    assert ranking.iloc[0]["composite_score"] < ranking.iloc[1]["composite_score"]


def test_rank_scenarios_identical_evaluations_tie_at_zero_composite_score():
    evaluations = {
        "a": _make_evaluation("a", 50.0, 90.0, 40.0, 0.3, 1.0),
        "b": _make_evaluation("b", 50.0, 90.0, 40.0, 0.3, 1.0),
    }

    ranking = rank_scenarios(evaluations)

    assert (ranking["composite_score"] == 0.0).all()

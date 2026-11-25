"""Export simulation results and KPIs to CSV, for Excel, Power BI, pandas, and Streamlit.

Produces five kinds of tables, matching the project brief:

- ``samples.csv`` / ``events.csv``: raw observations for one representative
  replication (replication 0) of a scenario, detailed enough for ad hoc
  inspection and dashboard drill-down.
- ``resource_stats.csv``: per-resource KPIs (utilization, waiting time,
  queue length), one row per replication so variability across
  replications is preserved.
- ``kpis_by_replication.csv``: scalar scenario-level KPIs, one row per
  replication.
- ``results/comparison/scenario_comparison.csv``: one row per scenario,
  with the mean and 95% confidence interval of every scalar KPI, for
  comparing optimization scenarios against the baseline.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pandas as pd

from src.generate_data import samples_to_dataframe
from src.kpi import SCALAR_KPI_FIELDS, ScenarioKPIs
from src.models import ProcessingEvent, SimulationResult

RESULTS_BASELINE_DIR = Path("results/baseline")
RESULTS_SCENARIOS_DIR = Path("results/scenarios")
RESULTS_COMPARISON_DIR = Path("results/comparison")


def events_to_dataframe(events: list[ProcessingEvent]) -> pd.DataFrame:
    """Flatten processing events, including derived waiting/service times."""
    rows = []
    for event in events:
        row = asdict(event)
        row["stage"] = event.stage.value
        row["waiting_time_minutes"] = event.waiting_time_minutes
        row["service_time_minutes"] = event.service_time_minutes
        rows.append(row)
    return pd.DataFrame(rows)


def scenario_kpis_to_dataframe(kpis_list: list[ScenarioKPIs]) -> pd.DataFrame:
    """One row per replication, scalar KPIs only (stage KPIs are a separate table)."""
    rows = [
        {
            "scenario_name": kpi.scenario_name,
            "replication_id": kpi.replication_id,
            "observed_minutes": kpi.observed_minutes,
            "samples_generated": kpi.samples_generated,
            "samples_completed": kpi.samples_completed,
            "samples_in_progress": kpi.samples_in_progress,
            **{field_name: getattr(kpi, field_name) for field_name in SCALAR_KPI_FIELDS},
        }
        for kpi in kpis_list
    ]
    return pd.DataFrame(rows)


def stage_kpis_to_dataframe(kpis_list: list[ScenarioKPIs]) -> pd.DataFrame:
    """Long-format resource statistics: one row per (replication, resource)."""
    rows = []
    for kpi in kpis_list:
        for stage_kpi in kpi.stage_kpis:
            rows.append(
                {
                    "scenario_name": kpi.scenario_name,
                    "replication_id": kpi.replication_id,
                    "resource_name": stage_kpi.resource_name,
                    "stage": stage_kpi.stage.value,
                    "sample_count": stage_kpi.sample_count,
                    "mean_waiting_minutes": stage_kpi.mean_waiting_minutes,
                    "utilization": stage_kpi.utilization,
                    "average_queue_length": stage_kpi.average_queue_length,
                }
            )
    return pd.DataFrame(rows)


def export_scenario_results(
    representative_result: SimulationResult,
    kpis_list: list[ScenarioKPIs],
    output_dir: str | Path,
) -> dict[str, Path]:
    """Write the four per-scenario tables (samples, events, resource stats, KPIs).

    ``representative_result`` supplies the raw samples/events (replication 0
    by convention); ``kpis_list`` should cover every replication so that
    resource-stats and per-replication KPI tables reflect the full set.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    paths = {
        "samples": output_dir / "samples.csv",
        "events": output_dir / "events.csv",
        "resource_stats": output_dir / "resource_stats.csv",
        "kpis_by_replication": output_dir / "kpis_by_replication.csv",
    }

    samples_to_dataframe(representative_result.samples).to_csv(paths["samples"], index=False)
    events_to_dataframe(representative_result.events).to_csv(paths["events"], index=False)
    stage_kpis_to_dataframe(kpis_list).to_csv(paths["resource_stats"], index=False)
    scenario_kpis_to_dataframe(kpis_list).to_csv(paths["kpis_by_replication"], index=False)

    return paths


def export_comparison(
    scenario_summaries: dict[str, dict],
    output_dir: str | Path = RESULTS_COMPARISON_DIR,
) -> Path:
    """Write one wide comparison row per scenario (mean + 95% CI of every KPI).

    ``scenario_summaries`` maps scenario name to the dict returned by
    ``src.kpi.summarize_kpis`` for that scenario.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for scenario_name, summary in scenario_summaries.items():
        row = {"scenario_name": scenario_name}
        for metric_name, stats_ in summary.items():
            row[f"{metric_name}_mean"] = stats_["mean"]
            row[f"{metric_name}_ci_low"] = stats_["ci_low"]
            row[f"{metric_name}_ci_high"] = stats_["ci_high"]
        rows.append(row)

    path = output_dir / "scenario_comparison.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path

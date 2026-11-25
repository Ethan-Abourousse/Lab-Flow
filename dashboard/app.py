"""LabFlow Streamlit dashboard.

Reads the CSV tables written by ``main.py`` / ``src/export.py`` under
``results/`` and presents them as an interactive, synthetic-data-only
business intelligence view: global KPIs, arrival/completion rates,
turnaround time distributions, resource utilization and bottleneck
identification, queue evolution, and a cross-scenario comparison.

Run with::

    streamlit run dashboard/app.py

If ``results/`` is empty, run ``python main.py all`` first.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

RESULTS_DIR = Path("results")
BASELINE_DIR = RESULTS_DIR / "baseline"
SCENARIOS_DIR = RESULTS_DIR / "scenarios"
COMPARISON_PATH = RESULTS_DIR / "comparison" / "scenario_comparison.csv"

#: Minutes per bin used for the arrival/completion-rate and queue-evolution
#: time series charts.
TIME_BIN_MINUTES = 30


@st.cache_data
def load_scenario_tables(scenario_dir: Path) -> dict[str, pd.DataFrame]:
    """Load the four per-scenario CSV tables, if present."""
    tables = {}
    for name in ("samples", "events", "resource_stats", "kpis_by_replication"):
        path = scenario_dir / f"{name}.csv"
        tables[name] = pd.read_csv(path) if path.exists() else pd.DataFrame()
    return tables


@st.cache_data
def load_comparison_table() -> pd.DataFrame:
    return pd.read_csv(COMPARISON_PATH) if COMPARISON_PATH.exists() else pd.DataFrame()


def discover_scenarios() -> dict[str, Path]:
    scenarios = {}
    if BASELINE_DIR.exists():
        scenarios["S0_baseline"] = BASELINE_DIR
    if SCENARIOS_DIR.exists():
        for child in sorted(SCENARIOS_DIR.iterdir()):
            if child.is_dir():
                scenarios[child.name] = child
    return scenarios


def render_global_kpis(kpis_by_replication: pd.DataFrame) -> None:
    st.subheader("Global KPIs")
    if kpis_by_replication.empty:
        st.info("No KPI data available for this scenario yet.")
        return

    means = kpis_by_replication.mean(numeric_only=True)
    columns = st.columns(6)
    columns[0].metric("Mean TAT (min)", f"{means['mean_turnaround_minutes']:.1f}")
    columns[1].metric("P95 TAT (min)", f"{means['p95_turnaround_minutes']:.1f}")
    columns[2].metric("Urgent TAT (min)", f"{means['mean_urgent_turnaround_minutes']:.1f}")
    columns[3].metric("Throughput (samples/h)", f"{means['throughput_per_hour']:.1f}")
    columns[4].metric("Deadline compliance", f"{means['deadline_compliance_rate'] * 100:.1f}%")
    columns[5].metric("Work in progress", f"{means['work_in_progress']:.1f}")


def render_arrival_and_completion_rates(samples: pd.DataFrame, events: pd.DataFrame) -> None:
    st.subheader("Arrival and completion rates over time")
    if samples.empty or events.empty:
        st.info("No sample/event data available for this scenario yet.")
        return

    arrivals = samples.copy()
    arrivals["time_bin"] = (
        arrivals["arrival_time_minutes"] // TIME_BIN_MINUTES * TIME_BIN_MINUTES
    )
    arrival_counts = arrivals.groupby("time_bin").size().rename("arrivals")

    completions = events[events["stage"] == "reporting"].copy()
    completions["time_bin"] = (
        completions["service_end_time_minutes"] // TIME_BIN_MINUTES * TIME_BIN_MINUTES
    )
    completion_counts = completions.groupby("time_bin").size().rename("completions")

    rates = pd.concat([arrival_counts, completion_counts], axis=1).fillna(0).reset_index()
    fig = px.line(
        rates,
        x="time_bin",
        y=["arrivals", "completions"],
        labels={"time_bin": "Simulation time (minutes)", "value": "Samples per bin"},
        title=f"Arrivals vs. completions (per {TIME_BIN_MINUTES}-minute bin)",
    )
    st.plotly_chart(fig, use_container_width=True)


def render_turnaround_distribution(samples: pd.DataFrame, events: pd.DataFrame) -> None:
    st.subheader("Turnaround time distribution")
    if samples.empty or events.empty:
        st.info("No sample/event data available for this scenario yet.")
        return

    completions = events[events["stage"] == "reporting"][
        ["sample_id", "service_end_time_minutes"]
    ]
    merged = samples.merge(completions, on="sample_id", how="inner")
    merged["turnaround_minutes"] = (
        merged["service_end_time_minutes"] - merged["arrival_time_minutes"]
    )

    if merged.empty:
        st.info("No completed samples to display for this scenario/filter combination.")
        return

    fig = px.histogram(
        merged,
        x="turnaround_minutes",
        color="priority",
        barmode="overlay",
        nbins=30,
        title="Turnaround time distribution by priority",
        labels={"turnaround_minutes": "Turnaround time (minutes)"},
    )
    st.plotly_chart(fig, use_container_width=True)


def render_resource_utilization_and_bottleneck(resource_stats: pd.DataFrame) -> None:
    st.subheader("Resource utilization and bottleneck identification")
    if resource_stats.empty:
        st.info("No resource statistics available for this scenario yet.")
        return

    mean_by_resource = (
        resource_stats.groupby("resource_name")[
            ["utilization", "mean_waiting_minutes", "average_queue_length"]
        ]
        .mean()
        .reset_index()
        .sort_values("utilization", ascending=False)
    )

    fig = px.bar(
        mean_by_resource,
        x="resource_name",
        y="utilization",
        title="Mean utilization by resource",
        labels={"resource_name": "Resource", "utilization": "Utilization"},
    )
    st.plotly_chart(fig, use_container_width=True)

    bottleneck = mean_by_resource.iloc[0]
    st.warning(
        f"**Bottleneck:** `{bottleneck['resource_name']}` has the highest mean "
        f"utilization ({bottleneck['utilization'] * 100:.1f}%) and a mean wait of "
        f"{bottleneck['mean_waiting_minutes']:.1f} minutes."
    )
    st.dataframe(mean_by_resource, use_container_width=True)


def render_queue_evolution(events: pd.DataFrame, resource_name: str) -> None:
    st.subheader("Queue evolution")
    if events.empty:
        st.info("No event data available for this scenario yet.")
        return

    resource_events = events[events["resource_name"] == resource_name].copy()
    if resource_events.empty:
        st.info(f"No events recorded for resource '{resource_name}'.")
        return

    resource_events["time_bin"] = (
        resource_events["queue_entry_time_minutes"] // TIME_BIN_MINUTES * TIME_BIN_MINUTES
    )
    evolution = (
        resource_events.groupby("time_bin")["waiting_time_minutes"].mean().reset_index()
    )
    fig = px.line(
        evolution,
        x="time_bin",
        y="waiting_time_minutes",
        title=f"Mean waiting time over time - {resource_name} (queue-length proxy)",
        labels={
            "time_bin": "Simulation time (minutes)",
            "waiting_time_minutes": "Mean waiting time (minutes)",
        },
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "Waiting time is used as a proxy for queue length over time (no continuous "
        "queue-occupancy sampling is recorded by the simulation; see src/kpi.py)."
    )


def render_scenario_comparison(comparison: pd.DataFrame) -> None:
    st.subheader("Comparison of optimization scenarios")
    if comparison.empty:
        st.info("No scenario comparison data yet. Run `python main.py optimize` first.")
        return

    fig = px.bar(
        comparison.sort_values("mean_turnaround_minutes_mean"),
        x="scenario_name",
        y="mean_turnaround_minutes_mean",
        error_y=comparison["mean_turnaround_minutes_ci_high"]
        - comparison["mean_turnaround_minutes_mean"],
        title="Mean turnaround time by scenario (95% CI)",
        labels={
            "scenario_name": "Scenario",
            "mean_turnaround_minutes_mean": "Mean TAT (minutes)",
        },
    )
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(comparison, use_container_width=True)


def main() -> None:
    st.set_page_config(page_title="LabFlow Dashboard", layout="wide")
    st.title("LabFlow: Laboratory Workflow Simulation Dashboard")
    st.warning(
        "All data shown is synthetic. It is generated from configurable, "
        "illustrative assumptions (see `data/assumptions.md`) and does not represent "
        "any real laboratory, patient data, or clinical diagnosis."
    )

    scenarios = discover_scenarios()
    if not scenarios:
        st.error("No results found. Run `python main.py all` to generate them.")
        return

    st.sidebar.header("Filters")
    scenario_name = st.sidebar.selectbox("Scenario", list(scenarios))
    tables = load_scenario_tables(scenarios[scenario_name])
    samples, events, resource_stats, kpis_by_replication = (
        tables["samples"],
        tables["events"],
        tables["resource_stats"],
        tables["kpis_by_replication"],
    )

    departments = sorted(samples["department"].unique()) if not samples.empty else []
    priorities = sorted(samples["priority"].unique()) if not samples.empty else []
    selected_departments = st.sidebar.multiselect("Department", departments, default=departments)
    selected_priorities = st.sidebar.multiselect("Priority", priorities, default=priorities)

    if not samples.empty:
        filtered_samples = samples[
            samples["department"].isin(selected_departments)
            & samples["priority"].isin(selected_priorities)
        ]
        filtered_events = events[events["sample_id"].isin(filtered_samples["sample_id"])]
    else:
        filtered_samples, filtered_events = samples, events

    render_global_kpis(kpis_by_replication)
    render_arrival_and_completion_rates(filtered_samples, filtered_events)
    render_turnaround_distribution(filtered_samples, filtered_events)
    render_resource_utilization_and_bottleneck(resource_stats)

    if not resource_stats.empty:
        resource_names = sorted(resource_stats["resource_name"].unique())
        default_resource = (
            resource_stats.groupby("resource_name")["utilization"].mean().idxmax()
        )
        resource_choice = st.sidebar.selectbox(
            "Resource (queue evolution)",
            resource_names,
            index=resource_names.index(default_resource),
        )
        render_queue_evolution(filtered_events, resource_choice)

    render_scenario_comparison(load_comparison_table())

    st.subheader("Data export")
    st.download_button(
        "Download filtered samples (CSV)",
        filtered_samples.to_csv(index=False).encode("utf-8"),
        file_name=f"{scenario_name}_samples_filtered.csv",
        mime="text/csv",
    )
    st.download_button(
        "Download filtered events (CSV)",
        filtered_events.to_csv(index=False).encode("utf-8"),
        file_name=f"{scenario_name}_events_filtered.csv",
        mime="text/csv",
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""LabFlow command-line entry point.

Usage::

    python main.py generate-data
    python main.py simulate [--scenario NAME] [--replications N]
    python main.py scenarios [--replications N]
    python main.py optimize [--replications N]
    python main.py all [--replications N]

Each subcommand both runs its simulation work and exports the resulting
CSV tables (samples, events, resource stats, per-replication KPIs, and,
for ``optimize``, the cross-scenario comparison), so no separate "export"
step is needed on top of them.
"""

from __future__ import annotations

import argparse
import sys

from src.generate_data import (
    DEFAULT_BASELINE_CONFIG_PATH,
    DEFAULT_SCENARIOS_CONFIG_PATH,
    export_samples_to_csv,
    generate_samples,
    load_configuration,
    load_scenario_configurations,
)
from src.export import (
    RESULTS_BASELINE_DIR,
    RESULTS_SCENARIOS_DIR,
    export_comparison,
    export_scenario_results,
)
from src.kpi import compute_kpis, summarize_kpis
from src.optimization import evaluate_all_scenarios, rank_scenarios
from src.simulation import run_replications


def cmd_generate_data(args: argparse.Namespace) -> None:
    config = load_configuration(DEFAULT_BASELINE_CONFIG_PATH)
    samples = generate_samples(config)
    output_path = export_samples_to_csv(samples)

    urgent_count = sum(1 for sample in samples if sample.is_urgent)
    print(
        f"Generated {len(samples)} synthetic samples "
        f"({urgent_count} urgent, {len(samples) - urgent_count} routine) "
        f"over a {config.arrival_window_minutes:.0f}-minute arrival window."
    )
    print(f"Written to {output_path}")


def _run_and_export_scenario(scenario_name: str, config, replications: int | None, output_dir) -> None:
    results = run_replications(config, replications)
    kpis_list = [compute_kpis(result, config) for result in results]
    summary = summarize_kpis(kpis_list)
    paths = export_scenario_results(results[0], kpis_list, output_dir)

    print(f"\n[{scenario_name}] {len(results)} replication(s) completed.")
    print(
        f"  mean TAT = {summary['mean_turnaround_minutes']['mean']:.1f} min, "
        f"P95 TAT = {summary['p95_turnaround_minutes']['mean']:.1f} min, "
        f"deadline compliance = {summary['deadline_compliance_rate']['mean'] * 100:.1f}%"
    )
    for name, path in paths.items():
        print(f"  {name}: {path}")


def cmd_simulate(args: argparse.Namespace) -> None:
    configurations = load_scenario_configurations(
        DEFAULT_BASELINE_CONFIG_PATH, DEFAULT_SCENARIOS_CONFIG_PATH
    )
    baseline_name = next(iter(configurations))
    scenario_name = args.scenario or baseline_name
    if scenario_name not in configurations:
        available = ", ".join(configurations)
        print(f"Unknown scenario '{scenario_name}'. Available: {available}", file=sys.stderr)
        raise SystemExit(1)

    config = configurations[scenario_name]
    output_dir = (
        RESULTS_BASELINE_DIR
        if scenario_name == baseline_name
        else RESULTS_SCENARIOS_DIR / scenario_name
    )
    _run_and_export_scenario(scenario_name, config, args.replications, output_dir)


def cmd_scenarios(args: argparse.Namespace) -> None:
    configurations = load_scenario_configurations(
        DEFAULT_BASELINE_CONFIG_PATH, DEFAULT_SCENARIOS_CONFIG_PATH
    )
    baseline_name = next(iter(configurations))
    for scenario_name, config in configurations.items():
        output_dir = (
            RESULTS_BASELINE_DIR
            if scenario_name == baseline_name
            else RESULTS_SCENARIOS_DIR / scenario_name
        )
        _run_and_export_scenario(scenario_name, config, args.replications, output_dir)


def cmd_optimize(args: argparse.Namespace) -> None:
    evaluations = evaluate_all_scenarios(
        DEFAULT_BASELINE_CONFIG_PATH, DEFAULT_SCENARIOS_CONFIG_PATH, args.replications
    )
    ranking = rank_scenarios(evaluations)
    comparison_path = export_comparison(
        {name: ev.summary for name, ev in evaluations.items()}
    )

    print("\nScenario ranking (best composite score first):")
    print(
        ranking[
            [
                "scenario_name",
                "composite_score",
                "mean_turnaround_minutes",
                "p95_turnaround_minutes",
                "max_utilization",
                "relative_cost",
            ]
        ].to_string(index=False)
    )
    print(f"\nComparison table written to {comparison_path}")


def cmd_all(args: argparse.Namespace) -> None:
    cmd_generate_data(args)
    cmd_scenarios(args)
    cmd_optimize(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="LabFlow: medical laboratory workflow simulation and optimization."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate_data_parser = subparsers.add_parser(
        "generate-data", help="Generate the baseline synthetic sample dataset."
    )
    generate_data_parser.set_defaults(func=cmd_generate_data)

    simulate_parser = subparsers.add_parser(
        "simulate", help="Run one scenario (baseline by default) and export its results."
    )
    simulate_parser.add_argument(
        "--scenario", default=None, help="Scenario name (defaults to the baseline)."
    )
    simulate_parser.add_argument(
        "--replications", type=int, default=None, help="Override config.replications."
    )
    simulate_parser.set_defaults(func=cmd_simulate)

    scenarios_parser = subparsers.add_parser(
        "scenarios", help="Run the baseline and every scenario, exporting each individually."
    )
    scenarios_parser.add_argument(
        "--replications", type=int, default=None, help="Override config.replications."
    )
    scenarios_parser.set_defaults(func=cmd_scenarios)

    optimize_parser = subparsers.add_parser(
        "optimize", help="Compare every scenario with a ranked, multi-objective score."
    )
    optimize_parser.add_argument(
        "--replications", type=int, default=None, help="Override config.replications."
    )
    optimize_parser.set_defaults(func=cmd_optimize)

    all_parser = subparsers.add_parser(
        "all", help="Run generate-data, scenarios, and optimize in sequence."
    )
    all_parser.add_argument(
        "--replications", type=int, default=None, help="Override config.replications."
    )
    all_parser.set_defaults(func=cmd_all)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

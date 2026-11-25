# LabFlow

**Medical laboratory workflow simulation and optimization**, built as a
personal engineering project applying discrete event simulation (DES),
industrial optimization, and Lean Six Sigma methodology to the biomedical
industry.

> ⚠️ **LabFlow uses only synthetic, illustrative data.** It does not
> reproduce any real laboratory (including Eurofins Biomnis), does not use
> real patient data, and does not provide medical diagnoses. All resource
> capacities, processing times, and cost figures are explicit modelling
> assumptions — see [`data/assumptions.md`](/Users/ethanabourousse/projects/Lab-Flow/data/assumptions.md).

## What it does

- Generates reproducible synthetic laboratory sample data.
- Simulates the full sample-processing workflow (registration → preparation
  → centrifugation → analysis → validation → report transmission) with
  SimPy, across three departments and seven shared/departmental resources.
- Models finite equipment/staff capacity, five scheduling strategies (FIFO,
  priority, EDF, fixed-interval batching, adaptive batching), and temporary
  equipment failures.
- Computes industrial KPIs (turnaround time statistics, utilization, queue
  length, WIP, deadline compliance) with confidence intervals across
  multiple replications.
- Compares 9 operational scenarios (S0 baseline + S1–S8) with a
  multi-objective, cost-aware ranking, plus targeted sensitivity sweeps.
- Exports everything to CSV for Excel, Power BI, and pandas, and presents it
  in an interactive Streamlit dashboard.
- Is structured around the Lean Six Sigma **DMAIC** methodology — see
  [`docs/dmaic_report.md`](/Users/ethanabourousse/projects/Lab-Flow/docs/dmaic_report.md) for the full analysis and recommendation.

## Repository structure

```
LabFlow/
├── main.py                  # CLI entry point
├── config/                  # baseline.json, scenarios.json (S1-S8)
├── data/                    # synthetic_samples.csv, assumptions.md
├── src/                     # models, generate_data, resources, laboratory,
│                             # scheduling, simulation, kpi, export, optimization
├── dashboard/app.py          # Streamlit dashboard
├── tests/                   # pytest suite (60 tests)
├── results/                 # baseline/, scenarios/<name>/, comparison/
└── docs/                    # methodology, validation, dmaic_report, bibliography
```

## Setup

Requires Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Usage

Run the full pipeline (generate data, simulate every scenario, rank them,
export all CSVs):

```bash
python main.py all
```

Or run individual steps:

```bash
python main.py generate-data                        # synthetic data only
python main.py simulate                              # baseline, default replications
python main.py simulate --scenario S2_increased_analyzer_capacity --replications 10
python main.py scenarios                             # every scenario, individually exported
python main.py optimize                              # ranked, multi-objective comparison
```

Launch the dashboard (after running `main.py all` at least once):

```bash
streamlit run dashboard/app.py
```

Run the test suite:

```bash
pytest
```

## Scenarios

| ID | Description |
|---|---|
| S0 | Baseline configuration (FIFO scheduling) |
| S1 | Priority-based scheduling |
| S2 | Increased analyzer capacity |
| S3 | Faster registration through automation |
| S4 | Resource redistribution |
| S5 | Adaptive centrifugation batching |
| S6 | Demand increase of 30% (stress test) |
| S7 | Temporary equipment failure (stress test) |
| S8 | Combined optimization (S1+S2+S3+S4+S5) |

See [`config/scenarios.json`](/Users/ethanabourousse/projects/Lab-Flow/config/scenarios.json) and [`docs/dmaic_report.md`](/Users/ethanabourousse/projects/Lab-Flow/docs/dmaic_report.md) for
details and results.

## Documentation

- [`docs/methodology.md`](/Users/ethanabourousse/projects/Lab-Flow/docs/methodology.md) — DES approach, module responsibilities, scheduling,
  replication/statistical methodology.
- [`docs/validation.md`](/Users/ethanabourousse/projects/Lab-Flow/docs/validation.md) — what is tested and where, plus known limitations.
- [`docs/dmaic_report.md`](/Users/ethanabourousse/projects/Lab-Flow/docs/dmaic_report.md) — the full Define-Measure-Analyze-Improve-Control
  analysis, with actual computed results.
- [`docs/bibliography.md`](/Users/ethanabourousse/projects/Lab-Flow/docs/bibliography.md) — general DES/queueing/Lean Six Sigma references.
- [`data/assumptions.md`](/Users/ethanabourousse/projects/Lab-Flow/data/assumptions.md) — every illustrative modelling assumption, explained.

## Technology stack

Python 3, SimPy, NumPy, pandas, SciPy, Matplotlib/Plotly, Streamlit, pytest.
No paid software or external APIs are required; everything runs locally.

## License

See [`LICENSE`](/Users/ethanabourousse/projects/Lab-Flow/LICENSE).

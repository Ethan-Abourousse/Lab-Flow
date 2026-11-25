# Methodology

## Discrete Event Simulation (DES)

LabFlow models the laboratory as a **discrete event simulation** using
[SimPy](https://simpy.readthedocs.io/): the system state only changes at
discrete points in time (sample arrivals, service starts/ends, batch
dispatches), and the simulation clock jumps directly from one event to the
next rather than advancing in fixed time steps. Each sample is a SimPy
*process* (a Python generator) that requests resources, waits, and records a
timestamped `ProcessingEvent` at every stage; resources (registration,
preparation, analyzers, validation, centrifuge machines) are SimPy
`Resource`/`PriorityResource` instances with finite capacity.

## Module responsibilities

- [`src/models.py`](/Users/ethanabourousse/projects/Lab-Flow/src/models.py): typed dataclasses (the data contracts every other module shares).
- [`src/generate_data.py`](/Users/ethanabourousse/projects/Lab-Flow/src/generate_data.py): configuration loading (baseline + scenario overrides) and synthetic sample generation.
- [`src/resources.py`](/Users/ethanabourousse/projects/Lab-Flow/src/resources.py): SimPy resource construction, priority-aware requests, the centrifuge batch queue, and equipment-failure processes.
- [`src/scheduling.py`](/Users/ethanabourousse/projects/Lab-Flow/src/scheduling.py): queue-discipline priority values (FIFO/priority/EDF) and centrifuge batch-dispatch policies (fixed-interval/adaptive).
- [`src/laboratory.py`](/Users/ethanabourousse/projects/Lab-Flow/src/laboratory.py): the `Laboratory` class that owns resources and routes each sample through every stage.
- [`src/simulation.py`](/Users/ethanabourousse/projects/Lab-Flow/src/simulation.py): orchestrates arrivals, the simulation clock, and reproducible replications.
- [`src/kpi.py`](/Users/ethanabourousse/projects/Lab-Flow/src/kpi.py): computes and statistically summarizes KPIs across replications.
- [`src/export.py`](/Users/ethanabourousse/projects/Lab-Flow/src/export.py): writes CSV tables for Excel/Power BI/pandas/Streamlit.
- [`src/optimization.py`](/Users/ethanabourousse/projects/Lab-Flow/src/optimization.py): multi-objective scenario ranking and resource-capacity sensitivity sweeps.
- [`dashboard/app.py`](/Users/ethanabourousse/projects/Lab-Flow/dashboard/app.py): the Streamlit business-intelligence view over the exported CSVs.

## Scheduling strategies

Two independent policy axes are implemented (see `src/scheduling.py`):

1. **Queue discipline** for individually-processed resources: FIFO (plain
   `simpy.Resource`), priority (urgent samples served first), and Earliest
   Deadline First (ordered by absolute deadline = arrival time + target
   turnaround). Priority/EDF use `simpy.PriorityResource` with
   `preempt=False`: priority only reorders the waiting queue, it never
   interrupts an in-progress service.
2. **Centrifugation batching**: fixed-interval (a batch is pulled on a
   regular timer regardless of how full it is) or adaptive (pulled as soon
   as the batch is full, an urgent sample is waiting, or the oldest sample
   exceeds a wait-time threshold).

## Replications and reproducibility

Each replication uses an independent-but-reproducible random stream, seeded
from `(config.random_seed, replication_index)` via
`numpy.random.default_rng`. Because the seed does not depend on
`scenario_name`, two configurations sharing the same `random_seed` (e.g. the
baseline and any of its scenario variants) receive **identical** arrival
streams for the same replication index. This is the **common random
numbers** variance-reduction technique: differences in KPIs between
scenarios are attributable to the configuration change being studied, not to
arrival-stream noise, which lets 30 replications produce tight confidence
intervals.

## Statistical comparison

For every scalar KPI, `src/kpi.summarize_kpis` reports the mean and a 95%
confidence interval across replications (Student's t-distribution via
`scipy.stats`, appropriate for the moderate sample sizes used here).
`src/optimization.rank_scenarios` then combines five such KPIs (mean TAT,
P95 TAT, urgent TAT, bottleneck utilization, relative cost) into a single
composite score, after min-max normalizing each one across the compared
scenarios so metrics with very different units and scales (minutes,
percentages, cost units) can be weighted together meaningfully.

## DMAIC

The project is structured around Define–Measure–Analyze–Improve–Control;
see [`docs/dmaic_report.md`](/Users/ethanabourousse/projects/Lab-Flow/docs/dmaic_report.md) for the full write-up, and the
[Streamlit dashboard](/Users/ethanabourousse/projects/Lab-Flow/dashboard/app.py) for the "Control" (ongoing monitoring) phase.

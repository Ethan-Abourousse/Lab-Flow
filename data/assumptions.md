# Data and Modelling Assumptions

LabFlow is a **synthetic, illustrative** simulation. It does not reproduce any
real laboratory's layout, staffing, throughput, or costs, and it does not use
or produce real patient data or clinical diagnoses. This document lists every
non-obvious assumption baked into the configuration and code, so the model's
limits are explicit rather than implicit.

## Workflow and departments

- Workflow: Registration → Preparation → Centrifugation (if required) →
  Analysis → Validation → Report transmission, per `src/laboratory.py`.
- Three departments: biochemistry (50% of samples), hematology (30%),
  immunology (20%). Centrifugation is required for biochemistry and
  immunology samples, not hematology. These proportions and the resource
  table below are taken directly from the project brief and are explicitly
  described there as illustrative, not real manufacturer or laboratory
  specifications.

## Resource configuration (`config/baseline.json`)

| Resource | Capacity | Processing time (min) |
|---|---|---|
| Registration | 2 | 1–3 |
| Preparation | 3 | 1–4 |
| Centrifugation | 2 machines | 10–15 per batch |
| Biochemistry analyzer | 2 | 4–8 |
| Hematology analyzer | 1 | 1–5 |
| Immunology analyzer | 1 | 15–30 |
| Validation | 2 | 1–4 |

Processing times are drawn from a continuous uniform distribution between the
listed bounds (`numpy.random.Generator.uniform`), independently per sample and
stage. This is a simplification: real processing times are more likely to
follow a distribution with a mode (e.g. triangular or log-normal); uniform was
chosen as the simplest distribution consistent with "a range of hypothetical
processing times" in the brief.

## Arrival process

- Arrivals follow a Poisson process (exponentially distributed interarrival
  times) with mean rate `arrival_rate_per_hour`.
- **Baseline rate is deliberately tuned, not arbitrary.** The immunology
  analyzer (capacity 1, 15–30 min/sample) is by far the slowest, lowest-
  capacity resource. At the originally drafted rate of 30 samples/hour, its
  utilization $\rho$ exceeds 2 (permanently growing queue, no steady state).
  The baseline rate of **10 samples/hour** keeps $\rho_{\text{immunology}}
  \approx 0.75$ (a clear but stable bottleneck), while every other resource
  stays below $\rho \approx 0.25$. This makes immunology analysis the single,
  unambiguous bottleneck for the "Analyze" phase of DMAIC, and leaves clear
  room for a genuine stress scenario (S6: +30% demand pushes
  $\rho_{\text{immunology}} \to 0.975$, i.e. the system is pushed toward -
  but not left in - instability).
- 90% of samples are routine priority, 10% urgent, per the brief.
- The arrival window (`arrival_window_minutes`, 600 min = 10 operating hours)
  is distinct from the total simulated duration
  (`max_simulation_minutes`, 1200 min): no new samples are generated after the
  arrival window closes, but the laboratory keeps processing until either
  every sample completes or the safety cap is reached.

## Centrifugation batching

- `batch_capacity: 8` samples per centrifuge run is an illustrative
  assumption; the brief gives machine count and run duration but not a batch
  size.
- Two batching strategies are implemented: fixed-interval (a batch is pulled
  every `centrifugation_fixed_interval_minutes`, win or lose) and adaptive
  (pulled as soon as the batch is full, an urgent sample is waiting, or the
  oldest sample exceeds `centrifugation_batch_wait_threshold_minutes`). The
  baseline uses fixed-interval; S5 switches to adaptive as an explicit
  improvement scenario.

## Report transmission

Report transmission is modelled as an instantaneous event (zero duration, no
resource contention) immediately after validation. This is a deliberate
simplification: the brief does not specify transmission infrastructure or
delay, and introducing an unconstrained synthetic delay would be no more
accurate than omitting it.

## Equipment failures (S7)

A failure is a single, deterministic outage: `capacity_reduction` units of a
named resource become unavailable for `duration_minutes` starting at
`start_minutes`. As a simplification, a failure does **not** interrupt a
sample already being processed; it only prevents new samples from being
assigned to the affected units once they next become free. Modelling true
mid-service equipment failure would require SimPy's preemptive resources and
is left as a possible future extension.

## Reprocessing

`Sample.requires_reprocessing` and the corresponding KPI
(`reprocessing_rate`) exist in the data model and KPI calculation, but
`src/generate_data.py` does not yet generate any reprocessed samples (always
`False`). This is an intentional Phase 1 simplification, not a bug: the field
is present so reprocessing can be added later without changing the data
model or downstream KPI/export code.

## Relative operational cost

`src/optimization.compute_relative_cost` counts one cost unit per
resource-capacity unit added relative to the baseline (capacity reductions
are not counted as savings, to keep the proxy conservative). No real
staffing or equipment costs are known or claimed; this is a deliberately
simple, explicit proxy for comparing scenarios' capital/staffing footprint,
not a financial estimate.

## KPI normalization

Throughput, utilization, and related KPIs are normalized to the full
`max_simulation_minutes` window (arrivals **and** drain time), not just the
arrival window or the time the last sample happened to finish. This keeps
comparisons fair across scenarios with different loads, at the cost of
slightly understating "instantaneous" utilization during the busiest part of
the day. Queue length and work-in-progress are derived from Little's Law
($L = \lambda W$) applied to the exact per-stage/per-system throughput and
mean sojourn time, rather than from continuous resource-occupancy sampling
(which the simulation does not currently record).

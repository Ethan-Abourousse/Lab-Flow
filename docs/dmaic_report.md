# DMAIC Report: LabFlow Baseline Analysis and Scenario Comparison

All figures below come from the repository's own reproducible runs (30
replications per scenario, common random numbers, 95% confidence intervals;
see `docs/methodology.md`). Reproduce them with:

```bash
python main.py all
```

All data is synthetic; see `data/assumptions.md` for every parameter choice.

## 1. Define

**Problem statement:** the laboratory processes samples through
Registration → Preparation → Centrifugation (if required) → Analysis →
Validation → Report transmission, with limited equipment and staff at each
stage. The objective is to identify where samples spend the most time
waiting, and to quantify how specific, low-effort operational changes
(scheduling policy, targeted capacity increases, automation, batching
policy) affect turnaround time, deadline compliance, and resource
utilization — before committing to any real investment.

**Scope:** three departments (biochemistry, hematology, immunology), seven
shared/departmental resources, nine scenarios (S0 baseline + S1-S8), 30
replications each.

## 2. Measure

Baseline (S0) performance, 30 replications:

| KPI | Value |
|---|---|
| Mean turnaround time | 36.7 min (95% CI: 34.8–38.6) |
| P95 turnaround time | 89.1 min |
| Mean urgent-sample turnaround time | 37.2 min |
| Deadline compliance | 98.5% |

Per-resource utilization and mean waiting time (baseline, averaged over
replications):

| Resource | Utilization | Mean wait (min) |
|---|---|---|
| Immunology analyzer | **37.8%** | **23.4** |
| Centrifugation | 14.1% | 9.7 |
| Biochemistry analyzer | 12.5% | 1.3 |
| Validation | 10.5% | 0.06 |
| Registration | 8.4% | 0.03 |
| Hematology analyzer | 7.7% | 0.26 |
| Preparation | 6.9% | 0.001 |

## 3. Analyze

The immunology analyzer is, by a wide margin, the system's bottleneck: it
has both the highest utilization (utilization figures are normalized to the
full arrival-plus-drain window, see `data/assumptions.md`, so the
*effective* utilization during the busy arrival window is roughly double
this) and by far the highest mean wait (23.4 min vs. under 10 min for every
other resource). This is a direct consequence of its configuration — a
single unit serving 20% of all samples at 15–30 minutes each, per the
brief's resource table — not an artifact of scheduling policy: switching to
priority scheduling alone (S1) does not change the *mean* turnaround time at
all (36.7 min, identical to baseline — because the same bottleneck exists
regardless of queue order), though it does reduce the urgent-sample mean TAT
from 37.2 to 34.1 minutes.

Centrifugation is a secondary contributor (9.7 min mean wait under the
baseline's fixed-interval batching), but far less severe than immunology
analysis.

Stress-testing confirms the diagnosis: a 30% demand increase (S6) pushes
mean TAT to 44.0 min and P95 to 128.7 min — the system is pushed toward, but
not past, instability, exactly as intended by the arrival-rate sizing
documented in `data/assumptions.md`.

## 4. Improve

Scenario comparison (mean turnaround time, lower is better):

| Scenario | Mean TAT (min) | P95 TAT (min) | Urgent TAT (min) | Deadline compliance |
|---|---|---|---|---|
| S8: Combined optimization | **30.1** | **56.5** | **24.2** | **99.97%** |
| S2: Increased analyzer capacity | 31.6 | 57.8 | 32.5 | 99.5% |
| S5: Adaptive centrifugation batching | 35.7 | 86.0 | 30.6 | 99.0% |
| S3: Faster registration | 35.7 | 89.9 | 36.0 | 98.7% |
| S0: Baseline (FIFO) | 36.7 | 89.1 | 37.2 | 98.5% |
| S1: Priority scheduling | 36.7 | 89.3 | 34.1 | 98.9% |
| S7: Temporary equipment failure | 36.9 | 88.9 | 37.3 | 98.5% |
| S4: Resource redistribution | 37.0 | 89.2 | 37.2 | 98.5% |
| S6: Demand +30% | 44.0 | 128.7 | 43.4 | 97.3% |

**S2 (increased analyzer capacity)** is the single most effective individual
lever: adding one unit each to the biochemistry, hematology, and immunology
analyzers cuts mean TAT by 14% and P95 TAT by 35%, at a relative cost of 3
capacity units (see `src/optimization.compute_relative_cost`). A targeted
sensitivity sweep on the immunology analyzer alone
(`src/optimization.grid_search_resource_capacity`) shows most of this gain
comes from going from 1 to 2 units (mean TAT 37.4 → 32.0 min), with sharply
diminishing returns from 2 to 3 units (32.0 → 31.7 min) — i.e. **one
additional immunology analyzer unit, not three analyzers' worth of
investment, captures nearly all of the achievable improvement.**

**S8 (combined: priority scheduling + increased analyzer capacity + faster
registration + resource redistribution + adaptive batching)** is the overall
best scenario on every measured KPI simultaneously, at the highest relative
cost (4 units). This is the expected result of combining complementary
improvements, and it ranks first under the default composite score in
`src/optimization.rank_scenarios` (weighting mean/P95/urgent TAT,
bottleneck utilization, and relative cost equally at 25/25/25/15/10%).

**S4 (resource redistribution)**, moving one registration staff member to
centrifugation, does **not** help: registration and centrifugation were
already far from saturated (8.4% and 14.1% utilization respectively), so
redistributing capacity there has no measurable effect on the real
bottleneck (immunology analysis). This is a useful negative result: it
demonstrates that "redistribution" is only valuable when capacity moves
*towards* the actual constraint, not away from an underused resource toward
another underused one.

## 5. Control

Ongoing monitoring is provided by the [Streamlit dashboard](/Users/ethanabourousse/projects/Lab-Flow/dashboard/app.py)
(`streamlit run dashboard/app.py`), which surfaces, per scenario: global
KPIs, arrival/completion rates over time, turnaround time distributions,
resource utilization with automatic bottleneck identification, a queue
length (waiting-time) evolution proxy, and the cross-scenario comparison
table — all clearly labelled as synthetic data, with CSV export for further
analysis in Excel or Power BI.

**Recommendation:** adopt S2 (one additional unit at each analyzer,
especially immunology) as the highest-value, lowest-complexity improvement;
treat S8's additional scheduling/automation changes as a secondary phase
once the primary bottleneck is resolved, since their marginal benefit beyond
S2 is comparatively small relative to their added operational complexity.

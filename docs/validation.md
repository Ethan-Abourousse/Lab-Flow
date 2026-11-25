# Validation, Testing, and Limitations

## What is tested, and where

60 automated tests (`pytest`, `tests/`) cover the invariants the project
brief explicitly requires:

| Invariant | Test(s) |
|---|---|
| Reproducibility with identical seeds | `test_generate_data.py::test_generate_samples_is_reproducible_with_identical_seed`, `test_simulation.py::test_reproducibility_with_identical_seed` |
| Conservation of sample counts (no loss/duplication) | `test_simulation.py::test_conservation_of_sample_counts` |
| Correct chronological ordering | `test_simulation.py::test_chronological_ordering_per_sample` |
| Non-negative waiting times | `test_resources.py`, `test_simulation.py::test_non_negative_waiting_and_service_times` |
| Resource capacity constraints | `test_simulation.py::test_resource_capacity_is_never_exceeded` (sweep-line overlap check, with centrifuge batches de-duplicated) |
| Correct sample routing | `test_simulation.py::test_centrifugation_routing_matches_department_configuration`, `test_analysis_routes_to_the_matching_department_analyzer` |
| Correct priority scheduling | `test_scheduling.py::test_priority_strategy_serves_later_urgent_request_before_earlier_routine_request`, `test_simulation.py::test_priority_strategy_reduces_mean_waiting_time_for_urgent_samples` |
| Correct KPI calculations | `test_kpi.py` (hand-computed expected values, including the centrifuge-batch utilization de-duplication) |
| No duplication or disappearance of samples | `test_simulation.py::test_conservation_of_sample_counts`, `test_generate_data.py::test_generate_samples_no_duplicate_sample_ids` |

Run the full suite with:

```bash
pytest
```

## A real bug this test suite caught

While wiring the adaptive centrifugation dispatcher to the `priority`
scheduling strategy with fast (sub-minute) processing times, the simulation
occasionally **livelocked**: `wait_remaining` (threshold minus elapsed wait)
could evaluate to a positive value smaller than floating-point resolution at
the current simulation time (e.g. `2.8e-14` when `env.now ≈ 267`), so
scheduling a `simpy.timeout` of that size never actually advanced the clock.
This was found by timing a full scenario sweep, root-caused by stepping the
SimPy event queue one event at a time, fixed with a small epsilon guard in
`src/scheduling.py`, and is now covered by a dedicated regression test
(`test_scheduling.py::test_adaptive_dispatcher_does_not_livelock_on_subepsilon_wait_remaining`).

## Known limitations

- **Reprocessing is not yet generated.** The data model and KPI support it,
  but `generate_data.py` never sets `requires_reprocessing = True`, so
  `reprocessing_rate` is currently always 0. See `data/assumptions.md`.
- **Equipment failures do not preempt in-progress service.** A failure only
  blocks *new* assignments to the affected capacity units; a sample already
  being analyzed when the failure starts will finish normally. True
  preemption would require `simpy.PreemptiveResource` and a policy for what
  happens to a partially-processed sample.
- **Queue length and WIP are Little's-Law estimates, not sampled
  time-series.** The simulation does not record continuous
  resource-occupancy; `average_queue_length` is derived as (throughput ×
  mean wait), which is exact in steady state but can be a rough proxy during
  transient/overloaded periods (see S6).
- **The relative operational cost model is a simple proxy** (one unit per
  added resource-capacity unit), not a real financial estimate — no real
  staffing or equipment costs are known or claimed.
- **Processing times are uniform**, not a more realistic skewed distribution
  (e.g. log-normal); see `data/assumptions.md`.
- **Single representative replication for samples/events CSVs.** Only
  replication 0's raw samples and events are exported per scenario (for
  dashboard drill-down); `resource_stats.csv` and `kpis_by_replication.csv`
  cover every replication.

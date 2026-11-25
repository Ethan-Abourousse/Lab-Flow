# Bibliography

LabFlow's modelling choices draw on general, publicly available discrete
event simulation (DES), queueing theory, and Lean Six Sigma references. **No
real laboratory specifications, proprietary data, or Eurofins-internal
information were used or consulted.** Resource capacities and processing
times are explicitly illustrative assumptions by the project author (see
`data/assumptions.md`), not citations to any manufacturer or facility.

## Discrete event simulation

- Banks, J., Carson, J. S., Nelson, B. L., & Nicol, D. M. *Discrete-Event
  System Simulation* (5th ed.). Pearson. — Standard graduate/undergraduate
  textbook on DES methodology, used here as the general basis for the
  simulation's event-driven structure and replication methodology.
- Law, A. M. *Simulation Modeling and Analysis* (5th ed.). McGraw-Hill. —
  Reference for replication design, confidence-interval estimation for
  simulation output, and variance-reduction techniques (including common
  random numbers, used in `src/simulation.py`).
- SimPy documentation: <https://simpy.readthedocs.io/> — the DES framework
  used throughout `src/`.

## Queueing theory

- Little, J. D. C. (1961). "A Proof for the Queuing Formula: L = λW".
  *Operations Research*, 9(3), 383–387. — Origin of Little's Law, used in
  `src/kpi.py` to derive average queue length and work-in-progress from
  measured throughput and sojourn time.

## Lean Six Sigma / DMAIC

- George, M. L., Rowlands, D., Price, M., & Maxey, J. *The Lean Six Sigma
  Pocket Toolbook*. McGraw-Hill. — General reference for the
  Define-Measure-Analyze-Improve-Control structure used in
  `docs/dmaic_report.md`.

## Clinical laboratory turnaround time (general context only)

- Clinical and Laboratory Standards Institute (CLSI) publishes general
  guidance on laboratory turnaround time measurement and quality indicators.
  LabFlow does not cite or reproduce any specific CLSI figures or
  thresholds; target turnaround times in `config/baseline.json` are
  illustrative values chosen by the project author, not values taken from
  CLSI or any other standard.

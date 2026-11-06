# Legacy change-factor sweep

These files are retained for historical reference, not as supported run entry
points:

- `run_simulation_sweep_log.py` uses the Importer interface removed by T-16 and
  cannot run against the current simulator.
- `run_simulation_sweep.py` is the old in-process monkey-patch probe. Its
  LinkEnd.put message counter is also obsolete after the November 2026 speed-ups.
- `constants_v1.py` is the old sweep-only configuration format, not a main.py
  config.

The active matrix sweep is:

```bash
python3 experiments/sweep.py experiments/sweeps/dfn_thresholds.py
```

It uses `experiments/main.py` for every simulation, `scripts/log_metrics.py` for
parsing, `scripts/sweep_metrics.py` for aggregation, and
`scripts/plot_change_factor_matrix.py` for plots. Do not add new imports of the
files in this directory; port needed ideas to the active path instead.

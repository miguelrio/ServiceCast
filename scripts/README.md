# Scripts Guide

This directory contains small analysis, plotting, and experiment-running tools.
They are intended to be run from this directory so their local imports resolve.

## Log Analysis

| Script | Purpose |
| --- | --- |
| `quick_stats.py` | Reads one or more current-format simulation logs and prints request accuracy, blocked-request, utility-gap, ServerMetric, and FIB-stability summaries. `-v` includes the detailed gap and per-router FIB statistics. |
| `plot_load.py` | Reads `OUTCOME_GAP` lines from current-format logs, reports per-server load summaries, and creates load-over-time and time-weighted load-CDF plots. |
| `log_syntax.py` | Shared line-level parser for current-format logs. It reads the optional parameter header, classifies timestamped events, and extracts gap, ServerMetric, and FIB fields. It is a library module rather than a standalone command. |
| `log_metrics.py` | Matrix-specific log aggregator used by the log-based matrix sweep. It uses `log_syntax.py` to assemble each request's gap lines and return raw metrics. |

## Change-Factor Matrix Experiments

| Script | Purpose |
| --- | --- |
| `run_simulation_sweep_log.py` | Default matrix-data collector. Runs the simulation across the configured change-factor grid, captures its logs, parses them through `log_metrics.py`, and writes a JSON matrix in `matrix_data/`. Per-cell logs are deleted unless `--keep-logs` is supplied. |
| `run_simulation_sweep.py` | Legacy in-memory, monkey-patch collector for the same matrix experiment. It is kept as an independent cross-check for the log-based collector. |
| `plot_change_factor_matrix.py` | Runs or reads a matrix sweep and renders heatmaps in `matrix_plots/`. Its default source is the log-based collector; use `--source probe` for the legacy collector. |

The current log syntax is documented in `../doc/Logging.md`. The matrix metrics
and the distinction between the log and probe collectors are documented in
`../doc/matrix_metrics_log_mode_explained.md`.
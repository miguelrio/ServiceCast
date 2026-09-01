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

## Scaling Benchmark

Measures how the simulator's cost (runtime, log size, peak memory) and workload
behaviour (requests served, blocked rate) scale with each configuration knob.

| Script | Purpose |
| --- | --- |
| `setup/constants_scaling.py` | Declares the experiment: baseline config, factorial core, one-at-a-time axes, confirmation points, and repeat counts. Pure data, no logic. |
| `run_scaling_benchmark.py` | Enumerates the matrix from the constants and runs one `measure_one.py` subprocess per cell. Writes `scaling_runtime.csv`, `manifest.json`, and a copy of the config into `results/scaling-<timestamp>/`. |
| `measure_one.py` | Runs exactly one simulation from a JSON knob set and prints one CSV row as JSON on stdout. Spawned by the runner; can also be called directly. |
| `placement.py` | Chooses the server and client nodes so that changing either count never moves the other's nodes. Library module used by `measure_one.py`. |
| `quick_look.py` | Reads only `scaling_runtime.csv` and draws self-describing first-look plots into `<csv_dir>/quick_plots/`. |

Unlike the scripts above, these run from the repository root — the runner
starts `scripts/measure_one.py` by relative path and sets `PYTHONPATH=src`.
Use an interpreter with the simulator's dependencies (simpy, tinydb, numpy)
plus matplotlib, and check the matrix before committing to a full run:

```bash
python3 scripts/run_scaling_benchmark.py --dry-run
python3 scripts/run_scaling_benchmark.py
python3 scripts/quick_look.py -d results/scaling-<timestamp>/scaling_runtime.csv
```

`--axes` and `--repeats` narrow a run, `--timeout` bounds each cell so one slow
configuration cannot stall the matrix, and `-c/--config` loads an alternative
experiment declaration — any module defining the same attributes as
`setup/constants_scaling.py`. A custom config may vary the matrix (baseline,
axes, repeats, timeout) but must keep the fixed invariants `SERVICE` and
`SERVER_LOAD_LAMBDA` at their default values: the benchmark wires exactly one
service, and the runner refuses a config that changes them. Failed or
unplaceable cells stay in the CSV with a `status` column rather than being
dropped.


## Running the scripts

### Running a sweep

You can run a simulation sweep, and read in the experimental setup
using the ```-c``` flag like this:

```python3 scripts/run_simulation_sweep_log.py -c scripts/setup/constants_v1.py ```


this will generate a directory for each run and create the JSON
results file:

```results/sweep-20260806-193542/matrix_data/sweep_data_log_first_decide.json```

This filename is produced as the output (onto stdout) of running the script.


Using the ```-c``` flag allows us to setup various experimental
configurations, and then do different sweep runs.


### Generating the plots

You can process the output of the sweep and do a plot like this:

```python3 scripts/plot_change_factor_matrix.py -d results/sweep-20260806-193542/matrix_data/sweep_data_log_first_decide.json```

which will read the JSON file and produce the plot files in the directory:

```results/sweep-20260806-193542/matrix_plots/```


### Combining the scripts

It is possible to combine the scripts in a single run, by piping them
together.  As the 
```run_simulation_sweep_log``` script outputs the JSON filename on
*stdout*, we can tell ```plot_change_factor_matrix``` to read the
filename from its *stdin* using ```-d -```.

We can now do this:

```python3 scripts/run_simulation_sweep_log.py -c scripts/setup/constants_v1.py | python3 scripts/plot_change_factor_matrix.py -d -```



### Usage

#### run\_simulation\_sweep\_log.py

```
usage: run_simulation_sweep_log.py [-h] [-l {file,stream}] [-k] [-j JOBS] [-o OUTPUT] -c CONFIG

Log-only change-factor matrix collector.

options:
  -h, --help            show this help message and exit
  -l {file,stream}, --log-mode {file,stream}
                        file: write per-cell .log then delete (default). stream: capture in memory.
  -k, --keep-logs       Keep per-cell .log files instead of deleting.
  -j JOBS, --jobs JOBS  Parallel worker processes (independent cells). Use 0 for auto (8 on this machine: cores-2).
  -o OUTPUT, --output OUTPUT
                        Output directory path for place to store JSON.
  -c CONFIG, --config CONFIG
                        Name of config file for this run
```


#### plot\_change\_factor\_matrix.py

```
usage: plot_change_factor_matrix.py [-h]
                                    [-m {created,messages,accuracy,mean_all,mean_subopt,max_error,fib_updates,blocked,accuracy_arrival,mean_arrival,announce,withdraw,recv_total,recv_announce,recv_withdraw,all} [{created,messages,accuracy,mean_all,mean_subopt,max_error,fib_updates,blocked,accuracy_arrival,mean_arrival,announce,withdraw,recv_total,recv_announce,recv_withdraw,all} ...]]
                                    [-s {log,probe}] [-d DATA_FILE]

Sweep damping parameters and plot heatmaps.

options:
  -h, --help            show this help message and exit
  -m {created,messages,accuracy,mean_all,mean_subopt,max_error,fib_updates,blocked,accuracy_arrival,mean_arrival,announce,withdraw,recv_total,recv_announce,recv_withdraw,all} [{created,messages,accuracy,mean_all,mean_subopt,max_error,fib_updates,blocked,accuracy_arrival,mean_arrival,announce,withdraw,recv_total,recv_announce,recv_withdraw,all} ...], --metrics {created,messages,accuracy,mean_all,mean_subopt,max_error,fib_updates,blocked,accuracy_arrival,mean_arrival,announce,withdraw,recv_total,recv_announce,recv_withdraw,all} [{created,messages,accuracy,mean_all,mean_subopt,max_error,fib_updates,blocked,accuracy_arrival,mean_arrival,announce,withdraw,recv_total,recv_announce,recv_withdraw,all} ...]
                        List of metrics to plot. Defaults to 'all'.
  -s {log,probe}, --source {log,probe}
                        Which collector to use on a cache miss and which default cache file to read: 'log' (purely from log text, default) or 'probe' (legacy monkey-patch
                        in-memory).
  -d DATA_FILE, --data-file DATA_FILE
                        Path to JSON results file to plot directly from.
```

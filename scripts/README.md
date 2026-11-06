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

`window_stats.py` accepts `--from`, `--to`, and `--every` in milliseconds and
reports window bounds as `from_ms` and `to_ms`. `memprobe.py` prefixes child
output with elapsed milliseconds and writes `elapsed_ms` in its RSS CSV.
Wall-clock duration fields in CSV/JSON output use the `_ms` suffix.

### Verbose levels

The simulator's verbose level (`Verbose.level`, the third argument of
`experiments/main_precomputed_t1.py`) decides what a log contains. Each level
prints everything the level below prints.

| Level | Prints |
| --- | --- |
| -2 | Silent: nothing per event, no ground-truth calculations. For timing runs. |
| -1 | Metrics: the parameter header, arrival/outcome request lines, and end-of-run `SUMMARY_` counts of ServerMetrics and per-router FIB actions. |
| 0 | + per-update lines (`PACKET_CREATED`, `RECV_PACKET`). |
| 1 | + selection-time gap lines, FIB stability lines and other decision detail. |
| 2+ | + progressively more debug detail. |

`quick_stats.py` and `plot_load.py` give the same results from a level -1 log
as from a level 1 log, at a small fraction of the size. Other scripts that
count `RECV_PACKET` or FIB lines themselves (e.g. `log_metrics.py` for the
matrix sweep) need level 1 for the complete current metric set.

**Level -1 is the expected level for large networks and long runs.** Levels
0 and above print one or more lines per update message, so they are for
detailed protocol debugging on small networks or short runs only; at scale
the logs become far too large (a 500000 ms run on 100K routers is projected at
about 25 MB at -1, 110 GB at 0 and 1.7 TB at 1). See `../doc/Logging.md`.

## Change-Factor Matrix Experiments

| Script | Purpose |
| --- | --- |
| `../experiments/sweep.py` | Default matrix-data collector. Runs one `main.py` subprocess per cell, validates its final `DONE`, parses its log through `log_metrics.py`, and writes a manifest plus the JSON matrix in `matrix_data/`. |
| `sweep_metrics.py` | Shared per-request summaries, per-cell metrics, and matrix assembly for `experiments/sweep.py`. |
| `plot_change_factor_matrix.py` | Reads the matrix JSON supplied with `-d` and renders heatmaps in `matrix_plots/`. Historical probe JSON uses the same command. |

The two obsolete collectors and their old `constants_v1.py` configuration are in
[`../legacy/`](../legacy/). They are not supported run entry points.

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
Use an interpreter with the simulator's dependencies (simpy, numpy)
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

Run the 3 x 3 DFN threshold definition from the repository root:

```bash
python3 experiments/sweep.py experiments/sweeps/dfn_thresholds.py --jobs 3
```

The sweep definition names the ordinary `main.py` base config, fixed overrides,
and the `SERVER_CF` and `ROUTER_FIB_UPT` axes. An optional `GRAPH_DELAY` axis adds
a third matrix dimension. Use `--jobs 0` for the number of cores minus two, and
`--output DIR` to choose a new output directory.

The driver writes per-cell logs, `manifest.json`, and:

```text
results/sweep-<timestamp>/matrix_data/sweep_data_log_first_decide.json
```

It prints this JSON filename on stdout. Every cell must exit zero and end its log
with `DONE`; a failed or incomplete cell prevents matrix output.


### Generating the plots

```bash
python3 scripts/plot_change_factor_matrix.py -d results/sweep-<timestamp>/matrix_data/sweep_data_log_first_decide.json
```

This produces plots in `results/sweep-<timestamp>/matrix_plots/`.


### Combining the scripts

The sweep writes the JSON filename to stdout, so the plotter can read it from
stdin using `-d -`:

```bash
python3 experiments/sweep.py experiments/sweeps/dfn_thresholds.py | python3 scripts/plot_change_factor_matrix.py -d -
```


### Usage

#### sweep.py

```text
usage: sweep.py [-h] [-j JOBS] [-o OUTPUT] definition

Run a matrix sweep through experiments/main.py.

positional arguments:
  definition            Python sweep definition file

options:
  -h, --help            show this help message and exit
  -j JOBS, --jobs JOBS  concurrent main.py processes; 0 selects cores minus two
                        (default: 1)
  -o OUTPUT, --output OUTPUT
                        new output directory (default: results/sweep-<timestamp>)
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

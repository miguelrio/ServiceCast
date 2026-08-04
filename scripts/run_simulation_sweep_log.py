#!/usr/bin/env python3
"""Log-only collector for the change-factor matrix (the default collector).

Instead of monkey-patching the simulation and reading in-memory state (the legacy
probe build in `run_simulation_sweep.py`, kept as a cross-check), it runs each
cell with the simulation's own logging on (`Verbose.level = 1`), captures the log
text, and derives every metric from it via `log_metrics.parse_log_lines`. Nothing
in the simulation or any log line is changed.

The simulation itself is *not* re-implemented: this module imports and reuses
`build_network`, `_configure_globals`, `_close_router_dbs`, `summarise_records`,
`current_git_commit`, `SIM_DURATION`, `SERVER_CFS`, and `ROUTER_CFS` from
`run_simulation_sweep.py`, so each run is identical to the probe sweep and to
`main_dfn.py` (which is left untouched as the human-readable reference).

Per cell: run -> per-cell `.log` file -> parse -> delete (default `--log-mode file`,
matching the requested write-then-delete design). `--log-mode stream` captures the
run in memory instead (no file). `--jobs N` runs independent cells in parallel.

What the parser reads (the redesigned per-request notation, see Logging.md and
log_metrics.py): each served request prints up to three gap lines -
OUTCOME_GAP (B, Verbose >= 0) carrying the arrival pair SEL_UTIL_ARR/BEST_UTIL_ARR,
plus DECISION_GAP (A) and STALENESS_ERR (C) at Verbose >= 1 carrying the
selection-time ground truth BEST_UTIL_SEL/SEL_UTIL_SEL. `log_metrics` assembles
them into the probe's (selected_sel, best_sel, selected_arr, best_arr) records.
Hence VERBOSE_LEVEL = 1: level 0 would lose A/C (no selection-time metrics) and
the SERVICE_FIB update_count lines.

The three hop metrics are named for what the log actually measures - router-side
*receptions* (`recv_total`/`recv_announce`/`recv_withdraw`), not the probe's
`LinkEnd.put` transmissions, which have no log line.
"""

import os
import sys
import io
import json
import argparse
import tempfile
import contextlib
import multiprocessing as mp
from datetime import datetime
from typing import NamedTuple
import numpy as np
import simpy

import Router as RouterModule
from tinydb.storages import MemoryStorage
import tinydb

class InMemoryTinyDB(tinydb.TinyDB):
    def __init__(self, *args, **kwargs):
        # Force MemoryStorage and discard the path argument since MemoryStorage is purely in-memory
        super().__init__(storage=MemoryStorage)

# Monkeypatch Router module's TinyDB to be in-memory
RouterModule.TinyDB = InMemoryTinyDB

from Graph import Graph
from Network import Network
from Server import Server
from Router import Router
from Generator import Generator
from Verbose import Verbose
from Utility import Utility
from Link import LinkEnd
from Gml import read_gml

from log_metrics import parse_log_lines, parse_log_file

script_path = os.path.dirname(os.path.abspath(__file__))
project_path = os.path.dirname(script_path)




# --- Fixed experiment constants -------------------------------------------------
# These define the scenario every sweep cell shares; only the swept axes
# (server_cf, router_cf, propagation_delay) vary between runs.
SIM_DURATION = 360            # simulated seconds per run
ALPHA = 0.50                  # Utility load/delay weighting
SLOTS = 50                    # server capacity
SEED = 15112022               # shared RNG seed for reproducibility
SERVICE = "§a"                # the single service every client requests

NUM_SERVERS = 5               # servers attached to core nodes
NUM_CLIENTS = 5               # clients attached to local nodes

SERVER_LOAD_LAMBDA = 55       # background-load inter-arrival; INERT here: we pass
                              # background_load=False, and Generator.py:216 (the only
                              # line that reads it) is commented out, so it has no effect
CLIENT_ARRIVAL_LAMBDA = 0.4   # mean inter-arrival time (s) between client requests
SESSION_SIZE_LAMBDA = 10      # mean session length (s)
SESSION_SIZE_SCALE = 10       # session-length multiplier (effective session ~= lambda*scale)


DELAYS = (0.1, 0.5, 1.0, 2.0, 4.0)  # A collection of delays for Links

# Metric fields, in output order. Drives both the per-cell accumulation and the
# JSON keys (matrix_<field>), so the seven metrics are named in exactly one place.
METRIC_FIELDS = ["created", "hops", "accuracy",
                 "mean_err_all", "mean_err_subopt", "max_err", "fib_updates",
                 "blocked_rate", "accuracy_arrival", "mean_err_arrival",
                 "hops_announce", "hops_withdraw"]

# Swept axes, shared so the log-based collector samples the identical grid.
# Ranges trimmed to the region where the metrics actually vary for this
# configuration (Dfn topology, Server.slots=50, this request distribution).
# Past Server.change_factor=0.32 no server ever clears its announcement
# threshold (max observed |Δload| ~0.32 = ~16/50 slots), and past
# Router.fib_utility_update_threshold=0.16 no replica's utility gap is ever
# large enough to switch the FIB (U=1-0.5*load-0.5*delay on a compact graph),
# so the upper ~two-thirds of the original axes were a flat dead zone.
SERVER_CFS = [0.0, 0.1, 0.2, 0.3]
ROUTER_CFS = [0.0, 0.1, 0.2, 0.3]


# Output order for the log build. The 9 shared metrics keep the probe's names; the
# 3 hop metrics are renamed to the honest RECV-based quantities the log provides.
LOG_METRIC_FIELDS = ["created", "recv_total", "accuracy",
                     "mean_err_all", "mean_err_subopt", "max_err", "fib_updates",
                     "blocked_rate", "accuracy_arrival", "mean_err_arrival",
                     "recv_announce", "recv_withdraw"]

VERBOSE_LEVEL = 1   # minimum level that emits every needed line
                    # (DECISION_GAP/STALENESS_ERR and SERVICE_FIB all need >= 1)



class RecordSummary(NamedTuple):
    """Selection quality derived from a run's per-request utility records."""
    accuracy: float          # % of requests that picked the optimal replica (selection time)
    mean_err_all: float      # mean |optimal - selected| utility over all requests
    mean_err_subopt: float   # mean error over suboptimal requests only
    max_err: float           # worst-case error
    accuracy_arrival: float  # % optimal judged by live state at arrival time
    mean_err_arrival: float  # mean |optimal - selected| utility judged at arrival time


def summarise_records(records):
    """Reduce per-request utility records to accuracy/error statistics.

    Each record is (selected_sel, best_sel, selected_arr, best_arr): the selected
    and best utilities at selection time and at arrival time. Selection-time stats
    measure the routing decision; arrival-time stats measure how good the pick
    looks once propagation delay has passed (decision staleness).
    """
    if not records:
        return RecordSummary(accuracy=100.0, mean_err_all=0.0, mean_err_subopt=0.0,
                             max_err=0.0, accuracy_arrival=100.0, mean_err_arrival=0.0)

    errors = [abs(best - sel) for sel, best, _, _ in records]
    arrival_errors = [abs(best - sel) for _, _, sel, best in records]

    subopt = [e for e in errors if e >= 1e-9]
    correct = sum(1 for e in errors if e < 1e-9)
    correct_arrival = sum(1 for e in arrival_errors if e < 1e-9)
    return RecordSummary(
        accuracy=correct / len(errors) * 100.0,
        mean_err_all=float(np.mean(errors)),
        mean_err_subopt=float(np.mean(subopt)) if subopt else 0.0,
        max_err=float(np.max(errors)),
        accuracy_arrival=correct_arrival / len(arrival_errors) * 100.0,
        mean_err_arrival=float(np.mean(arrival_errors)),
    )

def _configure_globals(server_cf, router_cf, hop_by_hop, propagation_delay):
    """Set the global knobs that define a single experiment. Verbose output is silenced."""
    Verbose.level = -1
    Verbose.table = 0

    Router.hop_by_hop = hop_by_hop
    Graph.default_propagation_delay = propagation_delay
    Utility.alpha = ALPHA
    Server.slots = SLOTS
    Server.change_factor = server_cf
    Router.fib_utility_update_threshold = router_cf


def current_git_commit():
    """Short hash of the code that produced the sweep data, for cache provenance."""
    try:
        result = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                cwd=project_path, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except Exception:
        return "unknown"

def build_network(env, propagation_delay):
    """Build the Dfn network ready to run: graph -> network, attach servers and clients,
    pre-compute forwarding tables, and install the load/request generators."""
    gml_file = os.path.join(project_path, "topologies/gml/Dfn.gml")
    network = Network.from_graph(read_gml(gml_file), env)

    # Core nodes (degree > 3) host servers; local nodes (degree <= 3) host clients.
    core = [r for r in network.network_nodes() if r.degree() > 3]
    local = [r for r in network.network_nodes() if r.degree() <= 3]

    servers = [f"s{s}" for s in range(1, NUM_SERVERS + 1)]
    for s, name in enumerate(servers, start=1):
        network.add_server(name, core[s], propagation_delay)

    clients = [f"c{c}" for c in range(1, NUM_CLIENTS + 1)]
    for c, name in enumerate(clients, start=1):
        network.add_client(name, local[c], propagation_delay)

    network.calculate_forwarding_tables()

    for name in servers:
        Generator.server_load_event_generator(
            network, name, [SERVICE], exponential_lambda=SERVER_LOAD_LAMBDA,
            seed=SEED, background_load=False)
    Generator.multi_client_event_generator(
        network, clients, SERVICE, arrival_lambda=CLIENT_ARRIVAL_LAMBDA,
        size_lambda=SESSION_SIZE_LAMBDA, size_scale_factor=SESSION_SIZE_SCALE, seed=SEED)

    return network


def _close_router_dbs(network):
    """Close router DBs to release file descriptors (avoids 'Too many open files')."""
    for router in network.routers.values():
        if getattr(router, 'db', None):
            router.db.close()

def recommended_jobs():
    """A sensible default worker count.

    Each cell is one independent, single-threaded simulation + parse (CPU-bound, ~1
    core, bounded memory), so the useful range is up to the core count. We leave ~2
    cores for the OS/UI so the machine stays responsive during a long sweep.
    """
    n = os.cpu_count() or 2
    return max(1, n - 2)


def resolve_jobs(jobs):
    """<=0 means 'auto' (recommended_jobs); a positive value is used as-is."""
    return recommended_jobs() if (jobs is None or jobs <= 0) else jobs


def _cell_from_metrics(lm):
    """Turn a parsed LogMetrics into the per-cell metric dict (same shape as the probe)."""
    summary = summarise_records(lm.records)
    served = len(lm.records)
    blocked_rate = lm.blocked / max(1, lm.blocked + served) * 100.0
    return {
        "created": lm.created,
        "recv_total": lm.recv_total,
        "recv_announce": lm.recv_announce,
        "recv_withdraw": lm.recv_withdraw,
        "fib_updates": lm.fib_updates,
        "blocked_rate": blocked_rate,
        **summary._asdict(),
    }


def run_single_experiment_log(server_cf, router_cf, hop_by_hop,
                              propagation_delay, log_dir, log_mode="file", keep_logs=False):
    """Run one cell with logging on, parse its log, and return (cell_dict, LogMetrics)."""
    _configure_globals(server_cf, router_cf, hop_by_hop, propagation_delay)
    Verbose.level = VERBOSE_LEVEL          # override the probe path's silent -1

    env = simpy.Environment()
    network = build_network(env, propagation_delay)

    if log_mode == "stream":
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            network.start(until=SIM_DURATION)
        lm = parse_log_lines(buf.getvalue().splitlines())
    else:  # "file": write a real per-cell log, parse it, then delete (unless kept)
        os.makedirs(log_dir, exist_ok=True)
        if keep_logs:
            name = f"cell_d{propagation_delay:g}_r{router_cf:.3f}_s{server_cf:.2f}.log"
            path = os.path.join(log_dir, name)
        else:
            fd, path = tempfile.mkstemp(suffix=".log", prefix="cell_", dir=log_dir)
            os.close(fd)
        try:
            with open(path, "w") as fh, contextlib.redirect_stdout(fh):
                network.start(until=SIM_DURATION)
            lm = parse_log_file(path)
        finally:
            if not keep_logs and os.path.exists(path):
                os.remove(path)

    _close_router_dbs(network)
    return _cell_from_metrics(lm), lm


# --- worker (top-level so it is picklable for multiprocessing) ------------------
def _worker(task):
    (k, i, j, s_cf, r_cf, delay, hop_by_hop, log_dir, log_mode, keep_logs) = task
    cell, lm = run_single_experiment_log(
        s_cf, r_cf, hop_by_hop, delay, log_dir, log_mode, keep_logs)
    served = len(lm.records)
    line = (f"Delay: {delay}, CF Server: {s_cf:.2f}, CF Router: {r_cf:.3f} => "
            f"Created: {lm.created}, Recv: {lm.recv_total} "
            f"(A:{lm.recv_announce} W:{lm.recv_withdraw}), "
            f"Acc: {cell['accuracy']:.1f}%, Blocked: {cell['blocked_rate']:.1f}%, "
            f"FIB updates: {lm.fib_updates}, served: {served}")
    return k, i, j, cell, line


def run_sweep_log(hop_by_hop, output_path=None, delays=DELAYS,
                  log_mode="file", keep_logs=False, jobs=1, log_dir=None):
    """Run the full sweep, collecting every metric purely from each run's log text."""
    delays = list(delays)
    jobs = resolve_jobs(jobs) 
    if log_dir is None:
        log_dir = os.path.join(project_path, "matrix_logs")

    mode_title = "Hop-by-Hop Anycast" if hop_by_hop else "First Decide Unicast"
    n = len(delays) * len(SERVER_CFS) * len(ROUTER_CFS)
    print(f"Starting LOG sweep ({mode_title}): "
          f"{len(delays)} delays x {len(SERVER_CFS)} cols x {len(ROUTER_CFS)} rows = {n} simulations "
          f"[log-mode={log_mode}, jobs={jobs}]...")

    shape = (len(delays), len(ROUTER_CFS), len(SERVER_CFS))
    matrices = {name: np.zeros(shape) for name in LOG_METRIC_FIELDS}

    tasks = [
        (k, i, j, s_cf, r_cf, delay, hop_by_hop, log_dir, log_mode, keep_logs)
        for k, delay in enumerate(delays)
        for i, r_cf in enumerate(ROUTER_CFS)
        for j, s_cf in enumerate(SERVER_CFS)
    ]

    def _store(result):
        k, i, j, cell, line = result
        for name in LOG_METRIC_FIELDS:
            matrices[name][k, i, j] = cell[name]
        print(line)

    done = 0
    if jobs and jobs > 1:
        with mp.Pool(processes=jobs) as pool:
            for result in pool.imap_unordered(_worker, tasks):
                _store(result)
                done += 1
                if done % 25 == 0:
                    print(f"  ... {done}/{n} cells")
    else:
        for task in tasks:
            _store(_worker(task))
            done += 1

    data = {
        "code_commit": current_git_commit(),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "log",
        "hop_by_hop": hop_by_hop,
        "delays": delays,
        "server_cfs": SERVER_CFS,
        "router_cfs": ROUTER_CFS,
        **{f"matrix_{name}": matrices[name].tolist() for name in LOG_METRIC_FIELDS},
    }

    if output_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"Log sweep results saved to: {output_path}")

    return data


def parse_args():
    p = argparse.ArgumentParser(description="Log-only change-factor matrix collector.")
    p.add_argument("--hop-by-hop", choices=["true", "false"], default="false")
    p.add_argument("--delays", nargs="+", type=float, default=[0.1, 0.5, 1.0, 2.0, 4.0])
    p.add_argument("--log-mode", choices=["file", "stream"], default="file",
                   help="file: write per-cell .log then delete (default). stream: capture in memory.")
    p.add_argument("--keep-logs", action="store_true", help="Keep per-cell .log files instead of deleting.")
    p.add_argument("--jobs", type=int, default=1,
                   help=f"Parallel worker processes (independent cells). "
                        f"Use 0 for auto ({recommended_jobs()} on this machine: cores-2).")
    p.add_argument("--output", default=None, help="Output JSON path.")
    return p.parse_args()


def main():
    args = parse_args()
    hop_by_hop = args.hop_by_hop == "true"
    if args.output:
        output_path = args.output
    else:
        mode_str = "hop_by_hop" if hop_by_hop else "first_decide"
        output_path = os.path.join(project_path, "matrix_data", f"sweep_data_log_{mode_str}.json")

    run_sweep_log(hop_by_hop, output_path, delays=args.delays,
                  log_mode=args.log_mode, keep_logs=args.keep_logs, jobs=args.jobs)


if __name__ == "__main__":
    main()

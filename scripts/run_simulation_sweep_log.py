#!/usr/bin/env python3
"""Log-only collector for the change-factor matrix (the default collector).

Instead of monkey-patching the simulation and reading in-memory state it runs each
cell with the simulation's own logging on (`Verbose.level = 1`), captures the log
text, and derives every metric from it via `log_metrics.parse_log_lines`. Nothing
in the simulation or any log line is changed.

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
"""

import os
import sys
import io
import json
import random
import argparse
import tempfile
import contextlib
import multiprocessing as mp
from datetime import datetime
from typing import NamedTuple
import numpy as np
import simpy
import Router as RouterModule
from Graph import Graph
from Network import Network
from Server import Server
from Router import Router
from Generator import Generator
from Verbose import Verbose
from Utility import Utility
from Gml import read_gml
from log_metrics import parse_log_lines, parse_log_file

import importlib.util
import importlib.machinery


config_module_name = 'config'

# import a python file
# as defined in importlib docs
def import_from_path(module_name, file_path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module




# The values of Server.change_factor, Router.fib_utility_update_threshold,
# and the Link propagation_delay are changed for each run
def _configure_globals(server_cf, router_cf, propagation_delay):
    """Set the global knobs that define a single experiment. Verbose output is silenced."""
    Verbose.level = -1
    Verbose.table = 0

    Router.hop_by_hop = config.HOP_BY_HOP
    Utility.alpha = config.ALPHA
    Server.slots = config.SLOTS

    Server.change_factor = server_cf
    Router.fib_utility_update_threshold = router_cf
    Graph.default_propagation_delay = propagation_delay

# Print parameters 
def print_simulation_parameters():
    print(f"""Simulation parameters:
    Verbose.level = {Verbose.level}
    Verbose.table = {Verbose.table}
    Router.hop_by_hop = {Router.hop_by_hop}
    Graph.default_propagation_delay = {Graph.default_propagation_delay}
    Utility.alpha = {Utility.alpha}
    Server.slots = {Server.slots}
    Server.change_factor = {Server.change_factor}
    Router.fib_utility_update_threshold = {Router.fib_utility_update_threshold}
    """)


# Short hash of the code that produced the sweep data, for cache provenance.
def current_git_commit():
    """Short hash of the code that produced the sweep data, for cache provenance."""
    project_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    try:
        result = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                cwd=project_path, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except Exception:
        return "unknown"

# 
def build_network(env, propagation_delay):
    """Build the Dfn network ready to run: graph -> network, attach servers and clients,
    pre-compute forwarding tables, and install the load/request generators."""
    project_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    gml_file = os.path.join(project_path, config.GML_FILE)
    network = Network.from_graph(read_gml(gml_file), env)

    # new code block below here that mirrors the client and server attachment logic in main_dfn_2.py
    
    # Use only low-degree local nodes for both servers and clients, and choose
    # them randomly so the sweep is not tied to the first nodes in the lists.
    local = [r for r in network.network_nodes() if r.degree() <= 3]
    needed = config.NUM_SERVERS + config.NUM_CLIENTS
    if len(local) < needed:
        raise ValueError(
            f"Not enough local nodes: need {needed}, found {len(local)}"
        )

    rng = random.Random(config.SEED)
    chosen_local_nodes = rng.sample(local, needed)

    server_nodes = chosen_local_nodes[:config.NUM_SERVERS]
    client_nodes = chosen_local_nodes[config.NUM_SERVERS:]

    servers = [f"s{s}" for s in range(1, config.NUM_SERVERS + 1)]
    for s, (name, node) in enumerate(zip(servers, server_nodes), start=1):
        network.add_server(name, node, propagation_delay)

    clients = [f"c{c}" for c in range(1, config.NUM_CLIENTS + 1)]
    for c, (name, node) in enumerate(zip(clients, client_nodes), start=1):
        network.add_client(name, node, propagation_delay)
    # end of main_dfn_2 client/server random attachment block

    network.calculate_forwarding_tables()

    for name in servers:
        Generator.server_load_event_generator(
            network, name, [config.SERVICE], exponential_lambda=config.SERVER_LOAD_LAMBDA,
            seed=config.SEED, background_load=False)
    Generator.multi_client_event_generator(
        network, clients, config.SERVICE, arrival_lambda=config.CLIENT_ARRIVAL_LAMBDA,
        size_lambda=config.SESSION_SIZE_LAMBDA, size_scale_factor=config.SESSION_SIZE_SCALE, seed=config.SEED)

    return network



def recommended_jobs():
    """A sensible default worker count.

    Each cell is one independent, single-threaded simulation + parse (CPU-bound, ~1
    core, bounded memory), so the useful range is up to the core count. We leave ~2
    cores for the OS/UI so the machine stays responsive during a long sweep.
    """
    n = os.cpu_count() or 2
    return max(1, n - 2)



# Turn a parsed LogMetrics into the per-cell metric dict (same shape as the probe).
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
        **summary
    }

def summarise_records(records):
    """Reduce per-request utility records to accuracy/error statistics.

    Each record is (selected_sel, best_sel, selected_arr, best_arr): the selected
    and best utilities at selection time and at arrival time. Selection-time stats
    measure the routing decision; arrival-time stats measure how good the pick
    looks once propagation delay has passed (decision staleness).
    """
    if not records:
        # summary is a dict
        return { "accuracy": 100.0, "mean_err_all": 0.0, "mean_err_subopt": 0.0,
                 "max_err": 0.0, "accuracy_arrival": 100.0, "mean_err_arrival": 0.0 }

    else:
        errors = [abs(best - sel) for sel, best, _, _ in records]
        arrival_errors = [abs(best - sel) for _, _, sel, best in records]

        subopt = [e for e in errors if e >= 1e-9]
        correct = sum(1 for e in errors if e < 1e-9)
        correct_arrival = sum(1 for e in arrival_errors if e < 1e-9)

        # summary is a dict
        return {
            "accuracy": correct / len(errors) * 100.0,
            "mean_err_all": float(np.mean(errors)),
            "mean_err_subopt": float(np.mean(subopt)) if subopt else 0.0,
            "max_err": float(np.max(errors)),
            "accuracy_arrival": correct_arrival / len(arrival_errors) * 100.0,
            "mean_err_arrival": float(np.mean(arrival_errors))
        }

# Close router DBs
def _close_router_dbs(network):
    """Close router DBs"""
    for router in network.routers.values():
        if getattr(router, 'db', None):
            router.db.close()

def resolve_jobs(jobs):
    """<=0 means 'auto' (recommended_jobs); a positive value is used as-is."""
    return recommended_jobs() if (jobs is None or jobs <= 0) else jobs


# Run a single experiment
# The return value becomes one cell in the resulting matrix
def run_single_experiment_log(config_spec, server_cf, router_cf, propagation_delay, log_dir, log_mode="file", keep_logs=False):
    """Run one cell with logging on, parse its log, and return (cell_dict, LogMetrics)."""
    # load module again - necessary for multiple workes
    # and python's poor multiprocessing capabilities
    
    # config_dict looks like:  { 'module_name': module_name, 'path': dirname }

    # print("Reloading module " + config_spec['module_name'], file=sys.stderr)
    config = import_from_path(config_spec['module_name'], config_spec['path'])
    globals()[config_module_name] = config

    _configure_globals(server_cf, router_cf, propagation_delay)
    Verbose.level = config.VERBOSE_LEVEL          # override the probe path's silent -1

    env = simpy.Environment()

    if log_mode == "stream":
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            print_simulation_parameters()
            network = build_network(env, propagation_delay)
            network.start(until=config.SIM_DURATION)
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
                print_simulation_parameters()
                network = build_network(env, propagation_delay)
                network.start(until=config.SIM_DURATION)
            lm = parse_log_file(path)
        finally:
            if not keep_logs and os.path.exists(path):
                os.remove(path)

    _close_router_dbs(network)
    return _cell_from_metrics(lm), lm



# --- worker (top-level so it is picklable for multiprocessing) ------------------
def worker(task):
    # unpack task values
    (k, i, j, s_cf, r_cf, delay, hop_by_hop, log_dir, log_mode, keep_logs, config_spec) = task

    # run a single experiment
    cell, lm = run_single_experiment_log(config_spec, s_cf, r_cf, delay, log_dir, log_mode, keep_logs)
    served = len(lm.records)
    line = (f"[{k},{i},{j}] "
            f"Delay: {delay}, CF Server: {s_cf:.2f}, CF Router: {r_cf:.3f} => "
            f"Created: {lm.created}, Recv: {lm.recv_total} "
            f"(A:{lm.recv_announce} W:{lm.recv_withdraw}), "
            f"Acc-arr: {cell['accuracy_arrival']:.1f}%, Blocked: {cell['blocked_rate']:.1f}%, "
            f"FIB updates: {lm.fib_updates}, served: {served}")
    return k, i, j, cell, line




# Run a sweep
# Called from main
def run_sweep_log(config_spec, output_root=None, jobs=1, log_mode="file", keep_logs=False, log_dir=None):
    """Run the full sweep, collecting every metric purely from each run's log text."""
    jobs = resolve_jobs(jobs) 

    if log_dir is None:
        raise ValueError(f"log_dir not specified")

    mode_title = "Hop-by-Hop Anycast" if config.HOP_BY_HOP else "First Decide Unicast"
    n = len(config.DELAYS) * len(config.SERVER_CFS) * len(config.ROUTER_CFS)

    # to stderr - not real data
    print(f"Starting LOG sweep ({mode_title}): "
          f"{len(config.DELAYS)} delays x {len(config.SERVER_CFS)} cols x {len(config.ROUTER_CFS)} rows = {n} simulations "
          f"[log-mode={log_mode}, jobs={jobs}]...", file=sys.stderr)

    shape = (len(config.DELAYS), len(config.ROUTER_CFS), len(config.SERVER_CFS))
    matrices = {name: np.zeros(shape) for name in config.LOG_METRIC_FIELDS}


    # generate a list of task parameters
    tasks = [
        (k, i, j, s_cf, r_cf, delay, config.HOP_BY_HOP, log_dir, log_mode, keep_logs, config_spec)
        for k, delay in enumerate(config.DELAYS)
        for i, r_cf in enumerate(config.ROUTER_CFS)
        for j, s_cf in enumerate(config.SERVER_CFS)
    ]

    # inner function
    # store a result in the matrix
    def _store(result):
        k, i, j, cell, line = result
        for name in config.LOG_METRIC_FIELDS:
            matrices[name][k, i, j] = cell[name]
        print(line)

    done = 0
    if jobs and jobs > 1:
        with mp.Pool(processes=jobs) as pool:
            for result in pool.imap_unordered(worker, tasks):
                _store(result)
                done += 1
                if done % 25 == 0:
                    print(f"  ... {done}/{n} cells")
    else:
        for task in tasks:
            _store(worker(task))
            done += 1

    # Setup data dict to then dump out as JSON
    data = {
        "code_commit": current_git_commit(),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "log",
        "hop_by_hop": config.HOP_BY_HOP,
        "delays": config.DELAYS,
        "server_cfs": config.SERVER_CFS,
        "router_cfs": config.ROUTER_CFS,
        **{f"matrix_{name}": matrices[name].tolist() for name in config.LOG_METRIC_FIELDS},
    }

    # do output
    if output_root:
        # ensure directory exists
        os.makedirs(output_root, exist_ok=True)
        
        # work out part of file name
        mode_str = "hop_by_hop" if config.HOP_BY_HOP else "first_decide"

        output_path = os.path.join(output_root, f"sweep_data_log_{mode_str}.json")
        
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"Log sweep results saved to: {output_path}", file=sys.stderr)

    # tidy up
    if not keep_logs:
        # clean away the logs directory
        os.rmdir(log_dir)
        print(f"No keep_logs, cleaned: {log_dir}", file=sys.stderr)


    return data


def parse_args():
    p = argparse.ArgumentParser(description="Log-only change-factor matrix collector.")
    p.add_argument("-l", "--log-mode", choices=["file", "stream"], default="file",
                   help="file: write per-cell .log then delete (default). stream: capture in memory.")
    p.add_argument("-k", "--keep-logs", action="store_true", help="Keep per-cell .log files instead of deleting.")
    p.add_argument("-j", "--jobs", type=int, default=1,
                   help=f"Parallel worker processes (independent cells). "
                        f"Use 0 for auto ({recommended_jobs()} on this machine: cores-2).")
    p.add_argument("-o", "--output", default=None, help="Output directory path for place to store JSON.")

    p.add_argument("-c", "--config", required=True, help="Name of config file for this run")
    # -h is help
    
    return p.parse_args()


def main():
    args = parse_args()

    # load these constants from config arg
    constants_to_import = args.config  # e.g 'scripts/setup/constants_v1.py'

    # allow imported data to be accessible via config.variable
    # global config
    config = import_from_path(config_module_name, constants_to_import)
    globals()[config_module_name] = config

    #print("CONSTANTS = " + str(config))

    project_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # print("project_path = " + str(project_path), file=sys.stderr)
    
    # setup results directory with date and time
    # and inside that matrix_logs and matrix_data
    # log_dir  is for matrix_logs
    # output_path is for matrix_data


    if args.output:
        # use passed in output path
        output_root =  os.path.join(args.output, "sweep-" + datetime.now().strftime('%Y%m%d-%H%M%S'))
        os.makedirs(output_root, exist_ok=True)
    else:
        # devise output root based on current path
        output_root =  os.path.join(project_path, "results", "sweep-" + datetime.now().strftime('%Y%m%d-%H%M%S'))
        os.makedirs(output_root, exist_ok=True)


    # set the results path
    results_path = os.path.join(output_root, "matrix_data")
    # and log_dir
    log_dir = os.path.join(output_root, "matrix_logs")
    
    # run a sweep and do logging
    config_dict = { 'module_name': config_module_name, 'path': constants_to_import }
    run_sweep_log(config_dict, output_root=results_path, jobs=args.jobs, log_mode=args.log_mode, keep_logs=args.keep_logs, log_dir=log_dir)


if __name__ == "__main__":
    main()

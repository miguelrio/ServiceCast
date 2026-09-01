#!/usr/bin/env python3
"""Measure one scaling-benchmark configuration.

One job: given a knob set, run exactly one simulation and return one CSV row's
worth of measurements. It is the subprocess child spawned by
`run_scaling_benchmark` per cell, and can also be run directly for a single
configuration.

Owns its config application end-to-end. SERVICE and SERVER_LOAD_LAMBDA come
from `setup.constants_scaling` and are fixed invariants, not knobs: the
runner refuses any -c config that changes them.

Log handling (never retain log text):
  * log_mode="file" (default for every matrix point): redirect stdout to a real
    scratch file, then after the sim: os.path.getsize for log_bytes,
    parse_log_file for the event counters, then os.remove. Only one log exists
    at a time, so peak disk is a single file. sim_s here includes genuine write
    I/O, which is what a real sweep pays.
  * log_mode="null": a counting sink that tallies bytes and lines and discards
    the text. No event counters available (the verbose=-1 twin suppresses the
    counter lines); join null rows to their file twin via (axis, config_key).

Paired file/null runs: because event counts are identical across verbose levels (verbose
guards are print-only), a verbose=-1/null run reproduces the same event sequence
as its verbose=1/file twin. Running both for every factorial point yields two
separate models -- compute cost and compute+logging+I/O cost -- and their
difference is logging's true share.

CLI: one positional arg (JSON knob set). Prints one JSON row to stdout.

Timing boundaries (time.perf_counter in this child):
  * build_s    around placement + wiring + Network.from_graph's downstream.
  * sim_s      around network.start(until=...) only. Headline number.
  * parse_s    around parse_log_file(), started only AFTER the sim timer stops,
               so parsing never contaminates simulation cost.
  * wall_s     total child wall clock. Set here to the child's own wall for
               standalone use; the parent overrides it with the subprocess wall
               (which includes the ~0.15 s interpreter startup) when collecting.
  * peak_rss_mb  resource.getrusage(RUSAGE_SELF).ru_maxrss, trustworthy because
               nothing retains log text.
"""

import os
import sys
import json
import time
import resource
import tempfile
import contextlib

import simpy

from Graph import Graph
from Network import Network
from Server import Server
from Router import Router
from Generator import Generator
from Verbose import Verbose
from Utility import Utility
from Gml import read_gml

import placement
from log_metrics import parse_log_file
from setup import constants_scaling as config


# --- log sink for null mode (counts bytes/lines, discards text) ---------------

class CountingSink:
    """A stdout stand-in that tallies bytes and lines and throws the text away."""

    def __init__(self):
        self.nbytes = 0
        self.nlines = 0

    def write(self, s):
        self.nbytes += len(s)
        self.nlines += s.count("\n")

    def flush(self):
        pass


# --- errors ------------------------------------------------------------------

class PlacementCapacityError(Exception):
    """Raised when the topology has too few local nodes for the requested counts."""


# --- config application -------------------------------------------------------

def apply_config(knobs):
    """Set every global the simulator reads, from one knob dict.

    Router.remove_fib_entry_when_all_utilities_zero is forced OFF: with it
    on, the simulator changes which requests get served, fib_updates picks
    up removal-driven updates, and null mode (verbose=-1) loses its
    near-log-free property. Feature behaviour is out of scope for this
    benchmark. (The startup REQUEST_NOT_FORWARDED guard still fires once
    for services never yet announced -- the single line null mode prints.)
    """
    Verbose.level = knobs["verbose_level"]
    Verbose.table = 0
    Router.hop_by_hop = knobs["hop_by_hop"]
    Utility.alpha = knobs["alpha"]
    Server.slots = knobs["slots"]
    Server.change_factor = knobs["server_cf"]
    Router.fib_utility_update_threshold = knobs["router_cf"]
    Graph.default_propagation_delay = knobs["prop_delay"]
    Router.remove_fib_entry_when_all_utilities_zero = False


# --- wiring (the simulator's own primitives + placement.select_nodes) --------

def build_network(knobs):
    """Read the GML, attach servers/clients via placement.select_nodes,
    pre-compute forwarding tables, and install the load/request generators."""
    project_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    gml_file = os.path.join(project_path, "topologies", "gml",
                            f"{knobs['topology']}.gml")

    env = simpy.Environment()
    network = Network.from_graph(read_gml(gml_file), env)

    # Low-degree local nodes only (exclude degree-0 nodes, which have no
    # links and would be non-functional).
    local = [r for r in network.network_nodes() if 0 < r.degree() <= 3]
    needed = knobs["num_servers"] + knobs["num_clients"]
    if len(local) < needed:
        raise PlacementCapacityError(
            f"{knobs['topology']}: need {needed} local nodes ("
            f"{knobs['num_servers']} servers + {knobs['num_clients']} clients), "
            f"found {len(local)} with 0 < degree <= 3")

    server_nodes, client_nodes = placement.select_nodes(
        local, knobs["num_servers"], knobs["num_clients"], knobs["seed"])

    server_names = [f"s{s}" for s in range(1, knobs["num_servers"] + 1)]
    client_names = [f"c{c}" for c in range(1, knobs["num_clients"] + 1)]

    # Third arg is `weight` (Network.add_server/add_client signature); the
    # older sweep scripts pass propagation_delay here, so we mirror it for
    # identical wiring.
    for name, node in zip(server_names, server_nodes):
        network.add_server(name, node, knobs["prop_delay"])
    for name, node in zip(client_names, client_nodes):
        network.add_client(name, node, knobs["prop_delay"])

    network.calculate_forwarding_tables()

    for name in server_names:
        Generator.server_load_event_generator(
            network, name, [config.SERVICE],
            exponential_lambda=config.SERVER_LOAD_LAMBDA,  # inert (background_load=False)
            seed=knobs["seed"], background_load=False)
    Generator.multi_client_event_generator(
        network, client_names, config.SERVICE,
        arrival_lambda=knobs["arrival_lambda"],
        size_lambda=knobs["session_lambda"],
        size_scale_factor=knobs["session_scale"],
        seed=knobs["seed"])

    return network


def close_router_dbs(network):
    """Close router TinyDB instances. The DBs use MemoryStorage, so this is
    hygiene, not file cleanup."""
    for router in network.routers.values():
        db = getattr(router, "db", None)
        if db is not None:
            db.close()


# --- config_key: how paired and repeated rows join ---------------------------
#
# Identifies the simulation config INDEPENDENT of log_mode, verbose, and
# repeat_idx, so the file/null twins and the repeats join cleanly. Joins are
# always on (axis, config_key), not config_key alone: the verbosity OFAT axis
# reuses the baseline config (Dfn 5/5/0.4), which is also a factorial cell, so a
# config_key-only join would match the verbosity-axis file rows to the
# factorial's null twin.

def config_key(knobs):
    return (
        knobs["topology"],
        knobs["num_servers"],
        knobs["num_clients"],
        knobs["arrival_lambda"],
        knobs["session_lambda"],
        knobs["session_scale"],
        knobs["slots"],
        knobs["sim_duration"],
        knobs["server_cf"],
        knobs["router_cf"],
        knobs["prop_delay"],
        knobs["hop_by_hop"],
        knobs["seed"],
    )


# --- peak RSS (platform-correct ru_maxrss -> MB) -----------------------------

def _peak_rss_mb():
    """ru_maxrss is bytes on macOS, kilobytes on Linux -- normalise to MB."""
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return rss / (1024.0 * 1024.0)
    return rss / 1024.0


# --- run one configuration ---------------------------------------------------

def run(knobs):
    """Run exactly one simulation from `knobs`; return one result-row dict."""
    child_start = time.perf_counter()

    # total_slots is NETWORK-wide capacity and takes precedence when present:
    # per-server slots = total // num_servers, floored. Mirrored in
    # run_scaling_benchmark.enumerate_cells so run_ids see the resolved value.
    knobs = dict(knobs)
    if knobs.get("total_slots") is not None:
        total, ns = knobs["total_slots"], knobs["num_servers"]
        if total % ns:
            print(f"warning: total_slots {total} not divisible by num_servers "
                  f"{ns}; flooring to {total // ns}/server "
                  f"({ns * (total // ns)} slots actual)", file=sys.stderr)
        knobs["slots"] = total // ns

    log_mode = knobs.get("log_mode", "file")
    row = {
        "axis": knobs.get("axis"),
        "run_id": knobs.get("run_id"),
        "repeat_idx": knobs.get("repeat_idx", 0),
        "log_mode": log_mode,
        "verbose_level": knobs["verbose_level"],
        "config_key": list(config_key(knobs)),
        # echo the knobs so each row is self-describing
        "topology": knobs["topology"],
        "num_servers": knobs["num_servers"],
        "num_clients": knobs["num_clients"],
        "arrival_lambda": knobs["arrival_lambda"],
        "session_lambda": knobs["session_lambda"],
        "session_scale": knobs["session_scale"],
        "slots": knobs["slots"],
        "total_slots": knobs.get("total_slots"),
        "sim_duration": knobs["sim_duration"],
        "server_cf": knobs["server_cf"],
        "router_cf": knobs["router_cf"],
        "prop_delay": knobs["prop_delay"],
        "hop_by_hop": knobs["hop_by_hop"],
        "alpha": knobs["alpha"],
        "seed": knobs["seed"],
        # cost fields (filled in below)
        "build_s": None,
        "sim_s": None,
        "parse_s": None,
        "log_bytes": None,
        "log_lines": None,
        "peak_rss_mb": None,
        "status": "ok",
    }

    log_path = None
    sink = None
    try:
        apply_config(knobs)

        if log_mode == "file":
            fd, log_path = tempfile.mkstemp(suffix=".log", prefix="scaling_")
            os.close(fd)
        elif log_mode == "null":
            sink = CountingSink()
        else:
            raise ValueError(f"unknown log_mode {log_mode!r}")

        build_s = None
        sim_s = None

        t_build_start = time.perf_counter()
        if log_mode == "file":
            with open(log_path, "w") as fh, contextlib.redirect_stdout(fh):
                network = build_network(knobs)
                build_s = time.perf_counter() - t_build_start
                t_sim_start = time.perf_counter()
                network.start(until=knobs["sim_duration"])
                sim_s = time.perf_counter() - t_sim_start
        else:  # null
            with contextlib.redirect_stdout(sink):
                network = build_network(knobs)
                build_s = time.perf_counter() - t_build_start
                t_sim_start = time.perf_counter()
                network.start(until=knobs["sim_duration"])
                sim_s = time.perf_counter() - t_sim_start

        close_router_dbs(network)

        row["build_s"] = build_s
        row["sim_s"] = sim_s
        row["peak_rss_mb"] = _peak_rss_mb()

        # offered load % = (1/λ) × (session_lambda × session_scale) / (num_servers × slots) × 100
        # Deterministic from config knobs, so file and null rows both carry it.
        _lam = knobs["arrival_lambda"]
        _mean_sess = knobs["session_lambda"] * knobs["session_scale"]
        _cap = knobs["num_servers"] * knobs["slots"]
        row["offered_load_pct"] = round((1.0 / _lam) * _mean_sess / _cap * 100, 2)

        if log_mode == "file":
            # parse_s started only AFTER the sim timer stops.
            t_parse_start = time.perf_counter()
            lm = parse_log_file(log_path)
            parse_s = time.perf_counter() - t_parse_start

            row["log_bytes"] = os.path.getsize(log_path)
            with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
                row["log_lines"] = sum(1 for _ in fh)
            row["parse_s"] = parse_s

            served = len(lm.records)
            blocked_rate = lm.blocked / max(1, lm.blocked + served) * 100.0
            row["created"] = lm.created
            row["recv_total"] = lm.recv_total
            row["recv_announce"] = lm.recv_announce
            row["recv_withdraw"] = lm.recv_withdraw
            row["fib_updates"] = lm.fib_updates
            row["served"] = served
            row["blocked_rate"] = blocked_rate
            row["per_server_served"] = json.dumps(lm.per_server_served, sort_keys=True)
        else:  # null: counters unavailable (verbose=-1 suppresses them)
            row["log_bytes"] = sink.nbytes
            row["log_lines"] = sink.nlines
            row["parse_s"] = 0.0

    except PlacementCapacityError as exc:
        row["status"] = "skipped:placement"
        row["error"] = str(exc)
    except Exception as exc:  # noqa: BLE001 - record any failure as a row
        row["status"] = f"error:{type(exc).__name__}"
        row["error"] = str(exc)
    finally:
        if log_path is not None and os.path.exists(log_path):
            try:
                os.remove(log_path)
            except OSError:
                pass

    child_wall = time.perf_counter() - child_start
    # wall_s: child-measured here (handy for standalone use); the parent
    # overrides it with the subprocess wall (includes ~0.15 s startup).
    row["wall_s"] = child_wall
    row["child_wall_s"] = child_wall
    return row


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Measure one scaling-benchmark configuration.")
    parser.add_argument("knobs", help="JSON-encoded knob set for one run.")
    args = parser.parse_args()

    knobs = json.loads(args.knobs)
    row = run(knobs)
    print(json.dumps(row))


if __name__ == "__main__":
    main()

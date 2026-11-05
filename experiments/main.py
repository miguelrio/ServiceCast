#!/usr/bin/env python3
# Run one ServiceCast simulation.
#
# From the repository root:
#   python3 experiments/main.py [CONFIG] [--set NAME=VALUE ...]
#   python3 experiments/main.py configs/caida_1k_s100_c100.py --set SERVER_CF=0.05 --set UNTIL=200000
#   python3 experiments/main.py configs/caida_1k_s100_c100.py --dump-config   every setting, in config form
#
# Each setting's value comes from --set if given, else from the config file,
# else from its default in the code (see src/Importer.py for the table of
# settings).  CONFIG is a Python file of NAME = value lines; it is optional,
# but the topology (GML_FILE) must be given, in the config or with --set.
# Times are in milliseconds (src/units.py).  There are no environment
# variables.  The log goes to stdout (redirect it); warnings go to stderr.
# The last line is DONE only if the run completed.
#
# The topology is a simulator-ready GML in topologies/ready/: servers and
# clients placed by the topology scripts, a provenance block and the mark
# simulatorReady 1.  Routing tables are computed at start-up
# (src/Routing.py); any tables in the GML are ignored.
#
# Verbose levels (VERBOSE_LEVEL, default -1 here; each prints everything the
# level below prints):
#   -2  silent: nothing per event, no ground-truth calculations (timing runs)
#   -1  metrics: parameter header, per-request lines and end-of-run SUMMARY_
#       counts -- enough for quick_stats.py / plot_load.py
#    0  + per-update lines (PACKET_CREATED, RECV_PACKET)
#    1  + FIB stability lines and other decision detail
#   2+  + progressively more debug detail
# Use -1 for large networks and long runs (see doc/Logging.md).

import os
import subprocess
import sys

# this checkout's code first, never another checkout's
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(REPO, "src"), os.path.join(REPO, "scripts")]

import argparse
import contextlib
import hashlib
import re
import shlex
import time

import simpy

from Importer import Importer
from Graph import Graph
from Network import Network
from Routing import Routing
from Generator import Generator
from Verbose import Verbose
from Run import Run
from Server import Server
from units import s_to_ms

READY_DIR = os.path.join(REPO, "topologies", "ready")

# the scripts that place servers, and so may mark a GML simulator-ready
PLACEMENT_SCRIPTS = ("place_servers.py", "make_zoo_gml.py")

DUMP_COMMENT = "# Settings in config form: every value is fixed here, defaults included."


def parse_args():
    parser = argparse.ArgumentParser(description="Run one ServiceCast simulation.")
    parser.add_argument("config", nargs="?", help="config file (a Python file of NAME = value lines)")
    parser.add_argument("--set", action="append", default=[], metavar="NAME=VALUE",
                        help="override a setting (repeatable); VALUE is a Python literal or a string")
    parser.add_argument("--dump-config", action="store_true",
                        help="print every resolved setting as a config file, then exit")
    return parser.parse_args()


def fail(message):
    sys.exit("experiments/main.py: " + message)


def warn(message):
    print("experiments/main.py: WARNING: " + message, file=sys.stderr)


def repo_path(path):
    """A file path as written in the log: relative to the repo root"""
    return os.path.relpath(os.path.abspath(path), REPO)


def find_file(path):
    """The absolute path of a file given relative to the current directory
    or to the repo root"""
    for candidate in (path, os.path.join(REPO, path)):
        if os.path.isfile(candidate):
            return os.path.abspath(candidate)
    fail("no such file: " + path)


def sha256(path):
    """First 16 hex characters of the file's sha256 (enough to tell files apart)"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()[:16]


def git_commit():
    """The commit of this checkout, with "+dirty" if tracked files have changed"""
    try:
        commit = subprocess.run(["git", "-C", REPO, "rev-parse", "--short", "HEAD"],
                                capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", REPO, "diff", "--quiet", "HEAD"]).returncode != 0
        return commit + ("+dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def as_list(value):
    """A GML list attribute: one entry parses as a dict, several as a list"""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def graph_attribute(gml_abs, name):
    """A graph attribute read from the GML's first lines, before any node,
    so the log header can name the sidecar without parsing the file"""
    pattern = re.compile(r'^\s*' + name + r'\s+"?([^"]*)"?\s*$')
    with open(gml_abs, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.strip() in ("node [", "edge ["):
                return None
            match = pattern.match(line)
            if match:
                return match.group(1)
    return None


def find_sidecar(gml_abs):
    """The sidecar file the GML names and its sha256, or (None, None)"""
    cones = graph_attribute(gml_abs, "observedCones")
    if not cones:
        return None, None
    sidecar = os.path.join(os.path.dirname(gml_abs), cones)
    if not os.path.isfile(sidecar):
        fail(f"{repo_path(gml_abs)} names sidecar {cones}, which is missing")
    return sidecar, sha256(sidecar)


def check_topology(meta, gml_abs, sidecar, sidecar_sha):
    """Check the GML is simulator-ready (after the log header, so that a
    log that merges stderr, as memprobe.py's does, still starts with it).

    5 Nov 2026: missing provenance, a missing simulatorReady mark and a file
    outside topologies/ready/ are WARNINGS until the topologies we use are
    rebuilt with the mark; then they become errors (agreed design)."""
    if not gml_abs.startswith(READY_DIR + os.sep):
        warn(f"{repo_path(gml_abs)} is not in topologies/ready/ (will be an error)")
    steps = as_list((meta.get("provenance") or {}).get("step"))
    if not steps:
        warn(f"{repo_path(gml_abs)} has no provenance block: not made by the topology scripts (will be an error)")
    elif not any(step.get("script") in PLACEMENT_SCRIPTS for step in steps):
        warn(f"{repo_path(gml_abs)}: no server placement step in its provenance (will be an error)")
    if str(meta.get("simulatorReady")) != "1":
        warn(f"{repo_path(gml_abs)} is not marked simulatorReady 1 (will be an error)")

    # the sidecar the GML names must match any checksum its provenance
    # recorded for it
    if not sidecar:
        return
    for step in steps:
        for out in as_list(step.get("output")):
            if os.path.basename(str(out.get("file", ""))) == os.path.basename(sidecar):
                recorded = str(out.get("sha256", ""))
                if recorded and not recorded.startswith(sidecar_sha):
                    fail(f"sidecar {repo_path(sidecar)} does not match the sha256 in the GML's provenance")


def print_header(config, gml_abs, sidecar, sidecar_sha):
    # log_syntax.py reads this block: "Simulation parameters:", then one
    # "name = value" line each, up to the generator's size_scale_factor line.
    # The run lines come first, then every setting in config form, exactly as
    # --dump-config prints it (5 Nov 2026: replaces the old Class.attr rows).
    argv = [repo_path(sys.argv[0])] + sys.argv[1:]
    print("Simulation parameters:")
    print(f"    command_line = {shlex.join(argv)}")
    print(f"    config_file = {config.config_file and repo_path(config.config_file)!r}")
    print(f"    git_commit = {git_commit()!r}")
    print(f"    gml_sha256 = {sha256(gml_abs)!r}")
    if sidecar:
        print(f"    sidecar_file = {repo_path(sidecar)!r}")
        print(f"    sidecar_sha256 = {sidecar_sha!r}")
    print("    time_unit = 'ms'")
    print("    " + DUMP_COMMENT)
    for line in config.config_lines():
        print("    " + line)
    print()


def run(config):
    if Run.gml_file is None:
        fail("no topology: give GML_FILE in the config or with --set GML_FILE=...")
    gml_abs = find_file(Run.gml_file)
    # paths in the log are relative to the repo root
    Run.gml_file = repo_path(gml_abs)

    # 1 - the log header first, before anything else is printed: a log that
    # merges stderr into stdout (memprobe.py) must still start with it
    sidecar, sidecar_sha = find_sidecar(gml_abs)
    print_header(config, gml_abs, sidecar, sidecar_sha)
    sys.stdout.flush()

    # read the topology and check it before building anything.  The reader's
    # progress lines (at VERBOSE_LEVEL >= 0) go to stderr with the warnings.
    t0 = time.perf_counter()
    with contextlib.redirect_stdout(sys.stderr):
        graph = Graph.from_gml_file(gml_abs)
    t1 = time.perf_counter()
    check_topology(graph.get_meta_data(), gml_abs, sidecar, sidecar_sha)

    # 2 - build the network: graph -> network
    env = simpy.Environment()
    network = Network.from_graph(graph, env, drop_external=False)
    # the network keeps what it needs; free the parsed graph for the run
    del graph
    t2 = time.perf_counter()

    servers = network.server_names()
    clients = network.client_names()
    print(f"load: gml {s_to_ms(t1 - t0):.3f}ms, from_graph {s_to_ms(t2 - t1):.3f}ms; "
          f"{len(network.routers)} nodes ({len(servers)} servers, {len(clients)} clients)")
    print(f"clients in gml ({len(clients)}): {clients}")
    if not servers:
        fail(f"{Run.gml_file} has no servers")
    if not clients and Run.clients != 0:
        fail(f"{Run.gml_file} has no clients (CLIENTS = 0 runs without them)")

    # 3 - routing tables, computed at start-up
    network.calculate_forwarding_tables()
    t3 = time.perf_counter()
    counts = network.routing_counts
    print(f"routing tables: {Routing.policy} for {counts['routers']} routers x "
          f"{counts['servers']} servers ({counts['entries']} entries, "
          f"{counts['unreachable_pairs']} pairs unreachable) in {s_to_ms(t3 - t2):.3f}ms")

    # 5 Nov 2026: the offered load, so an impossible one is caught at once:
    # mean sessions in progress (one request every ARRIVAL_MEAN ms, each
    # holding a slot SESSION_MEAN x SESSION_SCALE ms) over all slots
    if Run.clients != 0:
        load = Run.session_mean * Run.session_scale / (Run.arrival_mean * Server.slots * len(servers))
        print(f"offered load: {100 * load:.1f}% ({Run.session_mean * Run.session_scale:g} ms sessions, "
              f"one request every {Run.arrival_mean:g} ms, {len(servers)} servers x {Server.slots} slots)")
        if load > 1:
            warn(f"offered load {100 * load:.0f}% is above 100%: most requests will be blocked "
                 f"(check ARRIVAL_MEAN; for a load L, ARRIVAL_MEAN = "
                 f"{Run.session_mean * Run.session_scale:g} / (L x {Server.slots * len(servers)}))")

    # 4 - setup generators
    for server_name in servers:
        Generator.server_load_event_generator(network, server_name, [Run.service],
                                              seed=Run.seed, background_load=Run.server_background_load)

    if Run.clients == 0:
        # a control run: the only traffic is the servers' initial announcements
        print("CLIENTS=0: 0-client run, client request generator skipped")
    else:
        if Run.clients is not None:
            if Run.clients > len(clients):
                warn(f"CLIENTS = {Run.clients} but {Run.gml_file} has {len(clients)} clients: using all of them")
            all_clients = len(clients)
            clients = clients[:Run.clients]
            print(f"CLIENTS: using first {len(clients)} of {all_clients} clients")
        if Verbose.level <= 0:
            shown_clients = clients[:10]
            remaining_clients = len(clients) - len(shown_clients)
            suffix = f" (+{remaining_clients} more)" if remaining_clients else ""
            print(f"clients generating requests ({len(clients)}): {shown_clients}{suffix}")
        else:
            print(f"clients generating requests ({len(clients)}): {clients}")
        Generator.multi_client_event_generator(network, clients, Run.service,
                                               arrival_lambda=Run.arrival_mean,
                                               size_lambda=Run.session_mean,
                                               size_scale_factor=Run.session_scale,
                                               seed=Run.seed)

    # 5 - run
    print("RUN ----------------------------------------------------------------")
    network.start(until=Run.until)
    t4 = time.perf_counter()
    print(f"run: {s_to_ms(t4 - t3):.3f}ms wall; simulated {Run.until:g} ms (clock: ms)")
    # 5 Nov 2026: the last line of a completed run, so scripts can tell it from
    # a crashed or killed one
    print("DONE")


def main():
    args = parse_args()
    config = Importer().use_run_defaults()
    try:
        if args.config:
            # like GML_FILE: relative to the current folder or to the repo root
            config.load(find_file(args.config))
        config.override(args.set)
    except (ValueError, OSError, SyntaxError) as e:
        fail(str(e))
    config.apply()

    if args.dump_config:
        print(DUMP_COMMENT)
        for line in config.config_lines():
            print(line)
        return

    run(config)


if __name__ == "__main__":
    main()

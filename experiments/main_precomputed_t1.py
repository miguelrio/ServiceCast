
# Load a typed GML topology (routers + servers + clients in the file) and run
# a simulation. If the GML carries precomputed routing tables (per-router
# nextHop/delayMs attributes from the topology tool) they are installed
# instead of running per-router Dijkstra; otherwise the engine builds the
# tables as usual. Both paths use the same simulator logic after setup.
#
# Usage:
#   python3 main_precomputed_t1.py [gml_file] [until] [verbose_level]
# Defaults: the synthetic topology, until=360, verbose 1.
#
# Verbose levels (each prints everything the level below prints):
#   -2  silent: nothing per event, no ground-truth calculations (timing runs)
#   -1  metrics: parameter header, per-request lines (OUTCOME_GAP,
#       DECISION_GAP, STALENESS_ERR, REQUEST_NOT_FORWARDED, BLOCKED) and
#       end-of-run SUMMARY_ counts -- enough for quick_stats.py / plot_load.py
#    0  + per-update lines (PACKET_CREATED, RECV_PACKET)
#    1  + FIB stability lines and other decision detail
#   2+  + progressively more debug detail
# Use -1 for large networks and long runs; levels 0 and up are for protocol
# debugging on small networks or short runs only (see doc/Logging.md).
#
# Environment:
#   TREE_CHILDREN_ONLY=1  only send ServerMetric updates to neighbours whose
#                         unicast next hop to the replica is this router

import os
import sys
import time
from pathlib import Path

from Graph import Graph
from Network import Network
from Router import Router
from Generator import Generator
from Verbose import Verbose
from Utility import Utility
from Server import Server
from units import s_to_ms
import simpy
import random


def topology_setup():
    gml_file = sys.argv[1] if len(sys.argv) > 1 else \
        "topologies/synthetic/topology_synthetic_1788876186136.gml"
    until = float(sys.argv[2]) if len(sys.argv) > 2 else 360
    Verbose.level = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    Verbose.table = 0
    # optional trailing arguments (any order after the first three):
    #   "weighted"  engine Dijkstra with use_weights=True (delay-shortest)
    #               instead of the default min-hop; ignored when the GML
    #               carries precomputed tables
    #   a float     Server.change_factor damping threshold (default 0.01);
    #               bigger values mean load must drift further before a
    #               ServerMetric announcement is sent
    weighted = False
    floats = []
    for arg in sys.argv[4:]:
        if arg == "weighted":
            weighted = True
        else:
            floats.append(float(arg))
    # optional trailing floats: [server_change_factor [router_fib_threshold]]
    change_factor = float(os.environ.get("SERVER_CF",
                       floats[0] if len(floats) > 0 else 0.01))
    fib_threshold = floats[1] if len(floats) > 1 else 0.001

    # Set client request forwarding mode: hop-by-hop anycast (True) or
    # first-decide unicast (False)
    Router.hop_by_hop = False

    # TREE_CHILDREN_ONLY=1: only send ServerMetric updates to neighbours whose
    # unicast next hop to the replica is this router (skips sends the
    # receiver would drop as off the unicast path)
    Router.forward_to_tree_children_only = os.environ.get("TREE_CHILDREN_ONLY") == "1"

    # Default propagation delay for links without a usable GML weight
    # (attachment links to clients and servers). Engine constants are in ms
    # (src/units.py); 100 ms = 0.1 s.
    Graph.default_propagation_delay = 100

    # Set alpha value
    Utility.alpha = 0.50

    # Set slots (SERVER_SLOTS overrides; all servers share one global value)
    Server.slots = int(os.environ.get("SERVER_SLOTS", "50"))

    # Server change factor damping
    Server.change_factor = change_factor

    # Router change factor damping
    Router.fib_utility_update_threshold = fib_threshold

    print(f"""Simulation parameters:
    gml_file = {gml_file}
    until = {until}
    time_unit = ms
    Verbose.level = {Verbose.level}
    Router.hop_by_hop = {Router.hop_by_hop}
    Router.forward_to_tree_children_only = {Router.forward_to_tree_children_only}
    Graph.default_propagation_delay = {Graph.default_propagation_delay}
    Utility.alpha = {Utility.alpha}
    Server.slots = {Server.slots}
    Server.change_factor = {Server.change_factor}
    Router.fib_utility_update_threshold = {Router.fib_utility_update_threshold}
    """)

    # 1 - create the simpy environment
    env = simpy.Environment()

    # 2 - build the network: topology -> graph -> network
    t0 = time.perf_counter()
    if weighted:
        orig_dijkstra = Graph.dijkstra_algorithm
        Graph.dijkstra_algorithm = classmethod(
            lambda cls, g, start, use_weights=False: orig_dijkstra(g, start, True)
        )
    graph = Graph.from_gml_file(gml_file)
    t1 = time.perf_counter()
    network = Network.from_graph(graph, env, drop_external=False)
    t2 = time.perf_counter()

    servers = network.server_names()
    clients = network.client_names()
    print(f"load: gml {t1 - t0:.3f}s, from_graph {t2 - t1:.3f}s; "
          f"{len(network.routers)} nodes ({len(servers)} servers, {len(clients)} clients)")
    print(f"clients in gml ({len(clients)}): {clients}")

    # 3 - routing tables: precomputed from the GML if present, else the engine
    network.calculate_forwarding_tables()
    if weighted:
        Graph.dijkstra_algorithm = orig_dijkstra
    t3 = time.perf_counter()
    if network.precomputed_tables:
        print(f"routing tables: PRECOMPUTED from GML for "
              f"{len(network.precomputed_tables)} routers in {t3 - t2:.3f}s")
    else:
        mode = "weighted" if weighted else "min-hop"
        print(f"routing tables: engine Dijkstra ({mode}) for {len(network.nodes())} "
              f"nodes in {t3 - t2:.3f}s")

    # 4 - setup generators
    for server_name in servers:
        Generator.server_load_event_generator(network, server_name, ["§a"],
                                              seed=15112022, background_load=False)

    # NOCLIENTS=1: 0-client control run — skip the client request generator
    # entirely so the only control traffic is the servers' initial load=0
    # announcements (multi_client_event_generator would crash on an empty
    # client list anyway: sources_dist does gen.choice([])).
    # Mirrors the Stanford server copy.
    if os.environ.get("NOCLIENTS") == "1":
        print("NOCLIENTS=1: 0-client run, client request generator skipped")
    else:
        _tu = os.environ.get("TAU", os.environ.get("ARRIVAL_LAMBDA"))
        if _tu is not None:
            print(f"TAU override: arrival_lambda={float(_tu)}")
        if os.environ.get("NCLIENTS_USE") is not None:
            _nall = len(clients)
            clients = clients[:int(os.environ.get("NCLIENTS_USE"))]
            print(f"NCLIENTS_USE: using first {len(clients)} of {_nall} clients")
        print(f"clients generating requests ({len(clients)}): {clients}")
        # arrival_lambda is the mean inter-request time (seconds) of a single
        # Poisson process across all clients (each request goes to a random
        # client), so the total rate is 1/arrival_lambda whatever the client
        # count; session length averages size_lambda * size_scale_factor (seconds)
        _lam = float(_tu) if _tu is not None else 0.4
        Generator.multi_client_event_generator(network, clients, "§a",
                                               arrival_lambda=_lam, size_lambda=10,
                                               size_scale_factor=10, seed=15112022)

    # 5 - run
    print("RUN ----------------------------------------------------------------")
    network.start(until=until)
    t4 = time.perf_counter()
    print(f"run: {t4 - t3:.3f}s wall; simulated {until:g} s = {s_to_ms(until):g} ms (clock: ms)")


# go !
topology_setup()

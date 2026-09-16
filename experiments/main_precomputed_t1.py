
# Load a typed GML topology (routers + servers + clients in the file) and run
# a simulation. If the GML carries precomputed routing tables (per-router
# nextHop/delayMs attributes from the topology tool) they are installed
# instead of running per-router Dijkstra; otherwise the engine builds the
# tables as usual. Both paths use the same simulator logic after setup.
#
# Usage:
#   python3 main_precomputed_t1.py [gml_file] [until] [verbose_level]
# Defaults: the synthetic topology, until=360, verbose 1.

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
import simpy
import random


def topology_setup():
    gml_file = sys.argv[1] if len(sys.argv) > 1 else \
        "topologies/synthetic/topology_synthetic_1788876186136.gml"
    until = float(sys.argv[2]) if len(sys.argv) > 2 else 360
    Verbose.level = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    Verbose.table = 0
    # optional 4th argument "weighted": engine Dijkstra with use_weights=True
    # (delay-shortest) instead of the default min-hop; ignored when the GML
    # carries precomputed tables
    weighted = len(sys.argv) > 4 and sys.argv[4] == "weighted"

    # Set client request forwarding mode: hop-by-hop anycast (True) or
    # first-decide unicast (False)
    Router.hop_by_hop = False

    # Default propagation delay for links without a usable GML weight
    # (attachment links to clients and servers)
    Graph.default_propagation_delay = 0.1

    # Set alpha value
    Utility.alpha = 0.50

    # Set slots
    Server.slots = 50

    # Server change factor damping
    Server.change_factor = 0.01

    # Router change factor damping
    Router.fib_utility_update_threshold = 0.001

    print(f"""Simulation parameters:
    gml_file = {gml_file}
    until = {until}
    Verbose.level = {Verbose.level}
    Router.hop_by_hop = {Router.hop_by_hop}
    Graph.default_propagation_delay = {Graph.default_propagation_delay}
    Utility.alpha = {Utility.alpha}
    Server.slots = {Server.slots}
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

    # arrival_lambda is the mean inter-request time per client (seconds);
    # session length averages size_lambda * size_scale_factor (seconds)
    Generator.multi_client_event_generator(network, clients, "§a",
                                           arrival_lambda=0.4, size_lambda=10,
                                           size_scale_factor=10, seed=15112022)

    # 5 - run
    print("RUN ----------------------------------------------------------------")
    network.start(until=until)
    t4 = time.perf_counter()
    print(f"run: {t4 - t3:.3f}s simulated seconds={until}")


# go !
topology_setup()

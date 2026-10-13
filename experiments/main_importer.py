
# Run a simulation on a GML topology, with every setting read from a
# config file through Importer.
#
# Usage (from the repository root):
#   PYTHONPATH=src:scripts python3 experiments/main_importer.py -c scripts/setup/constants_dfn_2_importer.py
#
# The config file is a Python file. It must define every name in
# REQUIRED below; the simulator settings in it are applied through
# Importer.mappings (see src/Importer.py).
#
# Servers and clients are placed at random (seeded with SEED) on the
# low-degree (<= 3) routers of the GML, servers first, as in
# main_dfn_2.py and main_cog.py. GMLs that already contain servers,
# clients and precomputed routing tables are not handled yet (use
# main_precomputed_t1.py).
#
# The user utility function and the metric utility functions are not set
# from the config yet, so the defaults in Utility.py and MetricUtility.py
# are used (see the TODO in src/Importer.py).

import argparse
import os
import random
import sys

import simpy

from Graph import Graph
from Network import Network
from Server import Server
from Router import Router
from Generator import Generator
from Verbose import Verbose
from Utility import Utility
from Importer import Importer

repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# every name a config file must define
REQUIRED = [
    # run
    "SIM_DURATION", "VERBOSE_LEVEL", "VERBOSE_TABLE",
    # topology and placement
    "GML_FILE", "NUM_SERVERS", "NUM_CLIENTS", "SEED",
    # workload
    "SERVICE", "CLIENT_ARRIVAL_LAMBDA", "SESSION_SIZE_LAMBDA", "SESSION_SIZE_SCALE",
    # simulator settings (Importer.mappings)
    "ALPHA", "GRAPH_DELAY", "ROUTER_HOP_BY_HOP", "ROUTER_FIB_UPT",
    "ROUTER_FORWARD_TO_TREE_CHILDREN_ONLY",
    "ROUTER_REMOVE_FIB_ENTRY_WHEN_ALL_UTILITIES_ZERO",
    "SERVER_SLOTS", "SERVER_CF",
]


def repo_path(path):
    """A path as given if it exists, else relative to the repository root"""
    if os.path.exists(path):
        return path
    return os.path.join(repo_root, path)


def topology_setup(config_file):
    config = Importer(globals()).import_from_path(config_file, auto_config=True)

    missing = [name for name in REQUIRED if name not in vars(config)]
    if missing:
        raise ValueError("config file " + config_file + " does not define: " + ", ".join(missing))

    # TODO: set the utility functions from the config (see src/Importer.py);
    # until then the defaults in Utility.py and MetricUtility.py are used.

    print(f"""Simulation parameters:
    config_file = {config_file}
    gml_file = {config.GML_FILE}
    until = {config.SIM_DURATION}
    Verbose.level = {Verbose.level}
    Verbose.table = {Verbose.table}
    Router.hop_by_hop = {Router.hop_by_hop}
    Router.forward_to_tree_children_only = {Router.forward_to_tree_children_only}
    Router.remove_fib_entry_when_all_utilities_zero = {Router.remove_fib_entry_when_all_utilities_zero}
    Graph.default_propagation_delay = {Graph.default_propagation_delay}
    Utility.alpha = {Utility.alpha}
    Server.slots = {Server.slots}
    Server.change_factor = {Server.change_factor}
    Router.fib_utility_update_threshold = {Router.fib_utility_update_threshold}
    num_servers = {config.NUM_SERVERS}
    num_clients = {config.NUM_CLIENTS}
    """)

    env = simpy.Environment()

    # graph -> network
    graph = Graph.from_gml_file(repo_path(config.GML_FILE))
    network = Network.from_graph(graph, env)

    # servers and clients go on local (degree <= 3) routers, chosen at random
    local = [r for r in network.network_nodes() if r.degree() <= 3]
    needed = config.NUM_SERVERS + config.NUM_CLIENTS
    if len(local) < needed:
        raise ValueError(f"Not enough local nodes: need {needed}, found {len(local)}")

    rng = random.Random(config.SEED)
    chosen_local_nodes = rng.sample(local, needed)
    server_nodes = chosen_local_nodes[:config.NUM_SERVERS]
    client_nodes = chosen_local_nodes[config.NUM_SERVERS:]

    servers = []
    for s, server_dest in enumerate(server_nodes, start=1):
        server_name = "s" + str(s)
        servers.append(server_name)
        if Verbose.level >= 3:
            print("Add " + str(server_name) + " at " + str(server_dest))
        network.add_server(server_name, server_dest, Graph.default_propagation_delay)

    clients = []
    for c, client_dest in enumerate(client_nodes, start=1):
        client_name = "c" + str(c)
        clients.append(client_name)
        if Verbose.level >= 3:
            print("Add " + str(client_name) + " at " + str(client_dest))
        network.add_client(client_name, client_dest, Graph.default_propagation_delay)

    network.calculate_forwarding_tables()

    # generators
    for server_name in servers:
        Generator.server_load_event_generator(network, server_name, [config.SERVICE],
                                              seed=config.SEED, background_load=False)

    # CLIENT_ARRIVAL_LAMBDA is the mean time between requests across all
    # clients (one Poisson process); a session lasts on average
    # SESSION_SIZE_LAMBDA * SESSION_SIZE_SCALE seconds
    Generator.multi_client_event_generator(network, clients, config.SERVICE,
                                           arrival_lambda=config.CLIENT_ARRIVAL_LAMBDA,
                                           size_lambda=config.SESSION_SIZE_LAMBDA,
                                           size_scale_factor=config.SESSION_SIZE_SCALE,
                                           seed=config.SEED)

    if Verbose.level >= 3:
        print("RUN ----------------------------------------------------------------")
    network.start(until=config.SIM_DURATION)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a simulation from a config file.")
    parser.add_argument("-c", "--config", required=True, help="config file, e.g. scripts/setup/constants_dfn_2_importer.py")
    args = parser.parse_args()

    config_file = repo_path(args.config)
    if not os.path.exists(config_file):
        sys.exit("config file not found: " + args.config)

    topology_setup(config_file)

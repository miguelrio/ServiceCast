import os
from Graph import Graph
from Network import Network
from Server import Server
from Router import Router
from Client import Client
from Generator import Generator
from Verbose import Verbose
from Utility import Utility
from pathlib import Path
import simpy
import random
from Importer import Importer

# sclayman:
# Using a topology loaded from the DFN gml file

# v2 of main_dfn randomises the attachment of clients and servers to "local" nodes, i.e. those with degree <=3

# Use a topology from the DFN gml file

# Import config constants using the Importer
def topology_setup():
    constant_file_to_import = "scripts/setup/constants_dfn_2.py"
    config = Importer(globals()).import_from_path(constant_file_to_import, auto_config=True)
    
    print(f"""Simulation parameters:
    Verbose.level = {Verbose.level}
    Verbose.table = {Verbose.table}
    Router.hop_by_hop = {Router.hop_by_hop}
    Graph.default_propagation_delay = {Graph.default_propagation_delay}
    Utility.alpha = {Utility.alpha}
    Server.slots = {Server.slots}
    Server.change_factor = {Server.change_factor}
    Router.fib_utility_update_threshold = {Router.fib_utility_update_threshold}
    SIM_DURATION = {config.SIM_DURATION}
    SERVICE = {config.SERVICE}
    """)

    # 1 - Define the topology

    gml_file = config.GML_FILE

    if Verbose.level >= 3:
        print("Network - DFN")
        

    # 2 - create the simpy environment 
    env = simpy.Environment()

    # 3 - build the network: topology -> graph -> network

    graph = Graph.from_gml_file(gml_file)

    if Verbose.level >= 3:
        print("GRAPH")
        graph.print()

        print ("graph nodes = " + str(graph.nodes()))

        print("graph edges = " + str(graph.edges()))

    # 4 - graph -> network

    network = Network.from_graph(graph, env)

    if Verbose.level >= 3:
        print("Network nodes = " + str(network.nodes()))
        print("Network edges = " + str(network.edges()))

    # 5 - determine core and local nodes
    
    # filter out core nodes -  degree > 3
    core = [ r  for r in network.network_nodes() if r.degree() > 3 ]
    # filter out local nodes -  degree <= 3
    local = [ r  for r in network.network_nodes() if r.degree() <= 3 ]

    if Verbose.level >= 3:
        print("core  (degree > 3)  = " + str([(r.id(), r.degree()) for r in core]))
        print("local (degree <= 3) = " + str([(r.id(), r.degree()) for r in local]))


    # 6 - add servers and clients to the network
    
    if Verbose.level >= 3:
        print("--- Add Servers and Clients to Network ---")

    # add some servers
    servers = []

    # add some clients
    clients = []

    # both servers and clients are connected to local nodes
    num_servers = config.NUM_SERVERS
    num_clients = config.NUM_CLIENTS
    needed = num_servers + num_clients

    if len(local) < needed:
        raise ValueError(
            f"Not enough local nodes: need {needed}, found {len(local)}"
        )

    # fixed seed for reproducible random assignment; remove seed for different each run
    rng = random.Random(config.SEED)
    chosen_local_nodes = rng.sample(local, needed)

    server_nodes = chosen_local_nodes[:num_servers]
    client_nodes = chosen_local_nodes[num_servers:]

    for s, server_dest in enumerate(server_nodes, start=1):
        server_name = "s" + str(s)
        servers.append(server_name)

        if Verbose.level >= 3:
            print("Add " + str(server_name) + " at " + str(server_dest))

        network.add_server(server_name, server_dest, config.GRAPH_DELAY)

    for c, client_dest in enumerate(client_nodes, start=1):
        client_name = "c" + str(c)
        clients.append(client_name)

        if Verbose.level >= 3:
            print("Add " + str(client_name) + " at " + str(client_dest))

        network.add_client(client_name, client_dest, config.GRAPH_DELAY)

    # 7 - now calculate all the forwarding tables
    network.calculate_forwarding_tables()
    

    # 8 - dump graphviz file to tmp
    network.graphviz_to_file("dfn2_i.gv", dir="tmp")
        

    # Network
    if Verbose.level >= 3:
        print("Network = ")
        network.print()

    # 9 - setup generators
    
    # Services are not addresses -- they start with §

    # Server 's1' generates packets from arriving events
    # and sends to service 'a'  indicated by "§a" or config.SERVICE
    for server_name in servers:
        generator = Generator.server_load_event_generator(network, server_name, [config.SERVICE], seed=config.SEED, background_load=False)

    # Clients 'c1' ... 'c5' generates packets from arriving events
    # arrival_lambda is the mean arrival time between requests (in seconds)
    # size_lambda is the mean length/duration of the sessions (in seconds)
    # size_scale_factor is a multiplier for the session duration
    # Example: arrival_lambda=0.5, size_lambda=10, size_scale_factor=10 means an average of 2 requests per second, each lasting on average 100 seconds. This gives an average of 200 concurrent requests in the system. If there are 5 servers, each server will have an average of 40 concurrent requests.
    # Note that it doesn't matter whether we have size_lambda=10, size_scale_factor=10 or size_lambda=100, size_scale_factor=1, the average session duration is the same (100 seconds). The scale factor is just a multiplier for the session duration.
    generator_m1 = Generator.multi_client_event_generator(network, clients, config.SERVICE, arrival_lambda=config.CLIENT_ARRIVAL_LAMBDA, size_lambda=config.SESSION_SIZE_LAMBDA, size_scale_factor=config.SESSION_SIZE_SCALE, seed=config.SEED)

    # 10 - run
    
    if Verbose.level >= 3:
        print("RUN ----------------------------------------------------------------")

    network.start(until=config.SIM_DURATION)


# go !
topology_setup()


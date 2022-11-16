from Network import Network
from Server import Server
from Client import Client
from Router import Router
from Generator import Generator
from Verbose import Verbose
import simpy
from gml import read_gml

# sclayman:
# Using a topology loaded from the DFN gml file

# Use a topology from the DFN gml file
def topology_setup():
    Verbose.level = 2
    Verbose.table = 1

    # Set alpha value
    Router.alpha = 0.50

    # Set slots
    Server.slots = 50


    # 1 - Define the topology
    print("- DFN")
    gml_file = "gml/Dfn.gml"

    # 2 - create the simpy environment 
    env = simpy.Environment()

    # 3 - build the network: topology -> graph -> network

    print("SETUP ----------------------------------------------------------------")

    graph = read_gml(gml_file)
    graph.print()

    print ("graph nodes = " + str(graph.nodes()))

    print("graph edges = " + str(graph.edges()))

    # graph -> network

    print("--- Convert Graph to Network Begin ---")
    
    network = Network.from_graph(graph, env)

    print("Network nodes = " + str(network.nodes()))
    print("Network edges = " + str(network.edges()))

    # filter out core nodes -  degree > 3
    core = [ r  for r in network.network_nodes() if r.degree() > 3 ]
    # filter out local nodes -  degree <= 3
    local = [ r  for r in network.network_nodes() if r.degree() <= 3 ]

    print("core = " + str([(r.id(), r.degree()) for r in core]))
    print("local = " + str([(r.id(), r.degree()) for r in local]))

    print("--- Add Servers and Clients to Network ---")

    # add some servers
    servers = []
    
    # connected to core nodes
    server_count = range(1,6)
    for s in server_count:
        server_name = "s" + str(s)
        servers.append(server_name)
        server_dest = core[s]
        print("Add " + str(server_name) + " at " + str(server_dest))
        network.add_server(server_name, server_dest)

    
    # add some clients
    clients = []
    
    # connected to local nodes
    client_count = range(1,6)
    for c in client_count:
        client_name = "c" + str(c)
        clients.append(client_name)
        client_dest = local[c]
        print("Add " + str(client_name) + " at " + str(client_dest))
        network.add_client(client_name, client_dest)

    # now calculate all the forwarding tables
    network.calculate_forwarding_tables()
    
    print("Network = ")
    network.print()
    # Services are not addresses -- they start with §

    # Server 's1' generates packets from arriving events
    # and sends to service 'a'  indicated by "§a"
    for server_name in servers:
        generator = Generator.server_load_event_generator(network, server_name, ["§a"], exponential_lambda=55, seed=15112022, background_load=False)

    # Clients 'c1' ... 'c5' generates packets from arriving events
    generator_m1 = Generator.multi_client_event_generator(network, clients, "§a", arrival_lambda=5, size_lambda=10, size_scale_factor=10, seed=15112022)

    # run
    print("RUN ----------------------------------------------------------------")

    network.start(until=3600)


# go !
topology_setup()


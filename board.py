from Graph import Graph
from Network import Network
from Server import Server
from Client import Client
from Generator import Generator
from Verbose import Verbose
from Utility import Utility
import simpy

# sclayman:
# Test of a topology with 5 servers and 5 clients,
# using Generator.multi_client_event_generator and Generator.server_load_event_generator
#
# All Servers connected to node 'a'
# r1 -> a,  r2 -> a, s3 -> a, s4 -> a, s5 -> a
# All Clients connected to node 'e'


# Use a topology from an adjacency list
def topology_setup():
    Verbose.level = 2
    Verbose.table = 1

    # Set alpha value
    Utility.alpha = 0.50

    # Set slots
    Server.slots = 50

    
    # 1 - Define the topology
    topo = {
        'a': { ('c', 1), ('d', 5)},
        'b': { ('c', 1), ('e', 4)},
        'c': { ('a', 1), ('b', 1), ('d', 1), ('e', 1)},
        'd': { ('a', 5), ('c', 1), ('f', 1)},
        'e': { ('b', 4), ('c', 1), ('f', 1)},
        'f': { ('d', 1), ('e', 1) },
        'g': { ('f', 1) }
      }

    # 2 - create the simpy environment 
    env = simpy.Environment()

    # 3 - build the network: topology -> graph -> network

    print("SETUP ----------------------------------------------------------------")

    # adjacency list -> graph
    graph = Graph.from_dict(topo)

    # test print
    print("graph adjacency list = ")
    graph.print()

    # test dijkstra_algorithm
    print ("graph nodes = " + str(graph.nodes()))

    print("graph edges = " + str(graph.edges()))

    #print("graph edge b->c " + str(graph.contains_edge('b', 'c')) + " " + str(graph.edge('b', 'c')))

    #print("graph neighbours b = " + str(graph.neighbours('b')))

    #print("graph weight b->c = " + str(graph.weight('b', 'c')))

    #print("graph dijkstra from f = " + str(Graph.dijkstra_algorithm(graph, 'f')))

    # graph -> network

    print("--- Convert Graph to Network Begin ---")
    
    network = Network.from_graph(graph, env)

    print("--- Convert Graph to Network End ---")
    
    # do some test prints
    print("Network nodes = " + str(network.nodes()))
    print("Network edges = " + str(network.edges()))

    #print("Network from a: " + str(network.links_from('a')))

    #print("Network to d: " + str(network.links_to('d')))


    print("--- Add Servers and Clients to Network ---")

    # add some servers
    # connected to 'a'
    network.add_server("r1", 'a')
    network.add_server("r2", 'b')
    
    # add a client
    # connected to 'e'
    network.add_client("c1", 'g')
    network.add_client("c2", 'g')
    network.add_client("c3", 'g')
    network.add_client("c4", 'g')
    network.add_client("c5", 'g')

    # now calculate all the forwarding tables
    network.calculate_forwarding_tables()
    
    # some test values
    print("Network = ")
    network.print()

    #print("Network neighbours e: " + str(network.neighbours('e')))
    #print("Network degree e: " + str(network.degree('e')))

    #print("Network neighbours c1: " + str(network.neighbours('c1')))
    #print("Network degree c1: " + str(network.degree('c1')))

    #print("Network: dijkstra from a = " + str(Graph.dijkstra_algorithm(network, 'a')))
    print("Network: dijkstra from f = " + str(Graph.dijkstra_algorithm(network, 'f')))

    print("Network: unicast forwarding table at f = " + str(network['f'].get_unicast_forwarding_table()))

    print("Network: route from f to r1 = " + str(network['f'].route_to('r1')) +  "  distance: " + str(network['f'].distance_to('r1')) )
    
    #print("Network: route from r1 to c1  = " + str(network['r1'].route_to('c1')) +  "  distance: " + str(network['r1'].distance_to('c1')) )
    
    # 4 - Now we create the packet generator.

    # Services are not addresses -- they start with §

    # Server 'r1' generates packets from arriving events
    # and sends to service 'a'  indicated by "§a"
    generator_r1 = Generator.server_load_event_generator(network, "r1", ["§a"], exponential_lambda=55, seed=30072022, background_load=False)
    generator_r2 = Generator.server_load_event_generator(network, "r2", ["§a"], exponential_lambda=55, seed=30072022, background_load=False)


    # Clients 'c1' ... 'c5' generates packets from arriving events
    generator_m1 = Generator.multi_client_event_generator(network, ["c1", "c2", "c3", "c4", "c5"], "§a", arrival_lambda=5, size_lambda=10, size_scale_factor=10, seed=30072022)

    # run
    print("RUN ----------------------------------------------------------------")

    network.start(until=3600)


    




# go !
topology_setup()





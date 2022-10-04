# Simulation of the ServiceCast system
# Uses simpy and grotto networking:
# https://www.grotto-networking.com/DiscreteEventPython.html

from AdjList import Graph
from Network import Network
from Server import Server
from Client import Client
from Router import Router
from Generator import Generator
from Verbose import Verbose
import simpy



# Use a topology from an adjacency list
def topology_setup():
    Verbose.level = 2
    Verbose.table = 1

    # Set alpha value
    Router.alpha = 0.50


    
    # 1 - Define the topology
    topo = {
        'a': { 'b', ('c', 4)},
        'b': { ('c', 3), ('d', 2), ('e', 2)},
        'c': { },
        'd': { 'b', ('c', 5)},
        'e': { ('d', 5)}
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

    print("graph edge b->c " + str(graph.contains_edge('b', 'c')) + " " + str(graph.edge('b', 'c')))

    print("graph neighbours b = " + str(graph.neighbours('b')))

    print("graph weight b->c = " + str(graph.weight('b', 'c')))

    print("graph dijkstra from a = " + str(Graph.dijkstra_algorithm(graph, 'a')))

    # graph -> network

    print("--- Convert Graph to Network Begin ---")
    
    network = Network.from_graph(graph, env)

    print("--- Convert Graph to Network End ---")
    
    network.add_edge('c', 'f')

    # do some test prints
    print("Network nodes = " + str(network.nodes()))
    print("Network edges = " + str(network.edges()))

    print("Network from a: " + str(network.links_from('a')))

    print("Network to d: " + str(network.links_to('d')))


    print("--- Add Servers and Clients to Network ---")

    # add some servers
    # connected to 'a'
    network.add_server("s1", 'a')
    network.add_server("s2", 'a')
    network.add_server("s3", 'b')
    network.add_server("s4", 'b')
    network.add_server("s5", 'f')
    
    # add a client
    # connected to 'e'
    network.add_client("c1", 'e')
    network.add_client("c2", 'e')
    network.add_client("c3", 'e')
    network.add_client("c4", 'd')
    network.add_client("c5", 'd')

    # now calculate all the forwarding tables
    network.calculate_forwarding_tables()
    
    # some test values
    print("Network = ")
    network.print()

    print("Network neighbours e: " + str(network.neighbours('e')))
    print("Network degree e: " + str(network.degree('e')))

    print("Network neighbours c1: " + str(network.neighbours('c1')))
    print("Network degree c1: " + str(network.degree('c1')))

    print("Network: dijkstra from a = " + str(Graph.dijkstra_algorithm(network, 'a')))
    print("Network: dijkstra from d = " + str(Graph.dijkstra_algorithm(network, 'd')))

    print("Network: unicast forwarding table at d = " + str(network['d'].get_unicast_forwarding_table()))

    print("Network: route from d to s1 = " + str(network['d'].route_to('s1')) +  "  distance: " + str(network['d'].distance_to('s1')) )
    
    print("Network: route from s1 to c1  = " + str(network['s1'].route_to('c1')) +  "  distance: " + str(network['s1'].distance_to('c1')) )
    
    # 4 - Now we create the packet generator.

    # Services are not addresses -- they start with §

    # Server 's1' generates packets from arriving events
    # and sends to service 'a'  indicated by "§a"
    generator_s1 = Generator.server_load_event_generator(network, "s1", ["§a"], exponential_lambda=55, seed=30072022)
    generator_s2 = Generator.server_load_event_generator(network, "s2", ["§a"], exponential_lambda=55, seed=30072022)
    generator_s3 = Generator.server_load_event_generator(network, "s3", ["§a"], exponential_lambda=55, seed=30072022)
    generator_s4 = Generator.server_load_event_generator(network, "s4", ["§a"], exponential_lambda=55, seed=30072022)
    generator_s5 = Generator.server_load_event_generator(network, "s5", ["§a"], exponential_lambda=55, seed=30072022)

    # Clients 'c1' ... 'c5' generates packets from arriving events
    generator_m1 = Generator.multi_client_event_generator(network, ["c1", "c2", "c3", "c4", "c5"], "§a", exponential_lambda=30, seed=30072022)

    # run
    print("RUN ----------------------------------------------------------------")

    network.start(until=400)


    




# go !
topology_setup()





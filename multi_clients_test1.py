from AdjList import Graph
from Network import Network
from Server import Server
from Client import Client
from Router import Router
from Generator import Generator
from Verbose import Verbose
import simpy

# sclayman:
# Test of a topology with 5 servers and 5 clients,
# using Generator.multi_client_event_generator and Generator.server_event_generator



# Use a topology from an adjacency list
def square_topology_example_adj():
    Verbose.level = 1
    
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
    graph.print()

    # graph -> network
    network = Network.from_graph(graph, env)

    network.add_edge('c', 'f')

    # do some test prints
    print(network.nodes())
    print(network.edges())

    print("From a: " + str(network.links_from('a')))

    print("To d: " + str(network.links_to('d')))


    # add a server
    network.add_server("s1", 'a')
    
    # add a client
    network.add_client("c1", 'e')
    network.add_client("c2", 'e')
    network.add_client("c3", 'e')
    network.add_client("c4", 'e')
    network.add_client("c5", 'e')
    
    print("Neighbours e: " + str(network.neighbours('e')))
    print("Degree e: " + str(network.degree('e')))

    print("Neighbours c1: " + str(network.neighbours('c1')))
    print("Degree c1: " + str(network.degree('c1')))

    network.print()
    
    # 4 - Now we create the packet generator.

    # Server 's1' generates packets from arriving events
    generator_s1 = Generator.server_event_generator(network, "s1", ["b", "c", "d","e"], exponential_lambda=25)

    # Clients 'c1' ... 'c5' generates packets from arriving events
    generator_m1 = Generator.multi_client_event_generator(network, ["c1", "c2", "c3", "c4", "c5"], None, arrival_lambda=30)

    # run
    print("RUN ----------------------------------------------------------------")

    network.start(until=100)


    


# go !
square_topology_example_adj()





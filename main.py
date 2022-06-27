# Simulation of the ServiceCast system
# Uses simpy and grotto networking:
# https://www.grotto-networking.com/DiscreteEventPython.html

from AdjList import Graph
from Network import Network
from Server import Server
from Client import Client
from Router import Router
from Generator import Generator
import simpy



# Use a topology from an adjacency list
def square_topology_example_adj():
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

    print("Neighbours b: " + str(network.neighbours('b')))
    print("Degree b: " + str(network.degree('b')))

    # add a server
    network.add_server("s1", 'a')
    
    # add a client
    network.add_client("c1", 'e')
    
    print("Neighbours s1: " + str(network.neighbours('s1')))
    print("Degree s1: " + str(network.degree('s1')))

    network.print()
    
    # 4 - Now we create the packet generator.

    # Server 's1' generates packets from arriving events
    generator_s1 = Generator.server_event_generator(network, "s1", ["b", "c", "d","e"], exponential_lambda=25)

    # Client 'c1' generates packets from arriving events
    generator_c1 = Generator.client_event_generator(network, "c1", ["e"], exponential_lambda=50)

    # run
    print("RUN ----------------------------------------------------------------")

    network.start(until=100)


    


# go !
square_topology_example_adj()





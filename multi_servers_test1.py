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
def square_topology_example_adj():
    Verbose.level = 2
    
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


    # add some servers
    # connected to 'a'
    network.add_server("s1", 'a')
    network.add_server("s2", 'a')
    network.add_server("s3", 'a')
    network.add_server("s4", 'a')
    network.add_server("s5", 'a')
    
    # add a client
    # connected to 'e'
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
    # and sends to service 'a'  indicated by "§a"
    generator_s1 = Generator.server_load_event_generator(network, "s1",  ["b", "c", "d","e"], exponential_lambda=25)

    # Clients 'c1' ... 'c5' generates packets from arriving events
    generator_m1 = Generator.multi_client_event_generator(network, ["c1", "c2", "c3", "c4", "c5"], None, exponential_lambda=30)

    # run
    print("RUN ----------------------------------------------------------------")

    network.start(until=400)


    


# go !
square_topology_example_adj()





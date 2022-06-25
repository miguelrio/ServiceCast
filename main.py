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
    network = Network.from_graph(env, graph)

    network.add_edge(network['c'], Router(env, 'f'))

    # do some test prints
    print(network.nodes())
    print(network.edges())

    print(network.links_from('a'))

    print(network.links_to('d'))

    # add a server
    s1 = Server(env, 's1')
    network.linkhost(s1, network['a'])
    
    # add a client
    c1 = Client(env, 'c1')
    network.linkhost(c1, network['e'])
    
    network.print()
    
    # 4 - Now we create the packet generator.

    # Server 's1' generates packets from arriving events
    generator_s1 = Generator.server_event_generator(network, "s1", ["b", "c", "d","e"], exponential_lambda=25)

    # Client 'c1' generates packets from arriving events
    generator_c1 = Generator.client_event_generator(network, "c1", ["e"], exponential_lambda=50)

    # run
    print("RUN ----------------------------------------------------------------")

    network.start(until=1000)


    


# go !
square_topology_example_adj()





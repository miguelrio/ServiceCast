# Simulation of the ServiceCast system
# Uses simpy and grotto networking:
# https://www.grotto-networking.com/DiscreteEventPython.html

from AdjList import Graph
from Network import Network
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
    network = Network(env, graph)

    # do some test prints
    network.print()
    
    print(network.nodes())
    print(network.edges())

    print(network.links_from('a'))

    print(network.links_to('d'))
    
    # 4 - Now we create the packet generator.

    # For now, only router 'a' generates packets
    generator = Generator.packet_generator(network, "a", ["b", "c", "d","e"], exponential_lambda=5)

    # run
    print("RUN ----------------------------------------------------------------")

    network.start(until=1000)


    


# go !
square_topology_example_adj()





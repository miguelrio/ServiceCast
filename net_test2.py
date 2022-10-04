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



# Test the use of integers when doing add_edge()
def square_topology_example_edges():
    # 1 - No topology
    
    # 2 - create the simpy environment 
    env = simpy.Environment()

    # 3 - build the network: topology -> graph -> network

    print("SETUP ----------------------------------------------------------------")

    network = Network(env)
    
    # use same topology as adjacency list
    # but add node by node and edge by edge
    network.add_node('a')
    network.add_node('b')
    network.add_node('c')
    network.add_node('d')
    network.add_node('e')

    

    network.add_edge(0, 1)
    network.add_edge(0, 2, 4)
    network.add_edge(1, 3, 3)
    network.add_edge(1, 3, 2)
    network.add_edge(1, 4, 2)
    network.add_edge(3, 2)
    network.add_edge(3, 2, 5)
    network.add_edge(4, 3, 5)

    # add an edge: c -- f
    network.add_edge(network[2], 'f')

    print("node f = " + str(network.node(5)))
    
    # do some test prints
    print("nodes = " + str(network.nodes()))
    print("edges = " + str(network.edges()))

    print("contains_link " + network.name_of(0) + " --> " + network.name_of(1) + " = " + str(network.contains_link(0, 1)))

    print("From a: " + str(network.links_from(0)))

    print("To d: " + str(network.links_to(3)))

    

    # add a server
    s1 = Server('s1')
    network.add_host(s1, network[0])
    
    # add a client
    c1 = Client('c1')
    network.add_host(c1, network[4])
    
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
square_topology_example_edges()





from Graph import Graph
from Network import Network
from Server import Server
from Client import Client
from Router import Router
from Generator import Generator
import simpy

# sclayman:
# Test of a topology with 1 server and 1 client

# Use a topology by explicitly adding the edges
def square_topology_example_edges():
    # 1 - No topology
    
    # 2 - create the simpy environment 
    env = simpy.Environment()

    # 3 - build the network: topology -> graph -> network

    print("SETUP ----------------------------------------------------------------")

    network = Network(env)
    
    # use same topology as adjacency list
    # but add edge by edge
    network.add_edge('a', 'b')
    network.add_edge('a', 'c', 4)
    network.add_edge('b', 'c', 3)
    network.add_edge('b', 'd', 2)
    network.add_edge('b', 'e', 2)
    network.add_edge('d', 'b')
    network.add_edge('d', 'c', 5)
    network.add_edge('e', 'd', 5)

    # add an edge: c -- f
    network.add_edge(network['c'], 'f')


    # do some test prints
    print(network.nodes())
    print(network.edges())

    print("From a: " + str(network.links_from('a')))

    print("To d: " + str(network.links_to('d')))

    # add a server
    s1 = Server('s1')
    network.add_host(s1, network['a'])
    
    # add a client
    c1 = Client('c1')
    network.add_host(c1, network['e'])
    
    network.print()

    # now calculate all the forwarding tables
    network.calculate_forwarding_tables()
    

    
    # 4 - Now we create the packet generator.

    # Server 's1' generates packets from arriving events
    generator_s1 = Generator.server_event_generator(network, "s1", ["b", "c", "d","e"], exponential_lambda=25)

    # Client 'c1' generates packets from arriving events
    generator_c1 = Generator.client_event_generator(network, "c1", ["e"], arrival_lambda=50)

    # run
    print("RUN ----------------------------------------------------------------")

    network.start(until=1000)


    


# go !
square_topology_example_edges()





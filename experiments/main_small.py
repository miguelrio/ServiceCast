from Graph import Graph
from Network import Network
from Server import Server
from Client import Client
from Generator import Generator
from Verbose import Verbose
from Utility import Utility
import simpy

# sclayman:
# Test of a topology with 2 servers and 2 clients,
# using Generator.multi_client_event_generator and Generator.server_load_event_generator
#
# All Servers connected to node 'a'
# All Clients connected to node 'b'


# Setup a topology 
def topology_setup():
    Verbose.level = 2
    Verbose.table = 1

    # Set alpha value
    Utility.alpha = 0.50


    
    # 1 - Define the topology
    # not for this example

    # 2 - create the simpy environment 
    env = simpy.Environment()

    # 3 - build the network: topology -> graph -> network

    print("SETUP ----------------------------------------------------------------")


    # network
    network = Network(env)

    network.add_edge('a', 'b')



    # add some servers
    # connected to 'a'
    network.add_server("s1", 'a')
    network.add_server("s2", 'a')

    
    # add a client
    # connected to 'b'
    network.add_client("c1", 'b')
    network.add_client("c2", 'b')

    # now calculate all the forwarding tables
    network.calculate_forwarding_tables()
    

    # do some test prints
    print(network.nodes())
    print(network.edges())

    
    network.print()
    
    # 4 - Now we create the packet generator.

    # Services are not addresses -- they start with §

    # Server 's1' generates packets from arriving events
    # and sends to service 'a'  indicated by "§a"
    generator_s1 = Generator.server_load_event_generator(network, "s1", ["§a"], exponential_lambda=55, seed=30072022)
    generator_s2 = Generator.server_load_event_generator(network, "s2", ["§a"], exponential_lambda=55, seed=30072022)


    # Clients 'c1' ... 'c2' generates packets from arriving events
    generator_m1 = Generator.multi_client_event_generator(network, ["c1", "c2"], "§a", arrival_lambda=2, size_lambda=6, seed=30072022)

    # run
    print("RUN ----------------------------------------------------------------")

    network.start(until=3600)


    




# go !
topology_setup()





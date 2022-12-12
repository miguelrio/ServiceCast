from Graph import Graph
from Network import Network
from Server import Server
from Client import Client
from Router import Router
from Generator import Generator
import simpy

# sclayman:
# Test of a topology based on Bics.gml


# Test the use of integers when doing add_edge()
def square_topology_example_edges():
    # 1 - No topology
    
    # 2 - create the simpy environment 
    env = simpy.Environment()

    # 3 - build the network: topology -> graph -> network

    print("SETUP ----------------------------------------------------------------")

    network = Network(env)
    
    network.add_node("Bratislava")
    network.add_node("Vienna")
    network.add_node("Praha")
    network.add_node("Rotterdam")
    network.add_node("Roma")
    network.add_node("Budapest")
    network.add_node("Ljubjana")
    network.add_node("Zagreb")
    network.add_node("Bucharest")
    network.add_node("Istanbul")
    network.add_node("Vaduz")
    network.add_node("Strasbourg")
    network.add_node("Luxembourg")
    network.add_node("Zurich")
    network.add_node("Brussels")
    network.add_node("Geneva")
    network.add_node("Milan")
    network.add_node("Athens")
    network.add_node("Sofia")
    network.add_node("Frankfurt")
    network.add_node("Amsterdam")
    network.add_node("London")
    network.add_node("Paris")
    network.add_node("Stockholm")
    network.add_node("Warsaw")
    network.add_node("Kiev")
    network.add_node("Dublin")
    network.add_node("Lisbon")
    network.add_node("Madrid")
    network.add_node("Barcelona")
    network.add_node("Marseille")
    network.add_node("Lyon")
    network.add_node("Basel")
    network.add_edge(0, 1)
    network.add_edge(0, 2)
    network.add_edge(0, 5)
    network.add_edge(1, 16)
    network.add_edge(1, 19)
    network.add_edge(2, 24)
    network.add_edge(2, 19)
    network.add_edge(3, 20)
    network.add_edge(3, 14)
    network.add_edge(4, 16)
    network.add_edge(4, 13)
    network.add_edge(5, 8)
    network.add_edge(5, 18)
    network.add_edge(5, 7)
    network.add_edge(6, 7)
    network.add_edge(8, 25)
    network.add_edge(8, 9)
    network.add_edge(9, 17)
    network.add_edge(10, 13)
    network.add_edge(11, 32)
    network.add_edge(11, 19)
    network.add_edge(11, 12)
    network.add_edge(12, 14)
    network.add_edge(13, 16)
    network.add_edge(13, 19)
    network.add_edge(13, 15)
    network.add_edge(14, 19)
    network.add_edge(14, 20)
    network.add_edge(14, 21)
    network.add_edge(14, 22)
    network.add_edge(15, 32)
    network.add_edge(15, 22)
    network.add_edge(15, 31)
    network.add_edge(16, 30)
    network.add_edge(17, 18)
    network.add_edge(19, 20)
    network.add_edge(19, 23)
    network.add_edge(19, 24)
    network.add_edge(20, 21)
    network.add_edge(21, 26)
    network.add_edge(21, 27)
    network.add_edge(21, 22)
    network.add_edge(22, 28)
    network.add_edge(22, 31)
    network.add_edge(24, 25)
    network.add_edge(28, 29)
    network.add_edge(29, 30)
    network.add_edge(30, 31)

    # do some test prints
    print("nodes = " + str(network.nodes()))
    print("edges = " + str(network.edges()))

    print("contains_link " + network.name_of(0) + " --> " + network.name_of(1) + " = " + str(network.contains_link(0, 1)))

    print("From " + network.name_of(0) + ": " + str(network.links_from(0)))

    print("To " + network.name_of(3) + ": " + str(network.links_to(3)))

    
    
    network.print()
    
    # 4 - Now we create the packet generator.

    # Server 's1' generates packets from arriving events
    #generator_s1 = Generator.server_event_generator(network, "s1", ["b", "c", "d","e"], exponential_lambda=25)

    # Client 'c1' generates packets from arriving events
    #generator_c1 = Generator.client_event_generator(network, "c1", ["e"], exponential_lambda=50)

    # run
    #print("RUN ----------------------------------------------------------------")

    #network.start(until=1000)


    


# go !
square_topology_example_edges()





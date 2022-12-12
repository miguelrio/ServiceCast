# Simulation of the ServiceCast system
# Uses simpy and grotto networking:
# https://www.grotto-networking.com/DiscreteEventPython.html

from Graph import Graph
from Network import Network
from Verbose import Verbose
import simpy

# sclayman:
# Test of a Graph handcrafted with same nodes as Bics.gml
# then do Graph -> Network

# Test the use of integers when doing add_edge()
def square_topology_example_edges():
    Verbose.level = 2


    # 1 - No topology
    
    # 2 - create the simpy environment 
    env = simpy.Environment()

    # 3 - build the graph

    print("SETUP ----------------------------------------------------------------")

    graph = Graph()
    
    graph.add_node("Bratislava")
    graph.add_node("Vienna")
    graph.add_node("Praha")
    graph.add_node("Rotterdam")
    graph.add_node("Roma")
    graph.add_node("Budapest")
    graph.add_node("Ljubjana")
    graph.add_node("Zagreb")
    graph.add_node("Bucharest")
    graph.add_node("Istanbul")
    graph.add_node("Vaduz")
    graph.add_node("Strasbourg")
    graph.add_node("Luxembourg")
    graph.add_node("Zurich")
    graph.add_node("Brussels")
    graph.add_node("Geneva")
    graph.add_node("Milan")
    graph.add_node("Athens")
    graph.add_node("Sofia")
    graph.add_node("Frankfurt")
    graph.add_node("Amsterdam")
    graph.add_node("London")
    graph.add_node("Paris")
    graph.add_node("Stockholm")
    graph.add_node("Warsaw")
    graph.add_node("Kiev")
    graph.add_node("Dublin")
    graph.add_node("Lisbon")
    graph.add_node("Madrid")
    graph.add_node("Barcelona")
    graph.add_node("Marseille")
    graph.add_node("Lyon")
    graph.add_node("Basel")
    graph.add_edge(0, 1)
    graph.add_edge(0, 2)
    graph.add_edge(0, 5)
    graph.add_edge(1, 16)
    graph.add_edge(1, 19)
    graph.add_edge(2, 24)
    graph.add_edge(2, 19)
    graph.add_edge(3, 20)
    graph.add_edge(3, 14)
    graph.add_edge(4, 16)
    graph.add_edge(4, 13)
    graph.add_edge(5, 8)
    graph.add_edge(5, 18)
    graph.add_edge(5, 7)
    graph.add_edge(6, 7)
    graph.add_edge(8, 25)
    graph.add_edge(8, 9)
    graph.add_edge(9, 17)
    graph.add_edge(10, 13)
    graph.add_edge(11, 32)
    graph.add_edge(11, 19)
    graph.add_edge(11, 12)
    graph.add_edge(12, 14)
    graph.add_edge(13, 16)
    graph.add_edge(13, 19)
    graph.add_edge(13, 15)
    graph.add_edge(14, 19)
    graph.add_edge(14, 20)
    graph.add_edge(14, 21)
    graph.add_edge(14, 22)
    graph.add_edge(15, 32)
    graph.add_edge(15, 22)
    graph.add_edge(15, 31)
    graph.add_edge(16, 30)
    graph.add_edge(17, 18)
    graph.add_edge(19, 20)
    graph.add_edge(19, 23)
    graph.add_edge(19, 24)
    graph.add_edge(20, 21)
    graph.add_edge(21, 26)
    graph.add_edge(21, 27)
    graph.add_edge(21, 22)
    graph.add_edge(22, 28)
    graph.add_edge(22, 31)
    graph.add_edge(24, 25)
    graph.add_edge(28, 29)
    graph.add_edge(29, 30)
    graph.add_edge(30, 31)

    # do some test prints
    print("nodes = " + str(graph.nodes()))
    print("edges = " + str(graph.edges()))

    print("contains_link " + graph.name_of(0) + " --> " + graph.name_of(1) + " = " + str(graph.contains_link(0, 1)))

    print("From " + graph.name_of(0) + ": " + str(graph.neighbours(0)))

    print("To " + graph.name_of(3) + ": " + str(graph.neighbours(3)))

    
    
    graph.print()

    print("range: " + str(range(len(graph))))
    
    # graph -> network

    print("--- Convert Graph to Network Begin ---")
    
    network = Network.from_graph(graph, env)

    print("--- Convert Graph to Network End ---")
    
    # now calculate all the forwarding tables
    network.calculate_forwarding_tables()
    
    # some test values
    print("Network = ")
    network.print()



# go !
square_topology_example_edges()





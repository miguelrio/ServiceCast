# Simulation of the ServiceCast system
# Uses simpy and grotto networking:
# https://www.grotto-networking.com/DiscreteEventPython.html

from AdjList import Graph




# Test the use of integers when doing add_edge()
def square_topology_example_edges():
    # 1 - No topology
    
    # 2 - create the simpy environment 

    # 3 - build the  graph 

    print("SETUP ----------------------------------------------------------------")

    graph = Graph()
    
    # use same topology as adjacency list
    # but add node by node and edge by edge
    graph.add_node('a')
    graph.add_node('b')
    graph.add_node('c')
    graph.add_node('d')
    graph.add_node('e')

    

    graph.add_edge(0, 1)
    graph.add_edge(0, 2, 4)
    graph.add_edge(1, 3, 3)
    graph.add_edge(1, 3, 2)
    graph.add_edge(1, 4, 2)
    graph.add_edge(3, 2)
    graph.add_edge(3, 2, 5)
    graph.add_edge(4, 3, 5)

    # add an edge: c -- f
    graph.add_edge(graph[2], 'f')

    print("node f = " + str(graph.node(5)))
    
    # do some test prints
    print("nodes = " + str(graph.nodes()))
    print("edges = " + str(graph.edges()))

    print("contains_link " + graph.name_of(0) + " --> " + graph.name_of(1) + " = " + str(graph.contains_link(0, 1)))

    print("From a: " + str(graph.neighbours(0)))

    print("To d: " + str(graph.neighbours(3)))

    
    graph.print()
    

    


# go !
square_topology_example_edges()





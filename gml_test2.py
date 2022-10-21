from AdjList import Graph
from Network import Network
import simpy

# sclayman:
# Second test of a topology loaded from a gml file
# and using Graph.from_gml_file and Network.from_gml_file

print("- Bics")
g = Graph.from_gml_file("gml/Bics.gml")
g.print()


print("- Bics Network")
env = simpy.Environment()

n = Network.from_gml_file("gml/Bics.gml", env)
n.print()

print("- Bics Graph --> Network")
ng = Network.from_graph(g, env)
ng.print()

print("same? " + str(ng == n))

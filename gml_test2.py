#from gml import read_gml, write_gml
from AdjList import Graph
from Network import Network
import simpy


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

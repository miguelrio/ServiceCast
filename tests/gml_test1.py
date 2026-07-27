import os
import sys
# Ensure the simulator source in src/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from Gml import read_gml, write_gml

# sclayman:
# First test of a topology loaded from a gml file


print("- Bics")
g = read_gml("topologies/gml/Bics.gml")
g.print()
write_gml(g, "/tmp/Bics2.gml")

print("- Ntt")
g = read_gml("topologies/gml/Ntt.gml")
g.print()

print("- DeutscheTelekom")
g = read_gml("topologies/gml/DeutscheTelekom.gml")
g.print()

print("- HiberniaGlobal")
g = read_gml("topologies/gml/HiberniaGlobal.gml")
g.print()

print("- Cogent")
g = read_gml("topologies/gml/Cogentco.gml")
g.print()


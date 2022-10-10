from gml import read_gml, write_gml


print("- Bics")
g = read_gml("gml/Bics.gml")
g.print()
write_gml(g, "/tmp/Bics2.gml")

print("- Ntt")
g = read_gml("gml/Ntt.gml")
g.print()

print("- DeutscheTelekom")
g = read_gml("gml/DeutscheTelekom.gml")
g.print()

print("- HiberniaGlobal")
g = read_gml("gml/HiberniaGlobal.gml")
g.print()

print("- Cogent")
g = read_gml("gml/Cogentco.gml")
g.print()


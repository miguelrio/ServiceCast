# Example: Topology Zoo DFN with 5 servers and 5 clients (made by
# scripts/topologies/make_zoo_gml.py; see doc/Workflow.md).
#
#   python3 experiments/main.py configs/dfn_s5_c5.py > dfn.log

GML_FILE = "topologies/ready/dfn_s5_c5.gml"
ARRIVAL_MEAN = 4000           # ms between requests: 10% load on 5 servers x 50 slots
SERVER_CF = 0.01

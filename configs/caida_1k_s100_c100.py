# Example: the CAIDA subset of 1000 ASes with 100 servers and 100 client
# nodes, at 10% load. The topology is built by the CAIDA scripts (see
# doc/Workflow.md); CAIDA-derived files are not committed.
#
#   python3 experiments/main.py configs/caida_1k_s100_c100.py --set UNTIL=50000 > logs/caida_1k.log

GML_FILE = "topologies/ready/caida_1k_s100_c100.gml"
ARRIVAL_MEAN = 200            # ms between requests: 10% load on 100 servers x 50 slots

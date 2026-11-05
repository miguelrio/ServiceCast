# The settings of experiments/main_precomputed_t1.py, run with no arguments
# and no environment variables, so that experiments/main.py reproduces its
# runs (logs identical apart from the header).  Only what differs from the
# code defaults.  Times in ms.
#
#   python3 experiments/main.py configs/precomputed_t1.py --set GML_FILE=<gml> --set UNTIL=500000

GML_FILE = "topologies/synthetic/topology_synthetic_1788876186136.gml"
UNTIL = 360000
VERBOSE_LEVEL = 1
GRAPH_DELAY = 100             # ms: links with no delay in the GML
SERVER_CF = 0.01
ROUTER_FIB_UPT = 0.001

# Config for experiments/main_importer.py: the DFN-2 experiment
# (the settings of experiments/main_dfn_2.py, but with the default
# utility functions -- see the TODO below).
#
#   PYTHONPATH=src:scripts python3 experiments/main_importer.py -c scripts/setup/constants_dfn_2_importer.py
#
# main_importer.py requires every name below.

# --- run --------------------------------------------------------------------
SIM_DURATION = 360            # simulated seconds
VERBOSE_LEVEL = -1            # -1: metrics (large runs); 0 and up: protocol debugging (see doc/Logging.md)
VERBOSE_TABLE = 0

# --- topology and placement -------------------------------------------------
GML_FILE = "topologies/gml/Dfn.gml"
NUM_SERVERS = 5               # placed at random on routers of degree <= 3
NUM_CLIENTS = 5               # likewise, after the servers
SEED = 15112022               # placement and generator seed

# --- workload ---------------------------------------------------------------
SERVICE = "§a"                # the single service every client requests
CLIENT_ARRIVAL_LAMBDA = 0.2   # mean time (s) between requests, all clients together
SESSION_SIZE_LAMBDA = 10      # mean session length (s) ...
SESSION_SIZE_SCALE = 10       # ... times this multiplier

# --- simulator settings (Importer.mappings) ---------------------------------
ALPHA = 0.5                   # Utility.alpha: load/delay weighting
GRAPH_DELAY = 0.1             # Graph.default_propagation_delay (access links)
ROUTER_HOP_BY_HOP = False     # False: first-decide unicast; True: hop-by-hop anycast
ROUTER_FIB_UPT = 0.001        # Router.fib_utility_update_threshold
ROUTER_FORWARD_TO_TREE_CHILDREN_ONLY = True
ROUTER_REMOVE_FIB_ENTRY_WHEN_ALL_UTILITIES_ZERO = True
SERVER_SLOTS = 50             # Server.slots: capacity
SERVER_CF = 0.01              # Server.change_factor: damping

# TODO: utility functions. main_dfn_2.py uses a logarithmic load metric
# utility and a geometric user utility:
#   MetricUtility.metric_utility_fn['load'] = logarithmic
#   Utility.user_utility_fn = lambda alpha, mu: round(mu['load'] ** alpha * mu['delay'] ** (1 - alpha), 4)
# These can't be set from a config yet (see src/Importer.py), so this
# config uses the defaults in Utility.py and MetricUtility.py.

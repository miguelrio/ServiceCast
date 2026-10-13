# Config for experiments/main_importer.py: the Cogentco experiment
# (the settings of experiments/main_cog.py, which also uses the default
# utility functions).
#
#   PYTHONPATH=src:scripts python3 experiments/main_importer.py -c scripts/setup/constants_cog_importer.py
#
# main_importer.py requires every name below.

# --- run --------------------------------------------------------------------
SIM_DURATION = 360            # simulated seconds
VERBOSE_LEVEL = 0             # -1: metrics (large runs); 0 and up: protocol debugging (see doc/Logging.md)
VERBOSE_TABLE = 0

# --- topology and placement -------------------------------------------------
GML_FILE = "topologies/gml/Cogentco.gml"
NUM_SERVERS = 5               # placed at random on routers of degree <= 3
NUM_CLIENTS = 5               # likewise, after the servers
SEED = 15112022               # placement and generator seed

# --- workload ---------------------------------------------------------------
SERVICE = "§a"                # the single service every client requests
CLIENT_ARRIVAL_LAMBDA = 0.4   # mean time (s) between requests, all clients together
SESSION_SIZE_LAMBDA = 10      # mean session length (s) ...
SESSION_SIZE_SCALE = 10       # ... times this multiplier

# --- simulator settings (Importer.mappings) ---------------------------------
ALPHA = 0.5                   # Utility.alpha: load/delay weighting
GRAPH_DELAY = 0.1             # Graph.default_propagation_delay (access links)
ROUTER_HOP_BY_HOP = False     # False: first-decide unicast; True: hop-by-hop anycast
ROUTER_FIB_UPT = 0.001        # Router.fib_utility_update_threshold
ROUTER_FORWARD_TO_TREE_CHILDREN_ONLY = False
ROUTER_REMOVE_FIB_ENTRY_WHEN_ALL_UTILITIES_ZERO = True
SERVER_SLOTS = 50             # Server.slots: capacity
SERVER_CF = 0.01              # Server.change_factor: damping

# TODO: utility functions can't be set from a config yet (see
# src/Importer.py); main_cog.py uses the defaults too.

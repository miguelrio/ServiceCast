# --- Per experiment constants ----------------------------------------------
#
# These get loaded into the config context
#
#
# Experiment values

SIM_DURATION = 3600000        # simulated milliseconds per run

SERVICE = "§a"                # the single service every client requests

NUM_SERVERS = 5               # servers attached to core nodes
NUM_CLIENTS = 5               # clients attached to local nodes

SERVER_LOAD_LAMBDA = 55000    # background-load inter-arrival (ms); INERT here: we pass
                              # background_load=False, and Generator.py:216 (the only
                              # line that reads it) is commented out, so it has no effect
CLIENT_ARRIVAL_LAMBDA = 400   # mean inter-arrival time (ms) between client requests
SEED = 15112022               # shared RNG seed for reproducibility
SESSION_SIZE_LAMBDA = 10000   # mean session length (ms)
SESSION_SIZE_SCALE = 10       # dimensionless session-length multiplier

GML_FILE = "topologies/gml/Dfn.gml"     # The topology file of the network to use


# Values which map to System Variables

ALPHA = 0.50                  # Utility load/delay weighting

VERBOSE_LEVEL = 0             # minimum level that emits every needed line
                              # (DECISION_GAP/STALENESS_ERR and SERVICE_FIB all need >= 1)

ROUTER_HOP_BY_HOP = False     # Do routers to hop_by_hop forwarding

SERVER_SLOTS = 50             # server capacity


GRAPH_DELAY = 1000            # Graph.default_propagation_delay in milliseconds

SERVER_CF = 0.01
ROUTER_FIB_UPT = 0.001
                              

# --- END of constants -------------------------------------------------

UTILITY_USER_UTILITY_FN = staticmethod(lambda alpha, metric_utility: round(metric_utility['load'] ** alpha * metric_utility['delay'] ** (1 - alpha), 4))

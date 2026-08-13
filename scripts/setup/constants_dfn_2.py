# --- Per experiment constants ----------------------------------------------
#
# These get loaded into the config context
#
#
# Experiment values

SIM_DURATION = 3600           # simulated seconds per run

SERVICE = "§a"                # the single service every client requests

NUM_SERVERS = 5               # servers attached to core nodes
NUM_CLIENTS = 5               # clients attached to local nodes

SERVER_LOAD_LAMBDA = 55       # background-load inter-arrival; INERT here: we pass
                              # background_load=False, and Generator.py:216 (the only
                              # line that reads it) is commented out, so it has no effect
CLIENT_ARRIVAL_LAMBDA = 0.4   # mean inter-arrival time (s) between client requests
SEED = 15112022               # shared RNG seed for reproducibility
SESSION_SIZE_LAMBDA = 10      # mean session length (s)
SESSION_SIZE_SCALE = 10       # session-length multiplier (effective session ~= lambda*scale)

GML_FILE = "topologies/gml/Dfn.gml"     # The topology file of the network to use


# Values which map to System Variables

ALPHA = 0.50                  # Utility load/delay weighting

VERBOSE_LEVEL = 0             # minimum level that emits every needed line
                              # (DECISION_GAP/STALENESS_ERR and SERVICE_FIB all need >= 1)

ROUTER_HOP_BY_HOP = False     # Do routers to hop_by_hop forwarding

SERVER_SLOTS = 50             # server capacity


GRAPH_DELAY = 1               # Value for Graph.default_propagation_delay

SERVER_CF = 0.01
ROUTER_FIB_UPT = 0.001
                              

# --- END of constants -------------------------------------------------


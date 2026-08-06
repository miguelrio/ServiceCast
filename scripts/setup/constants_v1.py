# --- Per experiment constants ----------------------------------------------
#
# These get loaded into the config context
# 
# These define the scenario every sweep cell shares; only the swept axes
# (server_cf, router_cf, propagation_delay) vary between runs.
SIM_DURATION = 360            # simulated seconds per run
ALPHA = 0.50                  # Utility load/delay weighting
SLOTS = 50                    # server capacity
SEED = 15112022               # shared RNG seed for reproducibility
SERVICE = "§a"                # the single service every client requests

NUM_SERVERS = 5               # servers attached to core nodes
NUM_CLIENTS = 5               # clients attached to local nodes

SERVER_LOAD_LAMBDA = 55       # background-load inter-arrival; INERT here: we pass
                              # background_load=False, and Generator.py:216 (the only
                              # line that reads it) is commented out, so it has no effect
CLIENT_ARRIVAL_LAMBDA = 0.4   # mean inter-arrival time (s) between client requests
SESSION_SIZE_LAMBDA = 10      # mean session length (s)
SESSION_SIZE_SCALE = 10       # session-length multiplier (effective session ~= lambda*scale)


# Network settings
DELAYS = (0.1, 0.5, 1.0, 2.0, 4.0)      # A collection of delays for Links

GML_FILE = "topologies/gml/Dfn.gml"     # The topology file of the network to use

HOP_BY_HOP = False                      # Do routers to hop_by_hop forwarding



# Swept axes, shared so the log-based collector samples the identical grid.
# Ranges trimmed to the region where the metrics actually vary for this
# configuration (Dfn topology, Server.slots=50, this request distribution).
# Past Server.change_factor=0.32 no server ever clears its announcement
# threshold (max observed |Δload| ~0.32 = ~16/50 slots), and past
# Router.fib_utility_update_threshold=0.16 no replica's utility gap is ever
# large enough to switch the FIB (U=1-0.5*load-0.5*delay on a compact graph),
# so the upper ~two-thirds of the original axes were a flat dead zone.
SERVER_CFS = [0.0, 0.1, 0.2, 0.3]
ROUTER_CFS = [0.0, 0.1, 0.2, 0.3]


# Output order for the log build. The 9 shared metrics keep the probe's names; the
# 3 hop metrics are renamed to the honest RECV-based quantities the log provides.
LOG_METRIC_FIELDS = ["created", "recv_total", "accuracy",
                     "mean_err_all", "mean_err_subopt", "max_err", "fib_updates",
                     "blocked_rate", "accuracy_arrival", "mean_err_arrival",
                     "recv_announce", "recv_withdraw"]

VERBOSE_LEVEL = 1   # minimum level that emits every needed line
                    # (DECISION_GAP/STALENESS_ERR and SERVICE_FIB all need >= 1)


# --- END of constants -------------------------------------------------


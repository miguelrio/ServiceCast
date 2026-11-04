# Setup Constants

These constants are used for setting up experimental runs.

The constants can be used for:
- configuring the experiment
- setting system variable

## Experiment Values

```
SIM_DURATION = 360000         # simulated milliseconds per run


SERVICE = "§a"                # the single service every client requests
NUM_SERVERS = 5               # servers attached to core nodes
NUM_CLIENTS = 5               # clients attached to local nodes

SERVER_LOAD_LAMBDA = 55000    # background-load inter-arrival (ms); INERT here: we pass
                              # background_load=False, and Generator.py:216 (the only
                              # line that reads it) is commented out, so it has no effect
CLIENT_ARRIVAL_LAMBDA = 400   # mean inter-arrival time (ms) between client requests
SEED = 15112022               # shared RNG seed for reproducibility
SESSION_SIZE_LAMBDA = 10000   # mean session length (ms)
SESSION_SIZE_SCALE = 10       # dimensionless session-length multiplier (effective session ~= lambda*scale)

GML_FILE = "topologies/gml/Dfn.gml"     # The topology file of the network to use

```

## Mapping Values to System Variables
Here we show the mapping of setup constants to the System Variables
outlined [here](Variables.md).

The system variables are used for configuring each experimental
run, but here were present the setup constants which can
be used as an alternative way to configure then.

| Variable                                | Constant         |
| ---                                     | ---              |
| Utility.alpha                           | ALPHA            |
| Verbose.level                           | VERBOSE\_LEVEL   |
| Verbose.table                           | VERBOSE\_TABLE   |
| Graph.default\_propagation\_delay       | GRAPH\_DELAY     |
| Router.hop\_by\_hop                 | ROUTER\_HOP\_BY\_HOP |
| Router.fib\_utility\_update\_threshold  | ROUTER\_FIB\_UPT |
| Server.slots                            | SERVER\_SLOTS    |
| Server.change\_factor                   | SERVER\_CF       |


These are loaded directly by the ```Importer```.

## Extended list values

For some situations, such as running scripts we use a list of values
for a variable.

```
GRAPH_DELAYS = [100, 500, 1000, 2000, 4000]      # A collection of delays for Links (ms)
SERVER_CFS = [0.0, 0.1, 0.2, 0.3]
ROUTER_FIB_UPTS = [0.0, 0.1, 0.2, 0.3]
```

## Example configuration

```
SIM_DURATION = 360000         # simulated milliseconds per run
ALPHA = 0.50                  # Utility load/delay weighting
SLOTS = 50                    # server capacity
SEED = 15112022               # shared RNG seed for reproducibility
SERVICE = "§a"                # the single service every client requests
NUM_SERVERS = 5               # servers attached to core nodes
NUM_CLIENTS = 5               # clients attached to local nodes
SERVER_LOAD_LAMBDA = 55000    # background-load inter-arrival (ms); INERT here: we pass
CLIENT_ARRIVAL_LAMBDA = 400   # mean inter-arrival time (ms) between client requests
SESSION_SIZE_LAMBDA = 10000   # mean session length (ms)
SESSION_SIZE_SCALE = 10       # dimensionless session-length multiplier (effective session ~= lambda*scale)
GRAPH_DELAYS = [100, 500, 1000, 2000, 4000]      # A collection of delays for Links (ms)
GML_FILE = "topologies/gml/Dfn.gml"     # The topology file of the network to use
HOP_BY_HOP = False                      # Do routers to hop_by_hop forwarding
SERVER_CFS = [0.0, 0.1, 0.2, 0.3]
ROUTER_FIB_UPTS = [0.0, 0.1, 0.2, 0.3]
LOG_METRIC_FIELDS = ["created", "recv_total", "accuracy",
VERBOSE_LEVEL = 1   # minimum level that emits every needed line
```

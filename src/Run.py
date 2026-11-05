# Run -- the settings of one simulation run that belong to no simulator class:
# which topology, how long, the seed and the client workload.
#
# Like the simulator's own settings (Server.slots, Router.hop_by_hop, ...),
# each is a class attribute holding its default.  A config file read by
# Importer overrides them, and experiments/main.py's --set overrides the config.
#
# Times here are in MILLISECONDS, like every simulation time value
# (src/units.py), and pass to Network.start() and the generators unchanged.


class Run:
    # the simulator-ready GML topology (servers and clients placed); no
    # default: a run must name its topology, in the config or with --set
    gml_file = None

    # simulated time (ms); the main-sweep run length
    until = 500000

    # the seed for every random draw of the run
    seed = 15112022

    # the single service every client requests
    service = "§a"

    # client requests: one Poisson process over all clients, with this mean
    # time between requests (ms), so the total rate is 1/arrival_mean
    # requests per ms whatever the number of clients.  The right value
    # depends on the network and the target load: every config should set it.
    arrival_mean = 400

    # session length: exponential with mean session_mean * session_scale
    # (ms); passed to the generator as size_lambda and size_scale_factor
    # (mean session 10000 x 10 ms = 100 s)
    session_mean = 10000
    session_scale = 10

    # which of the GML's clients send requests:
    #   None -- all of them
    #   0    -- none (a control run: only the servers' initial announcements)
    #   N    -- the first N, in file order (all of them, with a warning, if
    #           the file has fewer)
    clients = None

    # servers send a background load update every 10 s
    server_background_load = False

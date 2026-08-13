
from Graph import Graph
from Network import Network
from Server import Server
from Router import Router
from Client import Client
from Generator import Generator
from Verbose import Verbose
from Utility import Utility
from pathlib import Path
from MetricUtility import MetricUtility, linear, logarithmic, sigmoid
import simpy
import random

# sclayman:
# Using a topology loaded from the DFN gml file

# v2 of main_dfn randomises the attachment of clients and servers to "local" nodes, i.e. those with degree <=3

# Use a topology from the DFN gml file
def topology_setup():
    Verbose.level = 2
    Verbose.table = 2

    # Set client request forwarding mode: hop-by-hop anycast (True) or first-decide unicast (False)
    Router.hop_by_hop = False

    # Default propagation delay.
    # If this is not configured explicitly here then a default value of 1 will be used, see Graph.py.    
    # This allows us to override link delays specified in the GML file
    # and set some hardcoded delays for links to clients and servers in Network. 
    Graph.default_propagation_delay = 0.1

    # Set alpha value
    Utility.alpha = 0.5

    # Set slots
    Server.slots = 50

    # Server change factor damping
    Server.change_factor = 0.01

    # Router change factor damping
    Router.fib_utility_update_threshold = 0.001

    # Set policy to remove FIB entries when all utilities are zero (default is true if not set here)
    Router.remove_fib_entry_when_all_utilities_zero = True
    
    print(f"""Simulation parameters:
    Verbose.level = {Verbose.level}
    Verbose.table = {Verbose.table}
    Router.hop_by_hop = {Router.hop_by_hop}
    Graph.default_propagation_delay = {Graph.default_propagation_delay}
    Utility.alpha = {Utility.alpha}
    Server.slots = {Server.slots}
    Server.change_factor = {Server.change_factor}
    Router.fib_utility_update_threshold = {Router.fib_utility_update_threshold}
    """)
    
    # 1 - Define the topology
    repo_root = Path(__file__).resolve().parents[1]
    gml_file = repo_root / "topologies/gml/Dfn.gml"
    if Verbose.level >= 3:
        print("Network - DFN")    

    # 2 - create the simpy environment 
    env = simpy.Environment()

    # 3 - build the network: topology -> graph -> network
    graph = Graph.from_gml_file(gml_file)
    if Verbose.level >= 3:
        print("GRAPH")
        graph.print()
        print ("graph nodes = " + str(graph.nodes()))
        print("graph edges = " + str(graph.edges()))

    # 4 - graph -> network
    network = Network.from_graph(graph, env)
    if Verbose.level >= 3:
        print("Network nodes = " + str(network.nodes()))
        print("Network edges = " + str(network.edges()))

    # 5 - determine core and local nodes   
    # filter out core nodes -  degree > 3
    core = [r for r in network.network_nodes() if r.degree() > 3]
    # filter out local nodes -  degree <= 3
    local = [r for r in network.network_nodes() if r.degree() <= 3]
    if Verbose.level >= 3:
        print("core  (degree > 3)  = " + str([(r.id(), r.degree()) for r in core]))
        print("local (degree <= 3) = " + str([(r.id(), r.degree()) for r in local]))

    # 6 - add servers and clients to the network    
    if Verbose.level >= 3:
        print("--- Add Servers and Clients to Network ---")
    # add some servers
    servers = []
    # add some clients
    clients = []
    # both servers and clients are connected to local nodes
    num_servers = 5
    num_clients = 5
    needed = num_servers + num_clients

    if len(local) < needed:
        raise ValueError(
            f"Not enough local nodes: need {needed}, found {len(local)}"
        )

    # fixed seed for reproducible random assignment; remove seed for different each run
    rng = random.Random(15112022)
    chosen_local_nodes = rng.sample(local, needed)
    server_nodes = chosen_local_nodes[:num_servers]
    client_nodes = chosen_local_nodes[num_servers:]
    for s, server_dest in enumerate(server_nodes, start=1):
        server_name = "s" + str(s)
        servers.append(server_name)
        if Verbose.level >= 3:
            print("Add " + str(server_name) + " at " + str(server_dest))
        network.add_server(server_name, server_dest, Graph.default_propagation_delay)
    for c, client_dest in enumerate(client_nodes, start=1):
        client_name = "c" + str(c)
        clients.append(client_name)
        if Verbose.level >= 3:
            print("Add " + str(client_name) + " at " + str(client_dest))
        network.add_client(client_name, client_dest, Graph.default_propagation_delay)

    # 7 - now calculate all the forwarding tables
    network.calculate_forwarding_tables()   

    # 8 - dump graphviz file to tmp
    network.graphviz_to_file("dfn2.gv", dir="tmp")

    # some cross check print outs
    if Verbose.level >= 3:
        dijkstra_c1 = Graph.dijkstra_algorithm(network, 'c1')
        print("Network: dijkstra from c1 = " + str(dijkstra_c1))
        print("Network: dijkstra routing from c1 = " + str(network.dijkstra_to_routing(dijkstra_c1)))
        dijkstra_c4 = Graph.dijkstra_algorithm(network, 'c4')
        print("Network: dijkstra from c4 = " + str(dijkstra_c4))
        print("Network: dijkstra routing from c4 = " + str(network.dijkstra_to_routing(dijkstra_c4)))
        print("Network = ")
        network.print()

    # 9 - setup generators   
    for server_name in servers:
        generator = Generator.server_load_event_generator(network, server_name, ["§a"], seed=15112022, background_load=False)

    # Clients 'c1' ... 'cn' generate request packets from arriving events
    # arrival_lambda is the mean arrival time between requests (in seconds)
    # size_lambda is the mean length/duration of the sessions (in seconds)
    # size_scale_factor is a multiplier for the session duration
    # Example: arrival_lambda=0.5, size_lambda=10, size_scale_factor=10 means an average of 2 requests per second, each lasting on average 100 seconds. This gives an average of 200 concurrent requests in the system. If there are 5 servers, each server will have an average of 40 concurrent requests.
    # Note that it doesn't matter whether we have size_lambda=10, size_scale_factor=10 or size_lambda=100, size_scale_factor=1, the average session duration is the same (100 seconds). The scale factor is just a multiplier for the session duration.
    generator_m1 = Generator.multi_client_event_generator(network, clients, "§a", arrival_lambda=0.2, size_lambda=10, size_scale_factor=10, seed=15112022)

    # 9.5 - configure utility functions

    # NB: load is already normalised to 0 -> 1, so scaling it again by
    # 2 * Server.slots leaves the load metric utility nearly constant.
    # Kept as-is to preserve this experiment's existing results.
    # MetricUtility.metric_scale['load'] = 1
    # MetricUtility.metric_utility_fn['load'] = lambda load, scale: (1-(0.12*(load/scale))) if (load/scale) < 0.8  else (4.5-(4.5*(load/scale)))
    # MetricUtility.metric_utility_fn['load'] = lambda load, scale: (1-(load/scale))
    MetricUtility.metric_utility_fn['load'] = logarithmic


    # delay: raw 0 -> scale (the network diameter)
    # NB: delay/scale is always <= 1, so the `else 0` branch has never been reachable
    
    MetricUtility.metric_scale['delay'] = network.network_diameter()

    # MetricUtility.metric_utility_fn['delay'] = lambda delay, scale: (1-(0.1*(delay/scale))) if delay/scale <= 10 else 0
    # MetricUtility.metric_utility_fn['delay'] = lambda delay, scale: (1 if delay/scale <= 3/8 else 0)
    MetricUtility.metric_utility_fn['delay'] = lambda delay, scale: (1 - delay / scale)
    # MetricUtility.metric_utility_fn['delay'] = logarithmic
    # MetricUtility.metric_utility_fn['delay'] = lambda delay, scale: ((1 - delay/scale) if delay/scale <= 3/network.network_diameter() else 0)


    # actual utility fn (lower = worse, higher = better)
    # Utility.user_utility_fn = staticmethod(lambda alpha, metric_utility: 0)
    Utility.user_utility_fn = staticmethod(lambda alpha, metric_utility: round(metric_utility['load'] ** alpha * metric_utility['delay'] ** (1 - alpha), 4))
    # Utility.user_utility_fn = staticmethod(lambda alpha, metric_utility: round(metric_utility['load'] * alpha + metric_utility['delay'] * (1 - alpha), 4))

    # 10 - run
    if Verbose.level >= 3:
        print("RUN ----------------------------------------------------------------")
    network.start(until=360)


# go !
topology_setup()


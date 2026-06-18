from Graph import Graph
from Network import Network
from Server import Server
from Router import Router
from Client import Client
from Generator import Generator
from Verbose import Verbose
from Utility import Utility, Place
import simpy

# sclayman:
# Using a topology loaded from the DFN gml file

# Use a topology from the DFN gml file
def topology_setup():
    Verbose.level = 2
    Verbose.table = 1

    # Set routing mode: hop-by-hop anycast (True) or first-decide unicast (False)
    Router.hop_by_hop = False

    # Network optimal_utility_timing
    Network.optimal_utility_timing = Place.Replica

    # Default propagation delay.
    # If this is not configured explicitly here then a default value of 1 will be used, see Graph.py.    
    # This allows us to override link delays specified in the GML file
    # and set some hardcoded delays for links to clients and servers in Network. 
    Graph.default_propagation_delay = 0.1

    # Set alpha value
    Utility.alpha = 0.50

    # Set slots
    Server.slots = 50

    # Server change factor damping
    Server.change_factor = 0.01

    # Router change factor damping
    Router.fib_utility_update_threshold = 0.001
    
    print(f"""Simulation parameters:
    Verbose.level = {Verbose.level}
    Verbose.table = {Verbose.table}
    Router.hop_by_hop = {Router.hop_by_hop}
    Network.optimal_utility_timing = {Network.optimal_utility_timing}
    Graph.default_propagation_delay = {Graph.default_propagation_delay}
    Utility.alpha = {Utility.alpha}
    Server.slots = {Server.slots}
    Server.change_factor = {Server.change_factor}
    Router.fib_utility_update_threshold = {Router.fib_utility_update_threshold}
    """)
    
    # 1 - Define the topology
    print("Network - DFN")
    gml_file = "gml/Dfn.gml"

    # 2 - create the simpy environment 
    env = simpy.Environment()

    # 3 - build the network: topology -> graph -> network

    print("SETUP ----------------------------------------------------------------")

    graph = Graph.from_gml_file(gml_file)

    print("GRAPH")
    graph.print()

    print ("graph nodes = " + str(graph.nodes()))

    print("graph edges = " + str(graph.edges()))

    # graph -> network

    print("--- Convert Graph to Network Begin ---")
    
    network = Network.from_graph(graph, env)

    print("Network nodes = " + str(network.nodes()))
    print("Network edges = " + str(network.edges()))

    # filter out core nodes -  degree > 3
    core = [ r  for r in network.network_nodes() if r.degree() > 3 ]
    # filter out local nodes -  degree <= 3
    local = [ r  for r in network.network_nodes() if r.degree() <= 3 ]

    print("core  (degree > 3)  = " + str([(r.id(), r.degree()) for r in core]))
    print("local (degree <= 3) = " + str([(r.id(), r.degree()) for r in local]))

    print("--- Add Servers and Clients to Network ---")

    # add some servers
    servers = []
    
    # connected to core nodes
    server_count = range(1,6)
    for s in server_count:
        server_name = "s" + str(s)
        servers.append(server_name)
        server_dest = core[s]
        print("Add " + str(server_name) + " at " + str(server_dest))
        network.add_server(server_name, server_dest, Graph.default_propagation_delay)

    
    # add some clients
    clients = []
    
    # connected to local nodes
    client_count = range(1,6)
    for c in client_count:
        client_name = "c" + str(c)
        clients.append(client_name)
        client_dest = local[c]
        print("Add " + str(client_name) + " at " + str(client_dest))
        network.add_client(client_name, client_dest, Graph.default_propagation_delay)

    # now calculate all the forwarding tables
    network.calculate_forwarding_tables()
    

    # some cross check print outs
    if Verbose.level >= 3:
        dijkstra_c1 = Graph.dijkstra_algorithm(network, 'c1')
        print("Network: dijkstra from c1 = " + str(dijkstra_c1))
        print("Network: dijkstra routing from c1 = " + str(network.dijkstra_to_routing(dijkstra_c1)))
        dijkstra_c4 = Graph.dijkstra_algorithm(network, 'c4')
        print("Network: dijkstra from c4 = " + str(dijkstra_c4))
        print("Network: dijkstra routing from c4 = " + str(network.dijkstra_to_routing(dijkstra_c4)))

    # Network
    print("Network = ")
    network.print()

    # dump graphviz file to tmp
    with open('/tmp/dfn.gv', mode='w') as file_object:
        network.graphviz(file=file_object)
        
    # Services are not addresses -- they start with §

    # Server 's1' generates packets from arriving events
    # and sends to service 'a'  indicated by "§a"
    for server_name in servers:
        generator = Generator.server_load_event_generator(network, server_name, ["§a"], exponential_lambda=55, seed=15112022, background_load=False)

    # Clients 'c1' ... 'c5' generates packets from arriving events
    # arrival_lambda is the mean arrival time between requests (in seconds)
    # size_lambda is the mean length/duration of the sessions (in seconds)
    # size_scale_factor is a multiplier for the session duration
    # Example: arrival_lambda=0.5, size_lambda=10, size_scale_factor=10 means an average of 2 requests per second, each lasting on average 100 seconds. This gives an average of 200 concurrent requests in the system. If there are 5 servers, each server will have an average of 40 concurrent requests.
    # Note that it doesn't matter whether we have size_lambda=10, size_scale_factor=10 or size_lambda=100, size_scale_factor=1, the average session duration is the same (100 seconds). The scale factor is just a multiplier for the session duration.
    generator_m1 = Generator.multi_client_event_generator(network, clients, "§a", arrival_lambda=5, size_lambda=10, size_scale_factor=10, seed=15112022)

    # run
    print("RUN ----------------------------------------------------------------")

    network.start(until=3600)


# go !
topology_setup()


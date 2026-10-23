import os
from Graph import Graph
from Router import Router
from Link import BidirectionalLink
from Host import Host
from Server import Server
from Client import Client
from Verbose import Verbose
from Utility import Utility
from units import s_to_ms
from MetricUtility import MetricUtility
from Routing import Routing
from collections import OrderedDict
from Gml import read_gml, write_gml
import sys


# PDF notation for the per-request metric lines (see the BEST_REPLICA_UTILITY
# notes PDF). The PDF numbers five measurable quantities:
#   1: SEL_UTIL_EST = u(s_sel, t_update)        router's FIB belief
#   2: SEL_UTIL_SEL = u(s_sel, t_sel)           selected, truth at selection
#   3: SEL_UTIL_ARR = u(s_sel, t_arr)           selected, truth at arrival
#   4: BEST_UTIL_SEL = u(best(t_sel), t_sel)    best, truth at selection
#   5: BEST_UTIL_ARR = u(best(t_arr), t_arr)    best, truth at arrival
# and three metrics: A = 4 - 1, B = 5 - 3, C = 2 - 1.
# At Verbose.level >= 1 each annotated field is printed as field(NOTATION): value
# and the metric formula is shown after the tag. Level 0 output is unchanged.
GAP_NOTATIONS = {
    'OUTCOME_GAP':   { 'formula': 'B = BEST_UTIL_ARR - SEL_UTIL_ARR',
                       'selected': {'time': 't_arr',    'server': 'SEL_ID',      'utility': 'SEL_UTIL_ARR'},
                       'compared': {'time': 't_arr',    'server': 'BEST_ID_ARR', 'utility': 'BEST_UTIL_ARR'},
                       'minload':  {'time': 't_arr',    'server': 'MIN_LOAD_ID', 'utility': 'MIN_LOAD_UTIL'} },
    'DECISION_GAP':  { 'formula': 'A = BEST_UTIL_SEL - SEL_UTIL_EST',
                       'selected': {'time': 't_update', 'server': 'SEL_ID',      'utility': 'SEL_UTIL_EST'},
                       'compared': {'time': 't_sel',    'server': 'BEST_ID_SEL', 'utility': 'BEST_UTIL_SEL'} },
    'STALENESS_ERR': { 'formula': 'C = SEL_UTIL_SEL - SEL_UTIL_EST',
                       'selected': {'time': 't_update', 'server': 'SEL_ID',      'utility': 'SEL_UTIL_EST'},
                       'compared': {'time': 't_sel',    'server': 'SEL_ID',      'utility': 'SEL_UTIL_SEL'} },
}

# Two utilities within this distance count as EQUAL ("a tiny difference,
# e.g. 1e-9" in the BEST_REPLICA_UTILITY notes PDF)
UTILITY_EQUAL_EPSILON = 1e-9


class Network:
    def __init__(self, env = None):
        """ Create a network
        """
        self.routers = OrderedDict()         # a dictionary of routers
        self.links = []           # a list of links
        self.servers = OrderedDict()         # a dictionary of servers
        self.clients = OrderedDict()         # a dictionary of clients
        self.env = env            # an Environment
        self.latency_table = {}

        # what route computation (Routing.compute_tables) needs from the GML:
        # link_key(a, b) -> (type, source, target) for links with a type
        # (c2p, p2p, internal, hosts, access); source/target keep the GML
        # order, which gives a c2p link its direction
        self.link_types = {}
        # node name -> tier (stub, transit, tier1), to orient c2p links
        self.node_tiers = {}
        # nodes marked Internal 0 in the GML: never used as transit
        self.external_nodes = set()

        # every run starts its end-of-run counters from zero
        Router.reset_counters()
        Server.server_metrics_created = 0

        # dropped nodes
        self.dropped = []

        # aggregate of replica capacity
        # gives a total view over the network
        # replica name -> dict of values like replica_capacity_total 
        self.replica_capacity = dict()
        # replica_capacity initial total
        # need 1 for slots and capacity 
        self.replica_capacity_total = { 'load': 0, 'no_of_flows': 0, 'slots': 1, 'capacity' : 1 }
 
        # aggregate of replica load utility
        # gives a total view over the network
        # replica name -> load value
        self.replica_normalised_load = dict()

        # the network diameter
        self.network_diameter_val = 0


    # Convert from a graph to a network
    #
    # Options:
    # use_default_weights=False -- (default) use value of weight from graph
    # use_default_weights=True  -- use Graph.default_propagation_delay for weight
    #
    # drop_external=True  -- (default) drop nodes which are labelled External
    # drop_external=False -- keep nodes which are labelled External
    @classmethod
    def from_graph(cls, graph, env, use_default_weights=False, drop_external=True):
        """ Create a network from a Graph representation of an adjacency list
        """

        # create the Network
        # add a handle to the simpy Environment
        network = Network(env)

        graph_meta_data = graph.get_meta_data()
        
        # print("G. meta_data = " + str(graph_meta_data), file=sys.stderr)

        # first we create the list of Routers
        for i in range(len(graph)):
            # convert number to name
            name = graph.name_of(i)

            meta_data = graph.get_node_meta_data(name)
            
            #print("name_of " + str(i) + " = " + name)
            #print("G. node_meta_data[" + name + "] = " + str(meta_data), file=sys.stderr)

            if drop_external and graph.node_is_external(meta_data):
                if Verbose.level >= 2:
                    print("Network: Not added node -- External for " + name)

                network.dropped.append(name)
                continue
            else:
                # what route computation needs from the node meta data
                if meta_data is not None:
                    if 'tier' in meta_data:
                        network.node_tiers[name] = meta_data['tier']
                    if meta_data.get('External') == 1 or meta_data.get('Internal') == 0:
                        network.external_nodes.add(name)

                # check type attribute
                # this is output by Miguel's topology tool
                if meta_data != None and 'type' in meta_data:
                    if meta_data['type'] == 'router':
                        # create a Router
                        router = Router(name, network)
                        # now add it to the routers
                        network.routers[name] = router
                    elif meta_data['type'] == 'server':
                        # create a Server
                        server = Server(name, network)
                        # now add it to the routers
                        network.routers[name] = server
                        # now add it to the servers
                        network.servers[name] = server
                    elif meta_data['type'] == 'client':
                        # create a Client
                        client = Client(name, network)
                        # now add it to the routers
                        network.routers[name] = client
                        # now add it to the clients
                        network.clients[name] = client
                    else:
                        # unknown type 
                        # Assume the default
                        # create a Router
                        router = Router(name, network)
                        # now add it to the routers
                        network.routers[name] = router

                else:
                    # default - add a Router
                    # create a Router
                    router = Router(name, network)
                    # now add it to the routers
                    network.routers[name] = router

        # now add the links
        demand_edges = []
        for i in range(len(graph)):
            # convert number to name
            name = graph.name_of(i)
            # get the adjacency list
            nodes = graph.adjacency(i)
            # get meta data
            meta_data = graph.get_node_meta_data(name)
            
            # try all nodes at 'name'
            # print("from_graph: nodes at " + name + " = " + str(nodes))
            # print("E. node_meta_data[" + name + "] = " + str(meta_data), file=sys.stderr)

            if drop_external and graph.node_is_external(meta_data):
                if Verbose.level >= 2:
                    print("Network: Not added in nodes -- External for " + name)
                continue

            else:
                for neighbour in nodes:
                    # skip through [ ('b', 1), ('c', 4)]
                    (neighbour_name, weight) = neighbour

                    neighbour_meta_data = graph.get_node_meta_data(neighbour_name)

                    # print("   node_meta_data[" + neighbour_name + "] = " + str(neighbour_meta_data), file=sys.stderr)

                    if drop_external and graph.node_is_external(neighbour_meta_data):
                        if Verbose.level >= 2:
                            print("Network: Not added edge -- External for " + neighbour_name)
                        continue

                    else: 
                        # setup edge
                        current = network.routers[name]
                        neighbour_obj = network.routers[neighbour_name]

                        # a link between two hosts is a client-server
                        # demand edge, not a network link: ignore it
                        # (each edge is seen from both ends)
                        if isinstance(current, Host) and isinstance(neighbour_obj, Host):
                            if name < neighbour_name:
                                demand_edges.append((name, neighbour_name))
                            continue

                        actual_weight = weight

                        # double check weight
                        if use_default_weights:
                            actual_weight = Graph.default_propagation_delay
                        else:
                            # check if weight is 0
                            if weight == 0:
                                actual_weight = Graph.default_propagation_delay


                        # add the neighbours for current to neighbour_obj
                        # and neighbour_obj to current
                        (status1, link1) = current.add_neighbour(neighbour_obj, actual_weight)
                        (status2, link2) = neighbour_obj.add_neighbour(current, actual_weight)

                        # create the BidirectionalLink
                        if status1 == "create" or status2 == "create":
                            network.links.append(BidirectionalLink(link1, link2))
                            edge_type = graph.edge_type(name, neighbour_name)
                            if edge_type is not None:
                                network.link_types[Network.link_key(name, neighbour_name)] = edge_type

        if demand_edges:
            print("Network: ignored {} host-to-host (demand) edges, e.g. {} -- {}".format(len(demand_edges), *demand_edges[0]), file=sys.stderr)

        if Verbose.level >= 3:
            print("dropped = " + str(network.dropped))
        
        return network
            
    # the key a link is stored under in link_types: its two end names, sorted
    @staticmethod
    def link_key(a, b):
        return (a, b) if a <= b else (b, a)

    # Build a graph from a GML file
    @classmethod
    def from_gml_file(cls, gml_file, env):
        """ Add some neighbours from a GML file.
        """
        graph = read_gml(gml_file)

        return Network.from_graph(graph, env)

    def start(self, until=1000):
        """Start the Network processing.
        Calls back to the simpy env to start elements.

        until is the run bound in SECONDS (the human-interface convention,
        see src/units.py); the simpy clock runs in milliseconds, so the
        bound converts here -- the single boundary crossing for this knob.
        """

        # start each of the routers
        for router in self.routers.values():
            router.start()

        # start the simpy environment run
        self.env.run(s_to_ms(until))

        # ServerMetric updates dropped as off the unicast path (0 when
        # forward_to_tree_children_only is on); an end-of-run count, so
        # printed at the metrics level too
        if Verbose.level >= -1:
            print("{:.3f}: INVALID_ROUTE_DROPS {} (forward_to_tree_children_only = {})".format(self.env.now, Router.invalid_route_drops, Router.forward_to_tree_children_only))

        if Verbose.level >= -1:
            self.print_metrics_summary()

    # End-of-run SUMMARY_ lines (Verbose.level >= -1): the totals the
    # analysis scripts would otherwise count from per-update lines
    def print_metrics_summary(self):
        now = self.env.now
        print("{:.3f}: {:5s} SUMMARY_SERVER_METRICS created: {} announce: {} withdraw: {}".format(
            now, "Net ", Server.server_metrics_created,
            Router.recv_server_metric.get('A', 0), Router.recv_server_metric.get('W', 0)))
        for router_id in sorted(Router.fib_actions):
            c = Router.fib_actions[router_id]
            print("{:.3f}: {:5s} SUMMARY_FIB_ROUTER SET: {} KEEP: {} CHANGED: {} REMOVED: {}".format(
                now, router_id, c['SET'], c['KEEP'], c['CHANGED'], c['REMOVED']))

    # contains router
    # pass in name or Router
    def contains_router(self, r):
        return self.contains_node(r)

    # pass in name or Router
    def contains_node(self, r):
        if type(r) == int:
            # it's an int -- check size
            return r < len(self.routers)

        elif isinstance(r, str):
            # we just got a name
            if (r in self.routers):
                return True
            else:
                return False
        else:
            # get the id() of the object r
            if (r.id() in self.routers):
                return True
            else:
                return False

    # add a node
    def add_node(self, name):
        # create a Router
        router = Router(name, self)
        # now add it to the routers
        self.routers[name] = router

        
    # add a host to the network and link it to a specified router
    def add_host(self, host, router, weight=1):
        """Add an edge from a Host to a Router.
           Pass in a Host and a Router.
        """

        if isinstance(host, Host):
            # now add it to the routers and add a link
            self.add_edge(host, router, weight)
        else:
            raise TypeError("host must be a Host")

    # add a client to the network and link it to a specified router
    def add_client(self, host, router, weight=1, count=1):
        """Add an edge from a Client to a Router.
           Pass in a name or a Client, and a Router.
        """
        
        if isinstance(host, Client):
            # now add it to the routers and add a link
            self.add_edge(host, router, weight)
            network.clients[host.id()] = host
            # set the count
            host.count = count

        elif isinstance(host, str):
            # got a name
            # create Client and pass in Network
            client = Client(host, self)
            self.add_edge(client, router, weight)
            self.clients[host] = client
            # set the count
            client.count = count
        else:
            raise TypeError("host must be a Client or a name")

    # add a server to the network and link it to a specified router
    def add_server(self, host, router, weight=1):
        """Add an edge from a Server to a Router.
           Pass in a name or a Server, and a Router.
        """

        if isinstance(host, Server):
            # now add it to the routers and add a link
            self.add_edge(host, router, weight)
            network.servers[host.id()] = host

        elif isinstance(host, str):
            # got a name
            # create Server and pass in Network
            server = Server(host, self)
            self.add_edge(server, router, weight)
            self.servers[host] = server
        else:
            raise TypeError("host must be a Server or a name")


    # add an edge
    # add new nodes if needed
    # return the new edge
    # or None, if nothing created
    def add_edge(self,n1, n2, weight=1):
        """Add an edge from one Router to another Router.
           Pass in 2 Routers. Binds in the Environment to both Routers.
        """

        # does n1 exist
        r1 = None

        if isinstance(n1, int):
            # we got a number
            r1 = self[n1]
            if Verbose.level >= 2:
                print("Net: add_edge int " + r1.id() + " " + str(r1))
        else:
            if not self.contains_router(n1):
                # new node
                if type(n1) == str:
                    # just got a name
                    # make a Router
                    r1 = Router(n1, self)
                    self.routers[n1] = r1

                    if Verbose.level >= 2:
                        print("Net: " + type(r1).__name__ + " add " + n1)
                else:
                    r1 = n1
                    self.routers[n1.id()] = r1

                    if Verbose.level >= 2:
                        print("Net: " + type(r1).__name__ + " add " + n1.id())
            else:
                # existing node
                if type(n1) == str:
                    # just got a name
                    r1 = self.routers[n1]
                else:
                    r1 = self.routers[n1.id()]
            # bind the Environment to the router
            r1.set_env(self)

            
        # does n2 exist
        r2 = None

        if isinstance(n2, int):
            # we got a number
            r2 = self[n2]
            if Verbose.level >= 2:
                print("Net: add_edge int " + r2.id() + " " + str(r2))
        else:
            if not self.contains_router(n2):
                # new node
                if type(n2) == str:
                    # just got a name
                    # make a Router
                    r2 = Router(n2, self)
                    self.routers[n2] = r2

                    if Verbose.level >= 2:
                        print("Net: " + type(r2).__name__ + " add " + n2)
                else:
                    r2 = n2
                    self.routers[n2.id()] = r2

                    if Verbose.level >= 2:
                        print("Net: " + type(r2).__name__ + " add " + n2.id())
            else:
                # existing node
                if type(n2) == str:
                    # just got a name
                    r2 = self.routers[n2]
                else:
                    r2 = self.routers[n2.id()]
            # bind the Environment to the router
            r2.set_env(self)

        # add the neighbours for the 2 nodes
        (status1, link1) = r1.add_neighbour(r2, weight)
        (status2, link2) = r2.add_neighbour(r1, weight)

        
        # create the BidirectionalLink
        if status1 == "create" or status2 == "create":
            edge = BidirectionalLink(link1, link2)
            self.links.append(edge)
            return edge
        else:
            return None

    # contains link
    def contains_link(self, r1, r2):
        return self.contains_edge(r1, r2)
        
    # contains edge
    def contains_edge(self, r1, r2):
        if isinstance(r1, int):
            # we got a number
            r1 = self.name_of(r1)
            
        if isinstance(r2, int):
            # we got a number
            r2 = self.name_of(r2)
            
        # edges:  [('b', 'a', 1), ('c', 'a', 4), ('d', 'b', 3), ('e', 'b', 2), ('c', 'd', 1) ...]

        found = [ e for e in  self.edges() if (e[0] == r1 and e[1] == r2) or  (e[0] == r2 and e[1] == r1) ]

        if len(found) > 0:
            return True
        else:
            return False

    # get a specific node
    def node(self, r):
        """Get the node represented by val.
           Can be a Router or a name or a number"""
        
        if isinstance(r, int):
            name = self.name_of(r)
            return self.routers[name]
        elif isinstance(r, str):
            return self.routers[r]
        else:
            # it's a router
            return self.routers[r.id()]

    # get a specific client
    def get_client(self, r):
        """Get the Client represented by val."""
        
        if isinstance(r, int):
            name = self.name_of(r)
            return self.clients[name]
        elif isinstance(r, str):
            return self.clients[r]
        else:
            # it's a client
            return self.clients[r.id()]

    # get a specific server
    def get_server(self, r):
        """Get the Server represented by val."""
        
        if isinstance(r, int):
            name = self.name_of(r)
            return self.servers[name]
        elif isinstance(r, str):
            return self.servers[r]
        else:
            # it's a Server
            return self.servers[r.id()]

    def weight(self, node1, node2):
        "Returns the weight of an edge between two nodes."
        router1 = self.node(node1)
        router2 = self.node(node2)
        
        return  router1.weight_edge(router2)

        

    # index into network by node name
    # returns a router
    def __getitem__(self, val):
        """Get network[val]"""
        if isinstance(val, int):
            name = self.name_of(val)
            return self.routers[name]
        else:
            return self.routers[val]

    # The size of the network
    def __len__(self):
        return len(self.routers)

    # contains a val
    def __contains__(self, val):
        return contains_router(val)

    # get router ids
    def nodes(self):
        return [ r.id()  for r in self.routers.values() ]

    # get server ids
    def server_names(self):
        return [ s.id()  for s in self.servers.values() ]

    # get client ids
    def client_names(self):
        return [ c.id()  for c in self.clients.values() ]

    # get routers
    def network_nodes(self):
        return list(self.routers.values())

    # get links as tuples with end points
    def edges(self):
        return [ (l.link1.src_node.id(), l.link2.src_node.id(), l.link1.propagation_delay) for l in self.links ]

    
    # get links
    def network_edges(self):
        return self.links

    # get neighbours of a router
    def neighbours(self, r):
        if isinstance(r, int):
            name = self.name_of(r)
            return self.routers[name].neighbours()
        elif isinstance(r, str):
            return self.routers[r].neighbours()
        else:
            # it's a router
            return self.routers[r.id()].neighbours()

    # degree at a router
    def degree(self, r):
        if isinstance(r, int):
            name = self.name_of(r)
            return self.routers[name].degree()
        elif isinstance(r, str):
            return self.routers[r].degree()
        else:
            return self.routers[r.id()].degree()

    # name of node a position N
    def name_of(self, n):
        return list(self.routers.keys())[n]

    # Links from a node - by name
    def links_from(self, val):
        if isinstance(val, int):
            name = self.name_of(val)
        else:
            name = val
            
        # filter over a list of BidirectionalLink
        return list(filter(lambda l: name in l.links(), self.links))
    
    # Links to a node - by name
    def links_to(self, val):
        if isinstance(val, int):
            name = self.name_of(val)
        else:
            name = val
            
        return list(filter(lambda l: name in l.links(), self.links))

    def install_host_rows(self):
        """Derive the hosts' latency rows from the routers' rows, then the
        diameter. Requests are one-way (client -> server) and every live table
        lookup is toward a server or from a server to a client, so router rows
        hold only servers and hosts need no forwarding tables."""
        # client rows: access router's row + the access link weight
        for client in self.clients.values():
            cname = client.id()
            neigh = client.neighbours()
            if not neigh:
                continue
            ar_name = neigh[0]
            ar_table = self.latency_table.get(ar_name, {})
            stub = self.weight(cname, ar_name)
            self.latency_table[cname] = {
                server: stub + delay for server, delay in ar_table.items()
            }

        # server rows: the utility machinery reads latency_table[server][client];
        # distances are symmetric, so mirror the client rows
        for server in self.servers.values():
            sname = server.id()
            row = {}
            for cname in self.clients:
                client_row = self.latency_table.get(cname, {})
                if sname in client_row:
                    row[cname] = client_row[sname]
            self.latency_table[sname] = row

        # the diameter is the largest delay in the tables: router -> server,
        # and client -> server including the client's access link
        self.network_diameter_val = self.network_diameter_fn()

    def calculate_forwarding_tables(self):
        """Calculate the forwarding tables for all routers, towards every
        server (src/Routing.py), then the hosts' latency rows and the
        diameter. Call it after every host is attached."""
        self.routing_counts = Routing.compute_tables(self)
        self.install_host_rows()

        # the diameter is the delay at which a replica is at its worst.
        # Set here, after an experiment's topology_setup() assignments, because
        # the diameter is the Network's to know, not an experiment's.
        MetricUtility.metric_scale['delay'] = self.network_diameter()

    # Network diameter
    #
    # It is the shortest distance between the two most distant nodes
    # in the network. In other words, once the shortest path length
    # from every node to all other nodes is calculated, the diameter
    # is the longest of all the calculated path lengths
    def network_diameter(self):
        return self.network_diameter_val

    # calculate the network diameter
    def network_diameter_fn(self):
        # Had to change the starting diameter from 1 to 0.0 to cope with link weights/latencies less than 1, previously the minimum the network diameter could be was 1.
        diameter = 0.0

        # visit the keys -- nodes names
        for node in self.latency_table:
            latency_from_node = self.latency_table[node]

            for dst in latency_from_node:
                distance = latency_from_node[dst]

                if distance > diameter:
                    diameter = distance
            
                # print(str(dst) + " -> " + str(distance) + " diameter: " + str(diameter))
        # Avoid division by zero when there are no paths
        if diameter == 0.0:
            return 1.0

        return diameter
        
    # Snapshot the optimal utility at the current time
    # and inject the data in the packet for later comparison.
    # vantage: the node whose latencies the utilities are computed from.
    # For decision-time quantities (SEL_UTIL_SEL, BEST_UTIL_SEL) this must be
    # the DECIDING router, so the ground truth shares the latency basis of the
    # FIB estimate (SEL_UTIL_EST). Falls back to the client if not given.
    def inject_snapshot_optimal_utility(self, packet, vantage=None):
        """Compute optimal replica utility now and store on packet."""
        vantage_node = vantage if vantage is not None else packet.src
        servers = [r for r in self.network_nodes() if isinstance(r, Server)]

        all_utilities = {}
        all_loads = {}
        all_latencies = {}

        vantage_latencies = self.latency_table.get(vantage_node, {})

        for server in servers:
            # skip servers with no valid path from the vantage node: with
            # valley-free routing some router/server pairs have no route, so
            # the ground truth is the best *reachable* server -- the same set
            # the router can choose from (see doc/TODO.md, Unreachable servers)
            if server.id() not in vantage_latencies:
                continue

            latency = vantage_latencies[server.id()]

            # the raw metrics of this replica, live -- the payload's placeholder
            # delay of 0 is replaced by the latency from the vantage node
            metrics = dict(server.calculate_payload(), delay=latency)

            # call the forwarding_utility on the raw metrics
            utility = Utility.eval_forwarding_utility(metrics)

            all_utilities[server.id()] = utility
            all_loads[server.id()] = metrics['load']
            all_latencies[server.id()] = latency

        # Find maximum utility and list of optimal candidates
        max_utility = max(all_utilities.values()) if all_utilities else -1
        best_servers = [sid for sid, util in all_utilities.items() if util == max_utility]

        # Resolve tie-breaker in favor of selected destination replica if it is in the optimal set
        selected_replica = getattr(packet, 'dst', None)
        if selected_replica in best_servers:
            best_id = selected_replica
        else:
            best_id = best_servers[0] if best_servers else None

        best_load = all_loads[best_id] if best_id else 0
        best_latency = all_latencies[best_id] if best_id else 0
        best_utility = max_utility

        packet.optimal_snapshot = {
            'time': self.env.now,
            'server_id': best_id,
            'load': best_load,
            'latency': best_latency,
            'utility': best_utility,
            'all_utilities': all_utilities,
            'all_loads': all_loads,
            'all_latencies': all_latencies
        }

    # Format one side of a gap line: {'time','server','load','latency','utility'}
    # notes: optional {'time','server','utility'} PDF notations, printed as
    # field(NOTATION): value
    @staticmethod
    def _gap_section(label, section, notes=None):
        if notes is None:
            return "{}: time: {:.3f} server: {} load: {} latency: {} utility: {}".format(
                label, section['time'], section['server'], section['load'],
                round(section['latency'], 3), round(section['utility'], 5))
        else:
            return "{}: time({}): {:.3f} server({}): {} load: {} latency: {} utility({}): {}".format(
                label, notes['time'], section['time'], notes['server'], section['server'],
                section['load'], round(section['latency'], 3),
                notes['utility'], round(section['utility'], 5))

    # Print one per-request metric line
    # gap = compared utility - selected utility (signed)
    # At Verbose.level >= 1 the PDF notation is shown before each value
    # (see GAP_NOTATIONS); the trailing "KEYWORD gap" is the same at all levels.
    def _log_request_gap(self, tag, arrival_server_id, packet, selected, compared,
                         status=None, compared_label="BEST", minload=None):
        gap = compared['utility'] - selected['utility']

        if status is not None:
            # client request not handled: BLOCKED
            keyword = status['msg']
        elif selected['server'] == compared['server']:
            keyword = "SAME"
        elif abs(gap) < UTILITY_EQUAL_EPSILON:
            keyword = "EQUAL"
        else:
            keyword = "DIFFERENT"

        notes = GAP_NOTATIONS.get(tag) if Verbose.level >= 1 else None

        if notes is None:
            tag_text = tag
            selected_notes = None
            compared_notes = None
        else:
            tag_text = "{} ({})".format(tag, notes['formula'])
            selected_notes = notes['selected']
            compared_notes = notes['compared']

        sections = [self._gap_section("SELECTED", selected, selected_notes),
                    self._gap_section(compared_label, compared, compared_notes)]
        if minload is not None:
            # BLOCKED lines carry an extra MINLOAD section (lowest-loaded
            # replica), placed before the trailing "KEYWORD gap" so
            # end-anchored parsers keep working
            minload_notes = notes.get('minload') if notes else None
            sections.append(self._gap_section("MINLOAD", minload, minload_notes))

        print("{:.3f}: {:5s} {} '{}' [{}.{}] {} {} {}".format(
            self.env.now, "Net ", tag_text, arrival_server_id, packet.src, packet.id,
            " ".join(sections), keyword, round(gap, 5)))

    # Report the per-request metrics.
    # This is called by individual Servers, when the request arrives (t_arr).
    #   OUTCOME_GAP   (B = BEST_UTIL_ARR - SEL_UTIL_ARR)   at Verbose level >= -1
    #   DECISION_GAP  (A = BEST_UTIL_SEL - SEL_UTIL_EST)   at Verbose level >= -1
    #   STALENESS_ERR (C = SEL_UTIL_SEL - SEL_UTIL_EST)    at Verbose level >= -1
    def best_replica_utility(self, requesting_server, packet, status = None):

        # level -2 (silent) skips the ground truth; -1 (metrics) and up need it
        if Verbose.level < -1:
            return

        client_name = packet.src
        requesting_server_id = requesting_server.id()
        now = self.env.now

        # filter out server nodes
        servers = [ r  for r in self.network_nodes() if isinstance(r, Server) ]

        # Ground truth at arrival time (t_arr):
        # - grab snapshot of load on all replicas.
        # - get latency from the client to all replicas (from the routing tables).
        # - calculate utility for each.
        utility_values = {}
        load_values = {}

        for server in servers:
            # skip servers with no valid path to the client
            # (see doc/TODO.md, Unreachable servers)
            if client_name not in self.latency_table.get(server.id(), {}):
                continue

            # get latency from client to server
            latency = self.latency_table[server.id()][client_name]

            # the raw metrics of this replica, live -- the payload's placeholder
            # delay of 0 is replaced by the latency to the client
            metrics = dict(server.calculate_payload(), delay=latency)

            # get load at server
            load = metrics['load']
            load_values[server.id()] = load

            # Now we map the actual latency / delay into a normalised_delay
            # which is a value between 0 and 1
            normalised_delay = self.get_normalised_delay(latency)

            # call the forwarding_utility on the raw metrics
            utility = Utility.eval_forwarding_utility(metrics)

            # save forwarding utility value for this server
            utility_values[server.id()] = utility

            if Verbose.level >= 3:
                print("best_replica_utility: '" + server.id() + "' load = " + str(load))
                print("best_replica_utility: '" + server.id() + "' delay = " + str(latency))
                print("best_replica_utility: '" + server.id() + "' normalised_delay = " + str(normalised_delay))
                print("best_replica_utility: '" + server.id() + "' forwarding_utility = " + str(utility))

        # summary
        if Verbose.level >= 3:
            print("best_replica_utility: '" + requesting_server_id + "' load = " + str(load_values))
            print("best_replica_utility: '" + requesting_server_id + "' latency = " + str(self.latency_table[requesting_server_id]))
            print("best_replica_utility: '" + requesting_server_id + "' utility from " + str(client_name) + " = " + str(utility_values))

        # best replica at arrival time, tie-break towards the arrival server
        # the arrival server was reached, so it must be reachable; an empty
        # set means the routing and latency tables disagree
        if not utility_values:
            raise RuntimeError("best_replica_utility: no reachable server in latency_table "
                               "for client {} (request arrived at {})".format(client_name, requesting_server_id))
        best_arrival_utility = max(utility_values.values())
        best_arrival_replicas = [sid for sid, u in utility_values.items() if u == best_arrival_utility]

        if requesting_server_id in best_arrival_replicas:
            best_arrival_id = requesting_server_id
        else:
            best_arrival_id = best_arrival_replicas[0]

        # a ground-truth section (at t_arr) for a given server
        def truth_section(server_id):
            return { 'time': now,
                     'server': server_id,
                     'load': load_values[server_id],
                     'latency': self.latency_table[server_id][client_name],
                     'utility': utility_values[server_id] }

        # On BLOCKED requests also report the lowest-loaded replica: load < 1.0
        # there means the request could have been served somewhere
        # (can_increase_load accepts while used_slots < slots, i.e. load < 1.0)
        minload = None
        if status is not None:
            minload = truth_section(min(load_values, key=load_values.get))

        # B: OUTCOME_GAP = BEST_UTIL_ARR - SEL_UTIL_ARR, both at t_arr
        self._log_request_gap("OUTCOME_GAP", requesting_server_id, packet,
                              truth_section(requesting_server_id),
                              truth_section(best_arrival_id),
                              status=status, minload=minload)

        # A and C need the decision-time data recorded by the deciding router
        if Verbose.level >= -1 and hasattr(packet, 'optimal_snapshot') and hasattr(packet, 'selection_estimate'):
            snapshot = packet.optimal_snapshot      # ground truth at t_sel
            estimate = packet.selection_estimate    # FIB belief, from the update at t_update
            selected_id = estimate['server_id']

            # the estimate's latency is the deciding router's RIB delay (the input
            # to SEL_UTIL_EST); the snapshot ground truth (SEL_UTIL_SEL,
            # BEST_UTIL_SEL) is computed from the same router's vantage, so A and
            # C compare like with like and only load staleness remains
            selected_estimate = { 'time': estimate['update_time'],
                                  'server': selected_id,
                                  'load': estimate['load'],
                                  'latency': estimate['latency'],
                                  'utility': estimate['utility'] }

            # A: DECISION_GAP = BEST_UTIL_SEL - SEL_UTIL_EST
            best_at_selection = { 'time': snapshot['time'],
                                  'server': snapshot['server_id'],
                                  'load': snapshot['load'],
                                  'latency': snapshot['latency'],
                                  'utility': snapshot['utility'] }
            self._log_request_gap("DECISION_GAP", requesting_server_id, packet,
                                  selected_estimate, best_at_selection)

            # C: STALENESS_ERR = SEL_UTIL_SEL - SEL_UTIL_EST
            # (same replica: stale belief vs fresh ground truth at t_sel)
            selected_at_selection = { 'time': snapshot['time'],
                                      'server': selected_id,
                                      'load': snapshot['all_loads'][selected_id],
                                      'latency': snapshot['all_latencies'][selected_id],
                                      'utility': snapshot['all_utilities'][selected_id] }
            self._log_request_gap("STALENESS_ERR", requesting_server_id, packet,
                                  selected_estimate, selected_at_selection,
                                  compared_label="ACTUAL")

    # Get replica capacity
    def get_replica_capacity(self, replica, entry):
        if replica in self.replica_capacity:
            return self.replica_capacity[replica][entry]
        else:
            return 1

    # Get total replica capacity
    def get_total_replica_capacity(self, entry):
        #print("Network: total_replica_capacity = " + str(self.replica_capacity_total))
        
        if entry in self.replica_capacity_total:
            return self.replica_capacity_total[entry]
        else:
            return 1

    # An update for replica_capacity
    def update_replica_capacity(self, replica, aDict):
        self.replica_capacity[replica] = aDict

        # calculate total
        self.replica_capacity_total = { 'load': 0, 'no_of_flows': 0, 'slots': 0,  'capacity': 0  }

        for key in self.replica_capacity:
            entry = self.replica_capacity[key]
            
            self.replica_capacity_total["load"] += entry["load"]
            self.replica_capacity_total["no_of_flows"] += entry["no_of_flows"]
            self.replica_capacity_total["slots"] += entry["slots"]
            self.replica_capacity_total["capacity"] += entry["capacity"]

        # load is total load: self.replica_capacity_total["load"]
        # divided by no of replicas:  len(self.replica_capacity)

        load = self.replica_capacity_total["load"] / len(self.replica_capacity)

        if Verbose.level >= 2:
            print ("{:.3f}: {:5s} REPLICA_CAPACITY_NETWORK 'load': {} 'no_of_flows': {}  'capacity': {}  'slots': {}  (Update from {})".format(self.env.now, "Net ", round(load, 6) ,  self.replica_capacity_total["no_of_flows"],  self.replica_capacity_total["capacity"],  self.replica_capacity_total["slots"], replica ))

    # Get the load_utility for a replica
    def get_normalised_load(self, replica):
        return self.replica_normalised_load[replica]
    

    # An update for load_utility
    def update_normalised_load(self, replica, load_val):
        self.replica_normalised_load[replica] = load_val
        
    # current average load_utility
    # average load_utilty = Network object collects all load_utility, returns average
    def average_normalised_load(self):
        count = 0
        total = 0
        
        for key in self.replica_normalised_load:

            load_val = self.replica_normalised_load[key]

            # print("Network: average_load_utility: load at " + str(key) + " = " + str(load_val))

            count += 1
            total += load_val


        avg =  total / count

        # print("Network: average_load_utility: average = " + str(avg))
        
        return avg
        

    # Get the normalised_delay for a delay
    # This is the delay / network_diameter
    def get_normalised_delay(self, delay):
        return delay / self.network_diameter()
    

    def print(self):
        print("{", end="\n")
        for router in self.routers:
            ports = self.routers[router].ports()
            portStr = [ str(port)  for port in ports.keys()]
            print("  '{}' : {},".format(self.routers[router].id(), portStr ), end="\n")
        print("}")

    # dump the graphviz file to a tmp directory
    def graphviz_to_file(self,filename, dir="tmp"):

        repo_root = None

        if dir.startswith("/"):
            # absolute path
            repo_root = dir
        else:
            # relative path
            repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        gv_file = os.path.join(repo_root, dir, filename)

        os.makedirs(os.path.dirname(gv_file), exist_ok=True)
    
        with open(gv_file, "w") as file_object:
            self.graphviz(file=file_object)
            
        
    # send graphviz output to file stream
    def graphviz(self, file=sys.stdout):
        print("Graph G {", file=file)
        print("  splines=polyline", file=file)
        # collect router names
        for router in self.routers:
            node = self.node(router)
            if isinstance(node, Client):
                print("\"" + router + "\" [shape=egg, style=\"filled\", fillcolor=\"pink\"", end="", file=file)
            elif isinstance(node, Server):
                print("\"" + router + "\" [shape=parallelogram, style=\"filled\", fillcolor=\"yellow\"", end="", file=file)
            else:
                print("\"" + router + "\" [shape=circle", end="", file=file)

            print("];", file=file)


        # collect router names
        for router in self.routers:
            node = self.node(router)

            for neighbour in node.neighbours():
                if router < neighbour:
                    print("\"" + router + "\" -- \"" + neighbour + "\""  + " [label=\"" + str(round(node.weight_edge(neighbour), 3)) + "\"];" , file=file)


        print("}", file=file)

        

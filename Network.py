from Graph import Graph
from Router import Router
from Link import BidirectionalLink
from Host import Host
from Server import Server
from Client import Client
from Verbose import Verbose
from Utility import Utility
from collections import OrderedDict
from gml import read_gml, write_gml
import sys

class Network:
    def __init__(self, env = None):
        """ Create a network
        """
        self.routers = OrderedDict()         # a dictionary of routers
        self.links = []           # a list of links
        self.env = env            # an Environment
        self.latency_table = {}
        
    @classmethod
    def from_graph(cls, graph, env):
        """ Create a network from a Graph representation of an adjacency list
        """

        # create the Network
        # add a handle to the simpy Environment
        network = Network(env)
        
        # first we create the list of Routers
        for i in range(len(graph)):
            # convert number to name
            name = graph.name_of(i)

            # print("name_of " + str(i) + " = " + name)
            
            # create a Router
            router = Router(name, network)
            # now add it to the routers
            network.routers[name] = router

        # now add the links
        for i in range(len(graph)):
            # convert number to name
            name = graph.name_of(i)
            # get the adjacency list
            nodes = graph.adjacency(i)

            # try all nodes at 'name'
            #print("from_graph: nodes at " + name + " = " + str(nodes))

            for node in nodes:
                # skip through [ ('b', 1), ('c', 4)]
                (node_name, weight) = node
                
                current = network.routers[name]
                neighbour_obj = network.routers[node_name]

                # add the neighbours for current to neighbour_obj
                # and neighbour_obj to current
                (status1, link1) = current.add_neighbour(neighbour_obj, weight)
                (status2, link2) = neighbour_obj.add_neighbour(current, weight)

                # create the BidirectionalLink
                if status1 == "create" or status2 == "create":
                    network.links.append(BidirectionalLink(link1, link2))

        return network
            
    # Build a graph from a GML file
    @classmethod
    def from_gml_file(cls, gml_file, env):
        """ Add some neighbours from a GML file.
        """
        graph = read_gml(gml_file)

        return Network.from_graph(graph, env)
    
    def start(self, until=1000):
        """Start the Network processing.
        Calls back to the simpy env to start elements"""

        # start each of the routers
        for router in self.routers.values():
            router.start()
            
        # start the simulation run
        self.env.run(until)

    # contains router
    # pass in name or Router
    def contains_router(self, r):
        return self.contains_node(r)

    # pass in name or Router
    def contains_node(self, r):
        if type(r) == int:
            # it's an int -- check size
            return val < len(self.routers)

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
    def add_client(self, host, router, weight=1):
        """Add an edge from a Client to a Router.
           Pass in a name or a Client, and a Router.
        """
        if isinstance(host, Client):
            # now add it to the routers and add a link
            self.add_edge(host, router, weight)

        elif isinstance(host, str):
            # got a name
            # create Client and pass in Network
            self.add_edge(Client(host, self), router, weight)
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

        elif isinstance(host, str):
            # got a name
            # create Server and pass in Network
            self.add_edge(Server(host, self), router, weight)
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
            print("add_edge int " + r1.id() + " " + str(r1))
        else:
            if not self.contains_router(n1):
                # new node
                if type(n1) == str:
                    # just got a name
                    # make a Router
                    r1 = Router(n1, self)
                    self.routers[n1] = r1

                    if Verbose.level >= 2:
                        print(type(r1).__name__ + " add " + n1)
                else:
                    r1 = n1
                    self.routers[n1.id()] = r1

                    if Verbose.level >= 2:
                        print(type(r1).__name__ + " add " + n1.id())
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
            print("add_edge int " + r2.id() + " " + str(r2))
        else:
            if not self.contains_router(n2):
                # new node
                if type(n2) == str:
                    # just got a name
                    # make a Router
                    r2 = Router(n2, self)
                    self.routers[n2] = r2

                    if Verbose.level >= 2:
                        print(type(r2).__name__ + " add " + n2)
                else:
                    r2 = n2
                    self.routers[n2.id()] = r2

                    if Verbose.level >= 2:
                        print(type(r2).__name__ + " add " + n2.id())
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

    # calculate the forwarding table for every node
    def calculate_forwarding_tables(self):
        """Calculate the forwarding tables for all nodes"""
        for node in self.nodes():            
            # calculate the forwarding table for node
            table = self.forwarding_table(node)
            # tell the node its unicast_forwarding_table
            self[node].set_unicast_forwarding_table(table)


    # calculate a forwarding table for a router r
    # each entry is (destination, next_hop, weight)
    # and the latencies from 'r' to other nodes
    def forwarding_table(self, r):
        """Calculate the forwarding table for router r"""
        router = None

        # work with router name
        if isinstance(r, int):
            router = self.name_of(r)
        elif isinstance(r, str):
            router = r
        else:
            router = r.id()

        # calculate Dijkstra's algorithm for the router
        # this returns a dict of 3 values
        # the 'source' node, the 'shortest_path' to other nodes,
        # the 'previous_nodes' for other nodes. 
        dijkstra_r = Graph.dijkstra_algorithm(self, router)

        # we combine shortest_path and previous_nodes to
        # create the routing table entries
        table = self.dijkstra_to_routing(dijkstra_r)

        # while in here we use the same dijkstra_r values to
        # combine the shortest_path and previous_nodes to
        # convert shortest_path and previous_nodes dicts into 
        # a list of path latencies
        latency_table_r = self.dijkstra_to_latency(dijkstra_r)
        self.latency_table.update(latency_table_r)

        if Verbose.level >= 2:
            print("latency_table: " + router + " = " + str(latency_table_r[router]))

        return table

    # convert shortest_path and previous_nodes dicts into 
    # a list of  entries like (destination, next_hop, weight)
    def dijkstra_to_routing(self, dijkstra_tuple):
        router = dijkstra_tuple['source']
        shortest_path = dijkstra_tuple['shortest_path']
        previous_nodes = dijkstra_tuple['previous_nodes']

        return self.dijkstra_to_routing_fn(router, shortest_path, previous_nodes)
        
    # convert shortest_path and previous_nodes dicts into 
    # a list of  entries like (destination, next_hop, weight)
    def dijkstra_to_routing_fn(self, router, shortest_path, previous_nodes):
        """Convert dijkstra_algorithm dict into a routing table"""
        
        # example inputs are:
        # 'shortest_path': {'a': 3, 'b': 2, 'c': 5, 'd': 0, 'e': 4, 'f': 6, 's1': 4, 's2': 4, 's3': 4, 's4': 4, 's5': 4, 'c1': 5, 'c2': 5, 'c3': 5, 'c4': 5, 'c5': 5},
        # 'previous_nodes': {'b': 'd', 'c': 'd', 'e': 'b', 'a': 'b', 's1': 'a', 's2': 'a', 's3': 'a', 's4': 'a', 's5': 'a', 'c1': 'e', 'c2': 'e', 'c3': 'e', 'c4': 'e', 'c5': 'e', 'f': 'c'}

        table = []
        
        # visit the shortest_path dict and work out which is the
        # directly connected node to send to
        for node, weight in shortest_path.items():
            if node == router:
                # found myself - nothing to do
                pass
            else:
                # now find the directly connected node
                connected = None
                lookup = node

                while True:
                    # find lookup in previous_nodes
                    connected = previous_nodes[lookup]

                    if connected == router:
                        # next is directly connected to router
                        break
                    else:
                        lookup = connected

                tuple = (node, lookup, weight) 

                table.append(tuple)

        return table

    # convert shortest_path and previous_nodes dicts into 
    # a list of  path latencies
    def dijkstra_to_latency(self, dijkstra_tuple):
        router = dijkstra_tuple['source']
        shortest_path = dijkstra_tuple['shortest_path']
        previous_nodes = dijkstra_tuple['previous_nodes']

        return self.dijkstra_to_latency_fn(router, shortest_path, previous_nodes)
        
    # convert shortest_path and previous_nodes dicts into 
    # a list of  path latencies
    def dijkstra_to_latency_fn(self, router, shortest_path, previous_nodes):
        """Convert dijkstra_algorithm dict into latency along the path"""
        
        # example inputs are:
        # {'source': 'a', 'shortest_path': {'a': 0, 'b': 1, 'c': 1, 'd': 2, 'e': 2}, 'previous_nodes': {'b': 'a', 'c': 'a', 'd': 'b', 'e': 'b'}}
        
        latency_table = {}
        
        # set up a dict for this router
        latency_table[router] = {}

        
        # visit the shortest_path dict and work out the latency along the path
        # the weights in shortest_path are hop count, and so not used here
        for node in shortest_path.keys():
            if node == router:
                # found myself - nothing to do
                pass
            else:
                # now find the path
                connected = None
                lookup = node
                path_latency = 0

                # skip through all nodes until we reach router
                while True:
                    # find lookup in previous_nodes
                    connected = previous_nodes[lookup]

                    # get the link weight of connected to lookup
                    link_weight = self.weight(connected, lookup)

                    path_latency += link_weight

                    if Verbose.level >= 5:
                        print("dijkstra_to_latency_fn: link_weight: " + connected + " -> " + lookup + " = " + str(link_weight))

                    if connected == router:
                        # next we have reached router
                        # so the path is complete
                        break
                    else:
                        lookup = connected

                if Verbose.level >= 4:
                    print("dijkstra_to_latency_fn: latency " + router + " --> " + node + " = " + str(path_latency))
                    
                latency_table[router][node] = path_latency

        return latency_table


    # Get the latency along a path from src to dst
    # Relies on the unicast_forwarding_table in each node
    def path_latency(self, s, d):
        src = None
        dst = None
        
        if isinstance(s, int):
            src = self.name_of(s)
        elif isinstance(s, str):
            src = s
        else:
            src = s.id()
        
        if isinstance(d, int):
            dst = self.name_of(d)
        elif isinstance(d, str):
            dst = d
        else:
            dst = d.id()
        

        return self.latency_table[dst][src]   # self[dst].distance_to(src)
        
    # Get the utility for best server / replica
    def best_replica_utility(self, requesting_server, packet):

        client_name = packet.src
        requesting_server_id = requesting_server.id()

        # filter out server nodes
        servers = [ r  for r in self.network_nodes() if isinstance(r, Server) ]


        # Utility of best replica:
        # - grab snapshot of load on all replicas.
        # - get latency from the client to all replicas (from dijkstra).
        # - calculate utility for each.
        # - Choose minimum.
        utility_values = {}
        load_values = {}


        for server in servers:
            # get load at server
            load = server.calculate_load()
            load_values[server.id()] = load

            # get latency from client to server
            latency = self.latency_table[server.id()][client_name]

            # calculate utility
            # we use
            # alpha --> same alpha
            # load --> load at chosen replica
            # delay --> length of path (sum of weigths) from client to chosen replica

            utility = Utility.forwarding_utility_fn(Utility.alpha, load, latency)

            utility_values[server.id()] = utility


        print("best_replica_utility: '" + requesting_server_id + "' load = " + str(load_values))
        print("best_replica_utility: '" + requesting_server_id + "' latency = " + str(self.latency_table[requesting_server_id]))
        print("best_replica_utility: '" + requesting_server_id + "' utility from " + str(client_name) + " = " + str(utility_values))


        # now we sort them by value, so the minimum value is the first item
        ordered = {k: v for k, v in sorted(utility_values.items(), key=lambda item: item[1])}
        
        print("best_replica_utility: '" + requesting_server_id + "' ordered_utility = " + str(ordered))

        # and select all the keys which match the minimum value
        minimum_pair = list(ordered.items())[0]

        print("best_replica_utility: '" + requesting_server_id + "' minimum_pair = " + str(minimum_pair))
        
        minimum_replicas = [k for k, v in ordered.items() if v == minimum_pair[1]]
        
        print("best_replica_utility: '" + requesting_server_id + "' minimum_replicas = " + str(minimum_replicas))

        # need to keep:
        # selected server load, selected server latency, selected server utility
        # for logging
        selected_server_load = 0
        selected_server_latency = 0
        selected_server_utility = 0

        best_server_id = None
        best_server_load = 0
        best_server_latency = 0
        best_server_utility = 0
        
        selected_server_load = load_values[requesting_server_id]
        selected_server_latency = self.latency_table[requesting_server_id][client_name]
        selected_server_utility = utility_values[requesting_server_id]
                
        if requesting_server.id() in minimum_replicas:
            # requesting_server has minimum load
            best_server_id = requesting_server.id()
        else:
            # just pick one
            best_server_id = minimum_replicas[0]

        best_server_load = load_values[best_server_id]
        best_server_latency = self.latency_table[best_server_id][client_name]
        best_server_utility = utility_values[best_server_id]

        # Log utility of true best replica and utility of selected replica: timestamp, selected server id, client id, client request id,  selected server id,  selected server load, selected server latency, selected server utility, best server id, best server load, best server latency
        print("{:.3f}: BEST_REPLICA_UTILITY '{}' pkt: {}.{} selected: {} load({}) latency({}) utility({}) best: {} load({}) latency({}) utility({}) {}".format(self.env.now, requesting_server.id(),  packet.src, packet.id, requesting_server.id(), selected_server_load, selected_server_latency, selected_server_utility,  best_server_id, best_server_load, best_server_latency, best_server_utility, "SAME" if requesting_server_id == best_server_id else "DIFFERENT"))

        
    

    def print(self):
        print("{", end="\n")
        for router in self.routers:
            ports = self.routers[router].ports()
            portStr = [ str(port)  for port in ports.keys()]
            print("  '{}' : {},".format(self.routers[router].id(), portStr ), end="\n")
        print("}")

    def graphviz(self, file=sys.stdout):
        print("Graph G {", file=file)
        print("  splines=polyline", file=file)
        # collect router names
        for router in self.routers:
            node = self.node(router)
            if isinstance(node, Client):
                print(router + " [shape=egg, style=\"filled\", fillcolor=\"pink\"", end="", file=file)
            elif isinstance(node, Server):
                print(router + " [shape=parallelogram, style=\"filled\", fillcolor=\"yellow\"", end="", file=file)
            else:
                print(router + " [shape=circle, fixedsize=true, width=1", end="", file=file)

            print("];", file=file)


        # collect router names
        for router in self.routers:
            node = self.node(router)
            for neighbour in node.neighbours():
                if router < neighbour:
                    print(router + " -- " + neighbour + ";", file=file)


        print("}", file=file)

        

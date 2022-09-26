from AdjList import Graph
from Router import Router
from Link import BidirectionalLink
from Host import Host
from Server import Server
from Client import Client
from Verbose import Verbose

# Convert a Graph of label and weights into a Network of Routers and Links

class Network:
    def __init__(self, env = None):
        """ Create a network
        """
        self.routers = {}         # a dictionary of routers
        self.links = []           # a list of links
        self.env = env            # an Environment
        
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
            name = graph.name(i)
            # create a Router
            router = Router(name, env)
            # now add it to the routers
            network.routers[name] = router

        # now add the links
        for i in range(len(graph)):
            # convert number to name
            name = graph.name(i)
            # get the adjacency list
            nodes = graph[i]

            # try all nodes at 'name'

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
        if isinstance(r, str):
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

    # contains link
    def contains_link(self, r1, r2):
        if (r.id() in self.routers):
            return True
        else:
            return False

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
            self.add_edge(Client(host), router, weight)
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
            self.add_edge(Server(host), router, weight)
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
        if not self.contains_router(n1):
            # new node
            if type(n1) == str:
                # just got a name
                # make a Router
                r1 = Router(n1, self.env)
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
        r1.set_env(self.env)

            
        # does n2 exist
        r2 = None
        if not self.contains_router(n2):
            # new node
            if type(n2) == str:
                # just got a name
                # make a Router
                r2 = Router(n2, self.env)
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
        r2.set_env(self.env)

        # add the neighbours for the 2 nodes
        (status1, link1) = r2.add_neighbour(r1, weight)
        (status2, link2) = r1.add_neighbour(r2, weight)

        # create the BidirectionalLink
        if status1 == "create" or status2 == "create":
            edge = BidirectionalLink(link1, link2)
            self.links.append(edge)
            return edge
        else:
            return None

    # get a specific node
    def node(self, r):
        """Get the node represented by val.
           Can be a Router or a name"""
        
        if isinstance(r, str):
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
        return self.routers[val]

    # The size of the network
    def __len__(self):
        return len(self.routers)

    # get routers
    def nodes(self):
        return [ r.id()  for r in self.routers.values() ]

    def network_nodes(self):
        return list(self.routers.values())

    # get links
    def edges(self):
        return [ (l.link1.src_node.id(), l.link2.src_node.id(), l.link1.propagation_delay) for l in self.links ]

    
    def network_edges(self):
        return self.links

    # get neighbours of a router
    def neighbours(self, r):
        if isinstance(r, str):
            return self.routers[r].neighbours()
        else:
            # it's a router
            return self.routers[r.id()].neighbours()

    # degree at a router
    def degree(self, r):
        if isinstance(r, str):
            return self.routers[r].degree()
        else:
            return self.routers[r.id()].degree()

    # Links from a node - by name
    def links_from(self, val):
        # filter over a list of BidirectionalLink
        return list(filter(lambda l: val in l.links(), self.links))
    
    # Links to a node - by name
    def links_to(self, val):
        return list(filter(lambda l: val in l.links(), self.links))

    # calculate the forwarding table for every node
    def calculate_forwarding_tables(self):
        """Calculate the forwarding tables for all nodes"""
        for node in self.nodes():            
            table = self.forwarding_table(node)
            self[node].set_unicast_forwarding_table(table)

    # calculate a forwarding table for a router r
    # each entry is (destination, next_hop, weight)
    def forwarding_table(self, r):
        """Calculate the forwarding table for router r"""
        router = None

        if isinstance(r, str):
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
        table = self.dijkstra_to_routing(router, dijkstra_r['shortest_path'], dijkstra_r['previous_nodes'])
        return table

    # convert shortest_path and previous_nodes dicts into 
    # a list of  entries like (destination, next_hop, weight)
    def dijkstra_to_routing(self, router, shortest_path, previous_nodes):
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
        
    
    def print(self):
        print("{", end="\n")
        for router in self.routers:
            ports = self.routers[router].ports()
            portStr = [ str(port)  for port in ports.keys()]
            print("  '{}' : {},".format(self.routers[router].id(), portStr ), end="\n")
        print("}")

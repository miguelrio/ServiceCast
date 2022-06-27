from AdjList import Graph
from Router import Router
from Link import BidirectionalLink

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
    def contains_router(self, r):
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
        # now add it to the routers and add a link
        self.add_edge(host, router, weight)

    # add an edge
    # add new nodes if needed
    # return the new edge
    # or None, if nothing created
    def add_edge(self,n1, n2, weight=1):
        """Add an edge from one Router to another Router.
           Pass in 2 Routers.
        """
        # does n1 exist
        r1 = None
        if not self.contains_router(n1):
            self.routers[n1.id()] = n1
            r1 = n1
            print("add " + n1.id())
        else:
            r1 = self.routers[n1.id()]
            
        # does n2 exist
        r2 = None
        if not self.contains_router(n2):
            self.routers[n2.id()] = n2
            r2 = n2
            print("add " + n2.id())
        else:
            r2 = self.routers[n2.id()]


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
        return list(self.routers.values())

    # get links
    def edges(self):
        return self.links

    # Links from a node - by name
    def links_from(self, val):
        # filter over a list of BidirectionalLink
        return list(filter(lambda l: val in l.links(), self.links))
    
    # Links to a node - by name
    def links_to(self, val):
        return list(filter(lambda l: val in l.links(), self.links))
    
    def print(self):
        print("{ ", end="")
        for router in self.routers:
            ports = self.routers[router].ports()
            portStr = [ str(port)  for port in ports.keys()]
            print("'{}' : {},".format(self.routers[router].id(), portStr ), end="\n")
        print("}")

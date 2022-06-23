from AdjList import Graph
from Router import Router

# Convert a Graph of label and weights into a Network of Routers and Links

class Network:
    def __init__(self):
        """ Create a network
        """
        self.routers = {}         # a dictionary of routers
        self.links = []           # a list of links
        
    @classmethod
    def from_graph(cls, env, graph):
        """ Create a network from a Graph representation of an adjacency list
        """
        network = Network()
        # add a handle to the simpy Environment
        network.env = env
        
        # first we create the list of Routers
        for i in range(len(graph)):
            # convert number to name
            name = graph.name(i)
            # create a Router
            router = Router(env, name)
            # now add it to the routers
            network.routers[name] = router

        # now add the links
        for i in range(len(graph)):
            # convert number to name
            name = graph.name(i)
            # get the adjacency list
            nodes = graph[i]
            # convert [ ('b', 1), ('c', 4)], into {'b': (routerB,1), 'c':  (routerC,4)},
            neighbours = {value[0] : (network.routers[value[0]], value[1]) for value in nodes}

            links = network.routers[name].add_neighbours(neighbours)

            network.links.extend(links)

        return network
            
    def start(self, until=1000):
        """Start the Network processing.
        Calls back to the simpy env to start elements"""

        # start each of the routers
        for router in self.routers.values():
            router.start()
            
        # start the simulation run
        self.env.run(until)

    # add a host to the network and link it to a specified router
    def linkhost(self, host, router):
        # now add it to the routers
        self.routers[host.id()] = host
        # add link
        link = host.set_neighbour(router)



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
        return list(filter(lambda l: l.src_node.id() == val, self.links))
    
    # Links to a node - by name
    def links_to(self, val):
        return list(filter(lambda l: l.dst_node.id() == val, self.links))
    
    def print(self):
        print("{ ", end="")
        for router in self.routers:
            ports = self.routers[router].ports()
            portStr = [ str(port)  for port in ports.keys()]
            print("'{}' : {},".format(self.routers[router].id(), portStr ), end="\n")
        print("}")

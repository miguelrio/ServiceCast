from AdjList import Graph
from Router import Router

# Convert a Graph of label and weights into a Network of Routers and Links

class Network:
    def __init__(self, env, graph):
        """ Create a network from a Graph representation of an adjacency list
        """
        self.routers = {}         # a dictionary of routers
        self.links = []           # a list of links
        self.env = env
        
        # first we create the list of Routers
        for i in range(len(graph)):
            # convert number to name
            name = graph.name(i)
            # create a Router
            router = Router(env, name)
            # now add it to the routers
            self.routers[name] = router

        # now add the links
        for i in range(len(graph)):
            # convert number to name
            name = graph.name(i)
            # get the adjacency list
            nodes = graph[i]
            # convert [ ('b', 1), ('c', 4)], into {'b': (routerB,1), 'c':  (routerC,4)},
            neighbours = {value[0] : (self.routers[value[0]], value[1]) for value in nodes}

            links = self.routers[name].add_neighbours(neighbours)

            self.links.extend(links)
            
    def start(self, until=1000):
        """Start the Network processing.
        Calls back to the simpy env to start elements"""

        # start each of the routers
        for router in self.routers.values():
            router.start()
            
        # start the simulation run
        self.env.run(until)

        
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
        return list(filter(lambda l: l.src_node.routerid == val, self.links))
    
    # Links to a node - by name
    def links_to(self, val):
        return list(filter(lambda l: l.dst_node.routerid == val, self.links))
    
    def print(self):
        print("{ ", end="")
        for router in self.routers:
            ports = self.routers[router].outgoing_ports
            portStr = [ str(port)  for port in ports.keys()]
            print("'{}' : {},".format(self.routers[router].routerid, portStr ), end="\n")
        print("}")

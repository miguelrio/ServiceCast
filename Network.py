from AdjList import Graph
from Router import Router

# Convert a Graph of label and weights into a Network of Routers and Links

class Network:
    def __init__(self, env, graph):
        """ Create a network from a Graph representation of an adjacency list
        """
        self.routers = {}         # a dictionary of routers
        
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

            self.routers[name].add_neighbours(neighbours)
            
    # index into network by node name
    # returns a router
    def __getitem__(self, val):
        """Get network[val]"""
        return self.routers[val]

    # The size of the network
    def __len__(self):
        return len(self.routers)
    
    
    def print(self):
        print("{ ", end="")
        for router in self.routers:
            print("'{}' : {},".format(self.routers[router].routerid, self.routers[router].outgoing_ports), end="\n")
        print("}")

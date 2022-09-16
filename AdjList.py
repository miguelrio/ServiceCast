# Adjacency List representation in Python
# Ideas from https://www.programiz.com/dsa/graph-adjacency-list

# Adjacency nodes are linked together
class AdjNode:
    def __init__(self, value, weight=1):
        self.vertex = value     # the value of this node
        self.next = None        # a link to the next node
        self.weight = weight    # a weight

    def as_list(self):
        node = self
        result = []
        
        while node:
            result.append((node.vertex, node.weight))
            node = node.next

        return result
        

    def __str__(self):
        return "AdjNode value: " + str(self.vertex) + " weight: " + str(self.weight) + " next: (" + "None" if self.next == None else str(self.next.vertex) + ")"



class Graph:
    def __init__(self, num):
        self.V = num                    # the size of the graph
        self.graph = [None] * self.V    # an array of AdjNode lists
        self.labels = []                 # an array of names

    # index into graph by index or node name
    # returns a list of adjacency info
    def __getitem__(self, val):
        if type(val) == int:
            node = self.graph[val]
            return [(self.name(value[0]), value[1]) for value in node.as_list()]
        else:
            index = self.labels.index(val)
            node = self.graph[index]
            return [(self.name(value[0]), value[1]) for value in node.as_list()]

    # The size of the graph
    def __len__(self):
        return self.V
    
    # Build a graph from a dictionary
    @classmethod
    def from_dict(cls, neighbours):
        """ Add some neighbours from a dictionary with label : { (router, propogation_delay) ...}
        """
        # Create graph
        graph = cls(len(neighbours))

        # Skip through all the neighbours
        # and create a list of node names
        for node in neighbours.keys():
            # and create entries in labels
            graph.labels.append(node)
            
        # print ("labels: {}\n".format(graph.labels))
        
        # Skip through all the neighbours again
        for node in neighbours.keys():

            # get index of node
            index = graph.labels.index(node)
            # print ("index {} = {}\n".format( node, index))
            
            # get the next links  {'b', 'c'}
            nextLinks = neighbours[node]
            # print ("nextLinks {} \n".format(nextLinks))

            for next in nextLinks:
                # a next might be: 'a'  or ('a', 10)
                name = ""
                weight = 1

                if type(next) == str:
                    name = next
                elif type(next) is tuple:
                    # it's a tuple
                    name = next[0]
                    weight = next[1]
                else:
                    # not defined yet
                    pass


                # get index of next
                nextIndex = graph.labels.index(name)
                # print ("nextIndex {} = {}\n".format(next, nextIndex))

                # add the edge, if it doesn't exist
                if graph.contains_edge(index, nextIndex):
                    # print ("exists {} = {}\n".format(index, nextIndex))
                    pass
                else:
                    graph.add_edge(index, nextIndex, weight)
                    # print ("add_edge {} = {}\n".format(index, nextIndex))

                # print ("graph: {} {}\n".format(len(graph.graph), graph.graph))

        return graph
        
    # Add edges
    def add_edge(self, s, d, weight=1):
        node = AdjNode(d,weight)
        node.next = self.graph[s]
        self.graph[s] = node

        node = AdjNode(s,weight)
        node.next = self.graph[d]
        self.graph[d] = node

    # Contains an edge
    def contains_edge(self, s, d):
        # s can be int or value
        if type(s) == int:
            pass
        else:
            s = self.labels.index(s)
        
        # d can be int or value
        if type(d) == int:
            pass
        else:
            d = self.labels.index(d)
        
        # get head of the adjacency
        node = self.graph[s]

        # Skip through all the nodes
        while node != None:
            if node.vertex == d:
                return True
            else:
                node = node.next
        return False
        
    # Get an edge
    def edge(self, s, d):
        """Returns a 3-tuple (src, dst, weight)  or None"""
        # s can be int or value
        if type(s) == int:
            pass
        else:
            s = self.labels.index(s)
        
        # d can be int or value
        if type(d) == int:
            pass
        else:
            d = self.labels.index(d)
        
        # get head of the adjacency
        node = self.node(s)
        head = node

        # Skip through all the nodes
        while node != None:
            if node.vertex == d:
                return (self.name(s), self.name(node.vertex), node.weight)
            else:
                node = node.next
        return None

    # get a list of edges
    def edges(self):
        nodes = self.labels

        edges = []

        for label in nodes:
            # get head of the adjacency
            node = self.node(label)


            # Skip through all the nodes
            while True:
                weight = node.weight
                dst = self.name(node.vertex)

                if  (label, dst, weight) in edges:
                    pass
                elif (dst, label, weight) in edges:
                    pass
                else:
                    edges.append( (label, dst, weight) )

                # end
                if (node.next == None):
                    break
                else:
                    node = node.next            

        return edges
        

    # get a list of the node names
    def nodes(self):
        return self.labels

    # get a specific node
    def node(self, val):
        """Get the node represented by val.
           Can be an int or a name"""
        if type(val) == int:
            node = self.graph[val]
            return node
        else:
            index = self.labels.index(val)
            node = self.graph[index]
            return node

    # Label for node
    def name(self, i):
        if len(self.labels) > i:
            # we have a list of labels
            return self.labels[i]
        else:
            # no labels, so use number
            return str(i)

    
    # Print the graph
    def print_agraph(self):
        for i in range(self.V):
            print(str(self.name(i)) + ":", end="")
            node = self.graph[i]
            while node:
                print("\t-> {}".format(self.name(node.vertex)), end="")
                if node.weight > 1:
                    print(" ({})".format(node.weight), end="")
                if node.next != None:
                    print("")
                node = node.next
                
            print(".")


    def print(self):
        print("{", end="\n")
        for label in self.labels:
            print("  '{}' : {},".format(label, self[label]), end="\n")
        print("}")


    def neighbours(self, s):
        "Returns the neighbors of a node s."
        
        connections = []

        # get head of the adjacency
        node = self.node(s)

        # Skip through all the nodes
        while node != None:
            connections.append(self.name(node.vertex))
            node = node.next

        return connections
    
    def weight(self, node1, node2):
        "Returns the weight of an edge between two nodes."
        edge = self.edge(node1, node2)

        return edge[2]

    # simple Dijkstra algorithm - adapted
    # from https://www.udacity.com/blog/2021/10/implementing-dijkstras-algorithm-in-python.html
    
    @classmethod
    def dijkstra_algorithm(cls, graph, start_node):
        """Dijkstra algorithm which returns 3 values:
        the 'source' node, the 'shortest_path' to other nodes,
        the 'previous_nodes' for other nodes. An example:
        {'source': 'a', 'shortest_path': {'a': 0, 'b': 1, 'c': 4,
        'd': 3, 'e': 3}, 'previous_nodes': {'b': 'a', 'c': 'a', 'd': 'b', 'e': 'b'}}"""
        
        unvisited_nodes = list(graph.nodes())

        # We'll use this dict to save the cost of visiting each node and update it as we move along the graph   
        shortest_path = {}

        # We'll use this dict to save the shortest known path to a node found so far
        previous_nodes = {}

        # We'll use max_value to initialize the "infinity" value of the unvisited nodes   
        max_value = float('inf')

        for node in unvisited_nodes:
            shortest_path[node] = max_value
            
        # However, we initialize the starting node's value with 0   
        shortest_path[start_node] = 0

        # The algorithm executes until we visit all nodes
        while unvisited_nodes:
            # The code block below finds the node with the lowest score
            current_min_node = None
            for node in unvisited_nodes: # Iterate over the nodes
                if current_min_node == None:
                    current_min_node = node
                elif shortest_path[node] < shortest_path[current_min_node]:
                    current_min_node = node

            # The code block below retrieves the current node's neighbors and updates their distances
            neighbors = graph.neighbours(current_min_node)
            for neighbor in neighbors:
                tentative_value = shortest_path[current_min_node] + graph.weight(current_min_node, neighbor)
                if tentative_value < shortest_path[neighbor]:
                    shortest_path[neighbor] = tentative_value
                    # We also update the best path to the current node
                    previous_nodes[neighbor] = current_min_node

            # After visiting its neighbors, we mark the node as "visited"
            unvisited_nodes.remove(current_min_node)

        return { 'source': start_node, 'shortest_path': shortest_path, 'previous_nodes': previous_nodes }

import os

from Verbose import Verbose

# A Graph
class Graph:
    # Default propagation delay for links in the network (in seconds).
    # This will usually be overridden by setting a value for it in an experiment file.
    # This allows us to set the link delays from links in the GML file.
    default_propagation_delay = 1

    """A representation of a Graph"""
    def __init__(self, num=0):
        self.V = num                    # the size of the graph
        self.graph = [None] * self.V    # an array of AdjNode lists
        self.labels = []                # an array of names
        self.meta_data = {}             # a dict of meta data
        self.node_meta_data = {}        # a dict of meta data for each node

        self._index = {}                # name -> position in labels
        self._index_len = 0             # len(labels) when _index was built

    # ------------------------------------------------------------------
    # Label index.
    #
    # The old code called self.labels.index(name) everywhere, which is a
    # linear scan.  These methods keep a dict alongside labels so the same
    # lookup is O(1).  The index is rebuilt lazily if anything appends to
    # self.labels without going through here (e.g. a direct-construction
    # loader), so it can never go stale.
    # ------------------------------------------------------------------

    def _rebuild_index(self):
        index = {}
        for i, label in enumerate(self.labels):
            # first occurrence wins, matching list.index()
            if label not in index:
                index[label] = i
        self._index = index
        self._index_len = len(self.labels)

    def index_of(self, val):
        """Position of val in labels.  val may already be an int."""
        if type(val) == int:
            return val

        if self._index_len != len(self.labels):
            self._rebuild_index()

        try:
            return self._index[val]
        except KeyError:
            # match the ValueError that labels.index() used to raise
            raise ValueError("{!r} is not in graph".format(val))

    # register a new label, keeping the index in step
    def _add_label(self, name):
        if self._index_len != len(self.labels):
            self._rebuild_index()

        if name not in self._index:
            self._index[name] = len(self.labels)

        self.labels.append(name)
        self._index_len = len(self.labels)

    # index into graph by index or node name
    # returns a name
    def __getitem__(self, val):
        if type(val) == int:
            return self.labels[val]
        else:
            return val

    # contains a val
    def __contains__(self, val):
        return self.contains_node(val)

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
            graph._add_label(node)
            
        # print ("labels: {}\n".format(graph.labels))
        
        # Skip through all the neighbours again
        for node in neighbours.keys():

            # get index of node
            index = graph.index_of(node)
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
                nextIndex = graph.index_of(name)
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

    # Build a graph from a GML file
    @classmethod
    def from_gml_file(cls, gml_file):
        """ Add some neighbours from a GML file.
        """
        from Gml import read_gml
        graph = read_gml(gml_file)

        return graph
    
    # Does the node look like an external node
    # Has attribute 'External': 1
    def node_is_external(self, data):
        """Pass in node meta data"""
        if data == None:
            return False
        elif 'External' in data and data['External'] == 1:
            return True
        else:
            return False
        
    # Add node
    def add_node(self, s):
        if self.contains_node(s):
            # graph already has s
            pass
        else:
            self.V += 1
            self._add_label(s)
            self.graph.append(None)

    # Contains node
    def contains_node(self, val):
        # s can be int or value
        if type(val) == int:
            # it's an int -- check size
            return 0 <= val < self.V

        if self._index_len != len(self.labels):
            self._rebuild_index()

        return val in self._index

        # if type(s) == int:
        #     s = self.labels[s]


        # if s in self.labels:
        #     return True
        # else:
        #     return False
        
    # Add edges
    def add_edge(self, s, d, weight=1):
        if Verbose.level >= 2:
            print("graph add_edge " + str(self.name_of(s)) + " " + str(self.name_of(d)) + " " + str(weight))

        if not self.contains_node(s):
            if Verbose.level >= 2:
                print("graph add_node " + str(self.name_of(s)))
            self.add_node(s)

        if not self.contains_node(d):
            if Verbose.level >= 2:
                print("graph add_node " + str(self.name_of(d)))
            self.add_node(d)

        # resolve both ends once
        s = self.index_of(s)
        d = self.index_of(d)

        if not self.contains_edge(s, d):
            node = AdjNode(d, weight)
            node.next = self.graph[s]
            self.graph[s] = node

            node = AdjNode(s, weight)
            node.next = self.graph[d]
            self.graph[d] = node
            

    # Contains a link
    def contains_link(self, s, d):
        return self.contains_edge(s, d)
    
    # Contains an edge
    def contains_edge(self, s, d):
        s = self.index_of(s)
        d = self.index_of(d)

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
        s = self.index_of(s)
        d = self.index_of(d)

        # get head of the adjacency
        node = self.graph[s]
        head = node

        # Skip through all the nodes
        while node != None:
            if node.vertex == d:
                return (self.name_of(s), self.name_of(node.vertex), node.weight)
            else:
                node = node.next
        return None

    # get a list of edges
    def edges(self):
        edges = []
        seen = set()            # was a list membership test -- that made this O(E^2)

        for index, label in enumerate(self.labels):
            # get head of the adjacency
            node = self.graph[index] if index < len(self.graph) else None

            # Skip through all the nodes
            while node != None:
                dst_index = node.vertex
                weight = node.weight

                # normalise so a-b and b-a collapse to one entry
                if index <= dst_index:
                    key = (index, dst_index, weight)
                else:
                    key = (dst_index, index, weight)

                if key not in seen:
                    seen.add(key)
                    edges.append((label, self.name_of(dst_index), weight))

                node = node.next

        return edges
        

    # get a list of the node names
    def nodes(self):
        return self.labels

    # get a specific node
    def node(self, val):
        """Get the node represented by val.
           Can be an int or a name"""
        return self.graph[self.index_of(val)]

    # Label for node
    def name_of(self, i):
        i = self.index_of(i)

        if len(self.labels) > i:
            # we have a list of labels
            return self.labels[i]
        else:
            # no labels, so use number
            return str(i)

    # adjacency at val
    def adjacency(self, val):
        node = self.graph[self.index_of(val)]

        if node == None:
            return []

        labels = self.labels
        result = []

        while node != None:
            result.append((labels[node.vertex], node.weight))
            node = node.next

        return result

    # neighbours of s
    def neighbours(self, s):
        "Returns the neighbors of a node s."
        
        connections = []

        # get head of the adjacency
        node = self.node(s)

        # Skip through all the nodes
        while node != None:
            connections.append(self.name_of(node.vertex))
            node = node.next

        return connections
    
    # weigth of an edge
    def weight(self, node1, node2):
        "Returns the weight of an edge between two nodes."
        edge = self.edge(node1, node2)

        return edge[2]

    # Update meta data
    def update_meta_data(self, d):
        # fold the dict d into meta_data
        self.meta_data.update(d)
        
    # Get meta data
    def get_meta_data(self):
        return self.meta_data
        
    # Update meta data
    def update_node_meta_data(self, node, d):
        # fold the dict d into meta_data
        if node in self.node_meta_data:
            self.node_meta_data[node].update(d)
        else:
            self.node_meta_data[node] = d
        
    # Get meta data
    def get_node_meta_data(self, node):
        if node in self.node_meta_data:
            return self.node_meta_data[node]
        else:
            return None
        
    # Get meta data for all nodes
    def get_all_node_meta_data(self):
        return self.node_meta_data
        
    # Print the graph
    def print_agraph(self):
        for i in range(self.V):
            print(str(self.name_of(i)) + ":", end="")
            node = self.graph[i]
            while node:
                print("\t-> {}".format(self.name_of(node.vertex)), end="")
                if node.weight > 1:
                    print(" ({})".format(node.weight), end="")
                if node.next != None:
                    print("")
                node = node.next
                
            print(".")


    def print(self):
        print("{", end="\n")
        for label in self.labels:
            print("  '{}' : {},".format(label, self.adjacency(label), end="\n"))
        print("}")


    # simple Dijkstra algorithm - adapted
    # from https://www.udacity.com/blog/2021/10/implementing-dijkstras-algorithm-in-python.html
    #
    # A faster drop-in engine lives behind this method. Set
    # Graph.dijkstra_backend (or the SC_DIJKSTRA env var) to one of:
    #   "old"     the original min-scan implementation below -- the default,
    #             byte-for-byte unchanged behaviour
    #   "python"  pure-Python binary-heap version    (src/dijkstra_fast.py)
    # Both engines return the same dicts with the same tie-breaks, so routing
    # tables come out identical either way.
    dijkstra_backend = os.environ.get("SC_DIJKSTRA", "old")

    @classmethod
    def dijkstra_algorithm(cls, graph, start_node, use_weights=False):
        """Dijkstra algorithm which returns 3 values:
        the 'source' node, the 'shortest_path' to other nodes,
        the 'previous_nodes' for other nodes. An example:
        {'source': 'a', 'shortest_path': {'a': 0, 'b': 1, 'c': 4,
        'd': 3, 'e': 3}, 'previous_nodes': {'b': 'a', 'c': 'a', 'd': 'b', 'e': 'b'}}"""

        backend = Graph.dijkstra_backend
        if backend == "python":
            import dijkstra_fast
            return dijkstra_fast.dijkstra(graph, start_node, use_weights)
        if backend != "old":
            raise ValueError(
                "dijkstra_backend must be 'old' or 'python', got %r" % (backend,))

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

            if Verbose.level >= 3:
                print("dijkstra_algorithm: neighbours " + current_min_node + " = " + str(len(neighbors)) + " " + str(neighbors))

            for neighbor in neighbors:

                if use_weights:
                    # use the actual weight for the shortest_path
                    next = graph.weight(current_min_node, neighbor)
                else:
                    # use the hop count for the shortest_path
                    next = 1

                tentative_value = shortest_path[current_min_node] + next
                
                if tentative_value < shortest_path[neighbor]:
                    shortest_path[neighbor] = tentative_value
                    # We also update the best path to the current node
                    previous_nodes[neighbor] = current_min_node

            # After visiting its neighbors, we mark the node as "visited"
            unvisited_nodes.remove(current_min_node)

        return { 'source': start_node, 'shortest_path': shortest_path, 'previous_nodes': previous_nodes }




# Adjacency List representation in Python
# Ideas from https://www.programiz.com/dsa/graph-adjacency-list

# Adjacency nodes are linked together
class AdjNode:
    __slots__ = ('vertex', 'next', 'weight')

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
        # the original was missing brackets around the conditional, so it
        # returned just "None" whenever next was None
        return ("AdjNode value: " + str(self.vertex) +
                " weight: " + str(self.weight) +
                " next: (" + ("None" if self.next == None else str(self.next.vertex)) + ")")



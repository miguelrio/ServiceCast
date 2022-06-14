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
        # get head of the adjacency
        node = self.graph[s]

        # Skip through all the nodes
        while node != None:
            if node.vertex == d:
                return True
            else:
                node = node.next
        return False
        
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
        print("{ ", end="")
        for label in self.labels:
            print("'{}' : {},".format(label, self[label]), end="\n")
        print("}")



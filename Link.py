class UnidirectionalLink(object):
    """A unidirectional link.
       Contains 1 LinkEnd.
    """
    def __init__(self, link_end):
        self.link = link_end

    def links(self):
        return { self.link.src_node.id() : self.link }
    
    def __str__(self):
        return "Link " + str(self.link.src_node.id()) + " --> " + str(self.link.dst_node.id())

    def __repr__(self):
        return "Link " + str(self.link.src_node.id()) + " --> " + str(self.link.dst_node.id())

class BidirectionalLink(object):
    """A Bidirectional link.
       Contains 2 LinkEnds.
    """
    def __init__(self, link_end_1, link_end_2):
        self.link1 = link_end_1
        self.link2 = link_end_2

    def links(self):
        return { self.link1.src_node.id() : self.link1, self.link2.src_node.id() : self.link2  }
    
    def __str__(self):
        return "Link " + str(self.link1.src_node.id()) + " <--> " + str(self.link2.src_node.id()) 

    def __repr__(self):
        return "Link " + str(self.link1.src_node.id()) + " <--> " + str(self.link2.src_node.id()) 




class LinkEnd(object):
    """A Link in the Simulation"""
    def __init__(self, env, propagation_delay, src_node, dst_node):
        self.env = env
        self.propagation_delay = propagation_delay
        self.src_node = src_node
        self.dst_node = dst_node

    def put(self, packet):
        """ The call from the Router to do packet forwarding
        """
        self.env.process(self._send(packet))

    def _send(self, packet):
        """ A method to send a packet
        """
        yield self.env.timeout(self.propagation_delay)
        # The destination receives the packet
        self.dst_node.recv(packet, self)

    def __str__(self):
        return "LinkEnd " + str(self.src_node.id()) + " --> " + str(self.dst_node.id()) + " (" + str(self.propagation_delay) + ")"

    def __repr__(self):
        return "LinkEnd " + str(self.src_node.id()) + " --> " + str(self.dst_node.id()) + " (" + str(self.propagation_delay) + ")"


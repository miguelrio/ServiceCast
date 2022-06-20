class Link(object):
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
        """ An internal method
        """
        yield self.env.timeout(self.propagation_delay)
        self.dst_node.put(packet)

    def __str__(self):
        return "Link " + str(self.src_node.id()) + " --> " + str(self.dst_node.id()) + " (" + str(self.propagation_delay) + ")"

    def __repr__(self):
        return "Link " + str(self.src_node.id()) + " --> " + str(self.dst_node.id()) + " (" + str(self.propagation_delay) + ")"


class Link(object):
    """A Link in the Simulation"""
    def __init__(self, env, propagation_delay, dst_node):
        self.env = env
        self.propagation_delay = propagation_delay
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



from Host import Host
from SimComponents import Packet

class Client(Host):
    """ A Client in the Simulation."""
    def __init__(self, env, serverid):
        super().__init__(env, serverid)
        self.type = "Client"

class ClientPacket(Packet):
    """A ClientPacket is a Packet that also holds a request
    """
    def __init__(self, time, size, id, src, dst, flow_id=0):
        super().__init__( time, size, id, src, dst, flow_id)
        # self.value = value

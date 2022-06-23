from Host import Host
from SimComponents import Packet

class Server(Host):
    """ A Server in the Simulation.
    """
    def __init__(self, env, serverid):
        super().__init__(env, serverid)
        self.type = "Server"


class ServerPacket(Packet):
    """A ServerPacket is a Packet that also holds an integer
    """
    def __init__(self, time, size, id, src, dst, flow_id=0):
        super().__init__( time, size, id, src, dst, flow_id)
        # self.value = value

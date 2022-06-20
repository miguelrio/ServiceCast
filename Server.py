from Host import Host

class Server(Host):
    """ A Server in the Simulation.
    """
    def __init__(self, env, serverid):
        super().__init__(env, serverid)
        self.type = "Server"


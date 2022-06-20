from Host import Host

class Client(Host):
    """ A Client in the Simulation."""
    def __init__(self, env, serverid):
        super().__init__(env, serverid)
        self.type = "Client"


from Host import Host

class Client(Host):
    """ A Client in the Simulation."""
    def __init__(self, env, clientid):
        super().__init__(env, clientid)
        self.type = "Client"

    def process_event(self, event):
        # check the type of event we got
        if event.type == "NetworkEvent":
            self.process_packet_event(event)
        else:
            self.process_other_event(event)

    def process_packet_event(self, event):
        # convert an event into a packet
        packet = event
        if packet.src == self.hostid:
            print("{:.3f}: Packet {}.{} ({:.3f}) created in {} after {:.3f}".format(self.env.now,
                packet.src, packet.id, packet.time, self.hostid, (self.env.now - packet.time)))
        else:
            print("{:.3f}: Packet {}.{} ({:.3f}) arrived in {} after {:.3f}".format(self.env.now,
                packet.src, packet.id, packet.time, self.hostid, (self.env.now - packet.time)))
        self.packet_store.put(packet)
        
    def process_other_event(self, event):
        print("Event type {}".format(event.type))


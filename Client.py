from Host import Host
from SimComponents import Packet

class Client(Host):
    """ A Client in the Simulation."""
    def __init__(self, clientid, env=None):
        super().__init__(clientid, env)
        self.type = "Client"

    def process_event(self, event):
        # check the type of event we got
        if event.type == "NetworkEvent":
            self.process_packet_event(event)
        else:
            self.process_other_event(event)

    def process_packet_event(self, event):
        # convert an event into a packet
        packet = Packet(event.time, event.size, event.seq, event.src, event.dst, event.flow_id)
        if packet.src == self.hostid:
            print("{:.3f}: Packet {}.{} ({:.3f}) created in {} after {:.3f}".format(self.env.now,
                packet.src, packet.id, packet.time, self.hostid, (self.env.now - packet.time)))
        else:
            print("{:.3f}: Packet {}.{} ({:.3f}) arrived in {} after {:.3f}".format(self.env.now,
                packet.src, packet.id, packet.time, self.hostid, (self.env.now - packet.time)))

        # add a tuple of (link_end, packet) to the packet store
        # None represents this node
        self.packet_store.put((None, packet))
        
    def process_other_event(self, event):
        print("Event type {}".format(event.type))


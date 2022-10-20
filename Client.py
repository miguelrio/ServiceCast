from Host import Host
from SimComponents import Packet

class Client(Host):
    """ A Client in the Simulation."""
    def __init__(self, clientid, env=None):
        super().__init__(clientid, env)
        self.type = "Client"
        self.pkt_no = 1

    def process_event(self, event):
        # check the type of event we got
        if event.type == "NetworkEvent":
            self.process_packet_event(event)
        else:
            self.process_other_event(event)

    def process_packet_event(self, event):
        # convert an event into a packet
        self.event_to_packet(event)

    def process_other_event(self, event):
        print("Client: Event type {}: {}".format(event.type, str(event)))

    def event_to_packet(self, event):
        # convert an event into a packet
        # Destination is likely to be a service name: e.g. §a
        packet = Packet(event.time, event.size, self.pkt_no, event.src, event.dst, event.flow_id)
        packet.type = "ClientRequest"
        packet.pkt_no = self.pkt_no
        
        print("{:.3f}: Packet {}.{} ({:.3f}) created in {} after {:.3f}".format(self.env.now,
                packet.src, packet.id, packet.time, self.hostid, (self.env.now - packet.time)))

        self.pkt_no += 1

        # add a tuple of (link_end, packet) to the packet store
        # None represents this node
        self.packet_store.put((None, packet))
        

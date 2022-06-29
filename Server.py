from Host import Host
from SimComponents import Packet

class Server(Host):
    """ A Server in the Simulation.
    """
    def __init__(self, serverid, env=None):
        super().__init__(serverid, env)
        self.type = "Server"
        self.saved_event = None


    def process_event(self, event):
        # check the type of event we got
        if event.type == "LoadEvent":
            self.process_load_event(event)
        elif event.type == "NetworkEvent":
            self.process_packet_event(event)
        else:
            self.process_other_event(event)

    def process_load_event(self, event):
        # we got a load event
        print("{:.3f}: {}".format(self.env.now, event))
        
        # it should have: seqno, time, no_of_flows, load
        if self.saved_event == None:
            # first time through        
            # convert an event into a packet
            # set size to 2, to represent 2 values
            packet = Packet(event.time, 2, event.seq, self.id(), dst=event.generator.destinations_dist())
            packet.payload = { 'load': event.load, 'no-of-flows': event.no_of_flows }
            # add a tuple of (link_end, packet) to the packet store
            # None represents this node
            self.packet_store.put((None, packet))

        
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

        # MR: STEP 9 update load (add or subtract)
        # MR: STEP 10 If threshold passes send update
        
    def process_other_event(self, event):
        print("Event type {}: {}".format(event.type, str(event)))


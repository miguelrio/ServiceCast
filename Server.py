from Host import Host
from SimComponents import Packet

class Server(Host):
    """ A Server in the Simulation.
    """
    def __init__(self, serverid, env=None):
        super().__init__(serverid, env)
        self.type = "Server"
        self.saved_event = None
        self.last_info = {}


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
        if self.last_info == {}:
            # first time through        

            # save the values in last_info
            last_info = { 'load': event.load, 'no_of_flows': event.no_of_flows }
            
            # convert an event into a packet
            self.event_to_packet(event)
        else:
            # more events

            if event.load != last_info.load or event.no_of_flows != last_info.no_of_flows:
                # at least one value was changed
                
                # save the values in last_info
                last_info = { 'load': event.load, 'no_of_flows': event.no_of_flows }

                # convert an event into a packet
                self.event_to_packet(event)

            else:
                # nothing changed
                print("Server: LoadEvent no change")

                
        
    def process_packet_event(self, event):
        # convert an event into a packet
        packet = Packet(event.time, event.size, event.seq, event.src, event.dst, event.flow_id)

        print("{:.3f}: Packet {}.{} ({:.3f}) created in {} after {:.3f}".format(self.env.now,
                packet.src, packet.id, packet.time, self.hostid, (self.env.now - packet.time)))


        # add a tuple of (link_end, packet) to the packet store
        # None represents this node
        self.packet_store.put((None, packet))

        # MR: STEP 9 update load (add or subtract)
        # MR: STEP 10 If threshold passes send update
        
    def process_other_event(self, event):
        print("Server: Event type {}: {}".format(event.type, str(event)))


    def event_to_packet(self, event):
        # convert an event into a packet
        # set size to 3, to represent 3 values
        packet = Packet(event.time, 3, event.seq, self.id(), dst=self.neighbour)
        packet.type = "ServerLoad"
        packet.service =  event.service_name
        packet.replica = self.hostid
        packet.payload = { 'load': event.load, 'no_of_flows': event.no_of_flows, 'delay': 0 }

        # add a tuple of (link_end, packet) to the packet store
        # None represents this node
        self.packet_store.put((None, packet))

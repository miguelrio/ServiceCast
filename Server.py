from Host import Host
from SimComponents import Packet
from Verbose import Verbose

class Server(Host):
    """ A Server in the Simulation.
    """
    def __init__(self, serverid, env=None):
        super().__init__(serverid, env)
        self.type = "Server"
        self.saved_event = None

        # values from last LoadEvent
        self.last_event_info =  { 'load': 0, 'no_of_flows': 0 }
        # values from client requests
        self.request_info =  { 'load': 0, 'no_of_flows': 0 }



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
        # more events

        if event.load != self.last_event_info['load'] or event.no_of_flows != self.last_event_info['no_of_flows']:
            # at least one value was changed

            # save the values in last_event_info
            self.last_event_info = { 'load': event.load, 'no_of_flows': event.no_of_flows }

            # convert an event into a packet
            self.send_load_packet(event.time, event.service_name)

        else:
            # nothing changed
            print("Server: LoadEvent no change")

        
    def process_packet_event(self, event):
        # convert an event into a packet
        packet = Packet(event.time, event.size, self.pkt_no, event.src, event.dst, event.flow_id)

        print("{:.3f}: Packet {}.{} ({:.3f}) created in {} after {:.3f}".format(self.env.now,
                packet.src, packet.id, packet.time, self.hostid, (self.env.now - packet.time)))

        self.pkt_no += 1

        # add a tuple of (link_end, packet) to the packet store
        # None represents this node
        self.packet_store.put((None, packet))

    def process_other_event(self, event):
        print("Server: Event type {}: {}".format(event.type, str(event)))

    # Send a ServerLoad packet
    def send_load_packet(self, time, service_name):
        """Send a ServerLoad packet"""
        # convert an event into a packet
        # set size to 3, to represent 3 values
        packet = Packet(time, 3, self.pkt_no, self.id(), dst=self.neighbour)
        packet.type = "ServerLoad"
        packet.service =  service_name
        packet.replica = self.hostid
        packet.payload = { 'load': self.calculate_load(),
                           'no_of_flows': self.calculate_flows(),
                           'delay': 0,
                           'slots': self.calculate_slots() }

        # update packet number for next time
        self.pkt_no += 1

        # add a tuple of (link_end, packet) to the packet store
        # None represents this node
        self.packet_store.put((None, packet))


    # Calculate the load
    def calculate_load(self):
        # we take the load from the last_event_info and
        # the load from the Client requests to
        # make the result
        return int(self.last_event_info['load']) + int(self.request_info['load'])
    
    # Calculate the no of flows
    def calculate_flows(self):
        # we take the no_of_flows from the last_event_info and
        # the no_of_flows from the Client requests to
        # make the result
        return int(self.last_event_info['no_of_flows']) + int(self.request_info['no_of_flows'])

    # Calculate the slots available
    def calculate_slots(self):
        # this is currently:  fn(100 - load)
        raw = 100 - self.calculate_load()
        return int(raw / 4)
    

    # We override manage_packet() to handle ClientRequests
    def manage_packet(self, packet_tuple):
        """ Manage a packet.  
         If it is for us, consume it
         Otherwise, forward it
        """
        (link_end, packet) = packet_tuple
        
        if packet.dst == self.hostid:
            # consume the packet
            self.sink.put(packet)

            if Verbose.level >= 1:
                print("{:.3f}: HOST Packet {}.{} consumed in {} after {:.3f}".format(self.env.now, packet.src, packet.id, self.hostid, (self.env.now - packet.time)))

        else:
            # MR: if packet is data packet (ClientRequest)
            # MR:   STEP 8 forward to right link based on fw table
        
            if self.is_service(packet.dst):
                # this packet is for a Service name
                if getattr(packet, 'type', False) == "ClientRequest": #  packet.type == "ClientRequest":
                    self.client_request_packet(link_end, packet)
                    
            else:
                # If the packet is not for us, forward to the neighbour
                # This is where the main servicecast algorithm will be implemented.
                self.outgoing_port.put(packet)

                if Verbose.level >= 2:
                    print("{:.3f}: HOST Packet {}.{} for {} deliver to {}".format(self.env.now, packet.src, packet.id, packet.dst,  self.neighbour))
           

    # Handle a ClientRequest
    def client_request_packet(self, link_end, packet):
        """A Client has sent a request"""

        if Verbose.level >= 1:
            print("{:.3f}: SERVER_PROCESS ClientRequest at {} for service {} pkt: {}".format(self.env.now, self.id(), packet.dst, packet.id))

        # process the request packet
        self. process_client_request_packet(packet)


    # Process a ClientRequest packet
    def process_client_request_packet(self, packet):
        """Process a ClientRequest packet"""

        # MR: STEP 9 update load (add or subtract)
        # MR: STEP 10 If threshold passes send update

        self.request_info = { 'load': self.request_info['load']+2, 'no_of_flows': self.request_info['no_of_flows']+1 }

        if Verbose.level >= 1:
            print("{:.3f}: REQUEST_FLOWS at {} {}".format(self.env.now, self.id(), self.request_info))
        
        
        # Destination is likely to be a service name: e.g. §a
        service_name = packet.dst

        self.send_load_packet(self.env.now, service_name)

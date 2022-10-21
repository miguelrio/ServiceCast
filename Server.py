from Host import Host
from SimComponents import Packet
from Verbose import Verbose

def load_up_fn(val):
    return val + 2

def load_down_fn(val):
    return val - 2

def flows_up_fn(val):
    return val + 1

def flows_down_fn(val):
    return val - 1

# Convert a request size into a timeout
def size_to_time(size):
    return size


class Server(Host):
    """ A Server in the Simulation.
    """
    def __init__(self, serverid, env=None):
        super().__init__(serverid, env)
        self.type = "Server"
        self.pkt_no = 1
        self.saved_event = None

        # values from last LoadEvent
        self.last_event_info =  { 'load': -1, 'no_of_flows': -1 }  # start condition
        # values from client requests
        self.request_info =  { 'load': 0, 'no_of_flows': 0 }

        # current values from requests
        self.load = 0
        self.no_of_flows = 0
        self.slots = 10


    # The event handler
    def process_event(self, event):
        # check the type of event we got
        if event.type == "LoadEvent":
            self.process_load_event(event)
        elif event.type == "NetworkEvent":
            self.process_packet_event(event)
        else:
            self.process_other_event(event)


    # Process a LoadEvent which generates background load
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
            # print("Server: {} LoadEvent no change".format(self.hostid))
            pass

        
    # Process a NetworkEvent
    def process_packet_event(self, event):
        # convert an event into a packet
        packet = Packet(event.time, event.size, self.pkt_no, event.src, event.dst, event.flow_id)
        packet.pkt_no = self.pkt_no

        print("{:.3f}: Packet {}.{} ({:.3f}) created in {} after {:.3f}".format(self.env.now,
                packet.src, packet.id, packet.time, self.hostid, (self.env.now - packet.time)))

        self.pkt_no += 1

        # add a tuple of (link_end, packet) to the packet store
        # None represents this node
        self.packet_store.put((None, packet))

    def process_other_event(self, event):
        print("Server: Event type {}: {}".format(event.type, str(event)))


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

        # convert packet data into a Request
        request = Request(packet.src, packet.dst, packet.id, packet.size)

        # increase_load will trigger a callback to decrease_load
        new_load = self.increase_load(request)


    # Send a ServerLoad packet
    def send_load_packet(self, time, service_name):
        """Send a ServerLoad packet"""
        # convert an event into a packet
        # set size to 3, to represent 3 values
        packet = Packet(time, 3, self.pkt_no, self.id(), dst=self.neighbour)
        packet.type = "ServerLoad"
        packet.service =  service_name
        packet.replica = self.hostid
        packet.pkt_no = self.pkt_no
        packet.payload = { 'load': self.calculate_load(),
                           'no_of_flows': self.calculate_flows(),
                           'delay': 0,
                           'slots': self.calculate_slots() }

        # update packet number for next time
        self.pkt_no += 1

        # add a tuple of (link_end, packet) to the packet store
        # None represents this node
        self.packet_store.put((None, packet))


    # increase load based on request size
    def increase_load(self, request):

        # MR: STEP 9 update load (add or subtract)
        # MR: STEP 10 If threshold passes send update

        # dig out size of request
        size = request.size

        # calculate new load
        new_load = load_up_fn(self.load)
        new_flows =  flows_up_fn(self.no_of_flows)

        # now we need to check the capacity to see if we can accept this request
        if (self.calculate_slots() == 0):
            # there is no more capacity to take a job
            print("{:.3f}: NO_MORE CAPACITY {} timeout {} for {}.{}".format(self.env.now, self.id(), size_to_time(size), request.src, request.id))
            return

        else:
            # process extra load

            self.load = new_load
            self.no_of_flows = new_flows

            if Verbose.level >= 1:
                print("{:.3f}: INCREASE_LOAD '{}' request  {}.{} timeout {} load: {} no_of_flows: {} capacity: {}".format(self.env.now, self.id(), request.src, request.id, size_to_time(size), self.load, self.no_of_flows, self.calculate_slots()))


            # Destination is likely to be a service name: e.g. §a
            self.send_load_packet(self.env.now, request.dst)

            # process callback event for future decrease
            self.env.process(self.decrease_load(request))


    # decrease load based once request times out
    def decrease_load(self, request):

        # MR: STEP 9 update load (add or subtract)
        # MR: STEP 10 If threshold passes send update

        yield self.env.timeout(size_to_time(request.size))

        new_load = load_down_fn(self.load)
        new_flows =  flows_down_fn(self.no_of_flows)
    
        self.load = new_load
        self.no_of_flows = new_flows
        

        if Verbose.level >= 1:
            print("{:.3f}: DECREASE_LOAD '{}'  request {}.{} after {}  load: {} no_of_flows: {} capacity: {}".format(self.env.now, self.id(), request.src, request.id, size_to_time(request.size),  self.load, self.no_of_flows, self.calculate_slots()))

        # Destination is likely to be a service name: e.g. §a
        service_name = request.dst

        self.send_load_packet(self.env.now, service_name)




    # Calculate the load
    def calculate_load(self):
        # we take the load from the last_event_info and
        # the load from the Client requests to
        # make the result
        return int(self.last_event_info['load']) + int(self.load)
    
    # Calculate the no of flows
    def calculate_flows(self):
        # we take the no_of_flows from the last_event_info and
        # the no_of_flows from the Client requests to
        # make the result
        return int(self.last_event_info['no_of_flows']) + int(self.no_of_flows)

    # Calculate the slots available
    def calculate_slots(self):
        # this is currently:  slots - calculate_flows()
        raw = self.slots - self.calculate_flows()
        return raw

    
class Request(object):
    """This holds the details of a client request"""
    def __init__(self, src, dst, id, size):
        # create with: Request(packet.src, packet.dst, packet.id, packe.size)
        self.src = src
        self.dst = dst
        self.id = id
        self.size = size

    def __repr__(self):
        return "Request: From {} seq: {} service: {} size: {}".format(self.src, self.id, self.dst, self.size)

        

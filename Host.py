import simpy
from SimComponents import SwitchPort, PacketSink
from Link import LinkEnd
from Verbose import Verbose

LINKRATE = 10000000

class Host(object):
    """ A Host in the Simulation.
      Requires a put() method as a callback from the PacketGenerator.
    """

    # network can be a Network or an simpy.Environment()
    # this gives flexibility in usage
    def __init__(self, hostid, network=None):
        self.network = network
        self.hostid = hostid
        self.pkt_no = 1
        self.type = "Host"
        
        # need just one SimComponent.SwitchPort for the neighbour
        self.outgoing_port = None

        # a forwarding table
        # each entry is (destination, next_hop, weight)
        self.unicast_forwarding_table = dict()

        # set the simulation environment
        self.set_env(network)


    def set_env(self, val):
        """ Set the env"""

        from Network import Network
        if isinstance(val, Network):
            # it is a Network
            self.env = val.env
            self.network = val
        elif isinstance(val, simpy.Environment):
            # it is a Environment
            self.env = val
            self.network = None
        else:
            self.env = None

        # Create a structure to retrieve packet sent to this host - think consumer (this host) and producer (the one that sent the packet) pattern
        # e.g. https://simpy.readthedocs.io/en/latest/examples/process_communication.html
        self.packet_store = simpy.Store(self.env, capacity=1)

        # create packet sink
        self.sink = PacketSink(self.env)

        
    def start(self):
        """Start the Host.
        Calls back to the simpy env to start processing"""
        # "Register" the process
        self.env.process(self.run())

        print (self.type + " " + str(self.hostid) + " running")

      
    def add_neighbour(self, neighbour_obj, propdelay=1, rate=LINKRATE):
        """Add a neighbour from this host to a router"""
        link = None
        
        if Verbose.level >= 1:
            print("LinkEnd Add " + self.id() + " -> " + "neighbour " + str(neighbour_obj) + " neighbour_obj " + str(neighbour_obj.id()) + " delay " + str(propdelay))

        self.neighbour = neighbour_obj.id()
        self.outgoing_port = SwitchPort(self.env, rate=rate, limit_bytes=False)
        
        # create a link object for modelling propagation delay. 
        link = LinkEnd(env=self.env,
                    propagation_delay=propdelay,
                    src_node=self,
                    dst_node=neighbour_obj)

              
        # here we connect our port to our neighbour
        self.outgoing_port.out = link

        return ("create", link)

            
            
    def run(self):
        # This function defines the process (in the simpy sense) of receiving a packet
        while True:

            # yielding here will basically "freeze" this process
            # until there is a packet in self.packet_store
            # packet_store is a simpy.Store(self.env, capacity=1)
            # which stores the packet
            # we get it out that
            packet_tuple = yield self.packet_store.get()

            # print ("HOST tuple = (" + str(packet_tuple[0]) + ", " + str(packet_tuple[1]) + ")")

            # now manage the packet
            self.manage_packet(packet_tuple)

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
            # If the packet is not for us, forward to the neighbour
            # This is where the main servicecast algorithm will be implemented.
            self.outgoing_port.put(packet)

            if Verbose.level >= 2:
                print("{:.3f}: HOST Packet {}.{} for {} forwarded from {} to {} after {:.3f}".format(self.env.now, packet.src, packet.id, packet.dst, self.hostid, self.neighbour, (self.env.now - packet.time)))
           
    # Is the destination address a service name:  e.g. §a
    def is_service(self, name):
        """Is the destination address a service name:  e.g. §a"""
        if name == None:
            return False
        elif name.startswith("§"):
            return True
        else:
            return False

    # Set the unicast forwarding table
    def set_unicast_forwarding_table(self, list_of_routes):
        """Set the forwarding table"""
        # takes a list of  entries like (destination, next_hop, weight)
        # and coverts into the internal forwarding table format

        for entry in list_of_routes:
            self.unicast_forwarding_table[entry[0]] = entry

    # Get the unicast forwarding table
    def get_unicast_forwarding_table(self):
        """Get the forwarding table"""

        return self.unicast_forwarding_table

    # Get the route to a specific node
    def route_to(self, dst):
        """Get the next hop for a route to a destination"""
        if isinstance(dst, str):
            return self.unicast_forwarding_table[dst][1]
        else:
            return self.unicast_forwarding_table[dst.id()][1]

    # Get the distance to a specific node
    def distance_to(self, dst):
        """Get the distance to a destination"""
        if isinstance(dst, str):
            return self.unicast_forwarding_table[dst][2]
        else:
            return self.unicast_forwarding_table[dst.id()][2]



    def put(self, event):
        """ The callback from the EventGenerator
        """
        self.process_event(event)

    def process_event(event):
        print("{} Event {} type {}".format(event.time, event.seq, event.type))

    def recv(self, packet, link_end):
        """A packet is received from a LinkEnd of a neighbouring Router.
        """
        if Verbose.level >= 1:
            print("{:.3f}: HOST_RECV '{}' Packet {}.{} consumed from {} after {:.3f}".format(self.env.now,  self.hostid, packet.src, packet.id, link_end.src_node.id(), (self.env.now - packet.time)))

        # add a tuple of (link_end, packet) to the packet store
        self.packet_store.put((link_end, packet))

    def weight_edge(self, node1):
        """What is the weight of the edge from this router to dest"""
        return self.outgoing_port.out.propagation_delay

    def neighbours(self):
        """Neighbours of Host"""
        return [self.neighbour]

    def degree(self):
        """Degree of Host"""
        return 1


    def ports(self):
        """Dict of ports"""
        # Need a Dict
        return { self.neighbour : self.outgoing_port }
            
    def id(self):
        """The id of this node"""
        return self.hostid

    def __str__(self):
        return self.type + " " + str(self.hostid) 

    def __repr__(self):
        return self.type + " " + str(self.hostid) 

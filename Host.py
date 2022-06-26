import simpy
from SimComponents import SwitchPort, PacketSink
from Link import LinkEnd

LINKRATE = 100

class Host(object):
    """ A Host in the Simulation.
      Requires a put() method as a callback from the PacketGenerator.
    """
    def __init__(self, env, hostid):
        self.env = env
        self.hostid = hostid
        # create one SimComponent.SwitchPort for the neighbour
        self.outgoing_port = None
        self.type = "Host"

        # Create a structure to retrieve packet sent to this host - think consumer (this host) and producer (the one that sent the packet) pattern
        # e.g. https://simpy.readthedocs.io/en/latest/examples/process_communication.html
        self.packet_store = simpy.Store(self.env, capacity=1)

        # create packet sink
        self.sink = PacketSink(env)

    def start(self):
        """Start the Host.
        Calls back to the simpy env to start processing"""
        # "Register" the process
        self.env.process(self.run())

        print (self.type + " " + str(self.hostid) + " running")

      
    def add_neighbour(self, neighbour_obj, propdelay=1, rate=LINKRATE):
        """Add a neighbour from this host to a router"""
        link = None
        
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
            packet = yield self.packet_store.get()

            # now manage the packet
            self.manage_packet(packet)

    def manage_packet(self, packet):
        """ Manage a packet.  
         If it is for us, consume it
         Otherwise, forward it
        """
        if packet.dst == self.hostid:
            # consume the packet
            self.sink.put(packet)
            print("{:.3f}: Packet {}.{} consumed in {} after {:.3f}".format(self.env.now,
                packet.src, packet.id, self.hostid, (self.env.now - packet.time)))
        else:
            # If the packet is not for us, forward to all neighbours.
            # This is where the main servicecast algorithm will be implemented.
            self.outgoing_port.put(packet)
            print("{:.3f}: Packet {}.{} forwarded from {} to {} after {:.3f}".format(self.env.now, packet.src, packet.id, self.hostid, self.neighbour, (self.env.now - packet.time)))
           

    def put(self, event):
        """ The callback from the EventGenerator
        """
        self.process_event(event)

    def process_event(event):
        print("{} Event {} type {}".format(event.time, event.seq, event.type))


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

import simpy
from SimComponents import SwitchPort, PacketSink
from Link import LinkEnd
from Host import Host
from Verbose import Verbose

LINKRATE = 100

class Router(object):
    """ A Router in the Simulation.
      Requires a put() method as a callback from the PacketGenerator.
    """
    def __init__(self, routerid, env=None):
        self._routerid = routerid
        # create one SimComponent.SwitchPort for each neighbour_id
        self.outgoing_ports = dict()

        self.set_env(env)

    def set_env(self,env):
        """ Set the env"""
        self.env = env
        # Create a structure to retrieve packet sent to this router - think consumer (this router) and producer (the one that sent the packet) pattern
        # e.g. https://simpy.readthedocs.io/en/latest/examples/process_communication.html
        self.packet_store = simpy.Store(self.env, capacity=1)

        # create packet sink
        self.sink = PacketSink(env)
        
    def start(self):
        """Start the Router.
        Calls back to the simpy env to start processing"""
        # "Register" the process
        self.env.process(self.run())

        print ("Router " + str(self._routerid) + " running")

      
    def add_neighbours(self, neighbours, rate=LINKRATE):
        """ Add some neighbours from a dictionary with label : {router, propogation_delay}
currently {'b': (routerB,1), 'c':  (routerC,4)},
        """
        links = []
        
        # Skip through all the neighbours
        for neighbour in neighbours.keys():
          
          (neighbour_obj, propdelay) = neighbours[neighbour]

          link = self.add_neighbour(neighbour_obj, propdelay, rate)

          if link != None:
              # a new link was created
              links.append(link)

        return links

    def add_neighbour(self, neighbour_obj, propdelay=1, rate=LINKRATE):
        """Add a neighbour to this router"""
        neighbour = neighbour_obj.id()
            
        # check if the neighbour_obj already has a link
        if (self.contains_edge(neighbour_obj)):
            # no need to add a link

            if Verbose.level >= 2:
                print("LinkEnd Exists "  + str(self._routerid) + " --> " + str(neighbour) + " Cancel " +  str(self._routerid) + " --> " + str(neighbour) )

            return ("exists", self.outgoing_ports[neighbour_obj.id()])

        else:
            if Verbose.level >= 1:
                print("LinkEnd Add " + self._routerid + " -> " + "neighbour " + str(neighbour) + " neighbour_obj " + str(neighbour_obj.id()) + " delay " + str(propdelay))

            self.outgoing_ports[neighbour] = SwitchPort(self.env, rate=rate, limit_bytes=False)

            # create a link object for modelling propagation delay. 
            link = LinkEnd(env=self.env,
                        propagation_delay=propdelay,
                        src_node=self,
                        dst_node=neighbour_obj)

            # here we connect our port to our neighbour
            self.outgoing_ports[neighbour].out = link

            return ("create", link)
        

    def contains_edge(self, dest):
        """Is there an edge from this router to dest
        """
        if (dest.id() in self.outgoing_ports):
            return True
        else:
            return False


    def run(self):
        # This function defines the process (in the simpy sense) of receiving a packet
        while True:

            # yielding here will basically "freeze" this process
            # until there is a packet in self.packet_store
            # packet_store is a simpy.Store(self.env, capacity=1)
            # which stores the packet
            # we get it out that
            packet_tuple = yield self.packet_store.get()

            # now manage the packet
            self.manage_packet(packet_tuple)

    def manage_packet(self, packet_tuple):
        """ Manage a packet.  
         If it is for us, consume it
         Otherwise, forward it
        """
        (link_end, packet) = packet_tuple
        
        if packet.dst == self._routerid:
            # consume the packet
            self.sink.put(packet)

            if Verbose.level >= 1:
                print("{:.3f}: Packet {}.{} consumed in {} after {:.3f}".format(self.env.now, packet.src, packet.id, self._routerid, (self.env.now - packet.time)))

        else:
            # If the packet is not for us, forward to all neighbours.
            # This is where the main servicecast algorithm will be implemented.
          # MR: if packet is data packet 
          # MR:   STEP 8 forward to right link based on fw table
          # MR: else
          #       STEP 5,11 forward to appropriate links based on routing table information (fix code below)
          #      STEP 6,12 check if fw table needs changing. If yes, change it
          for neighbour in self.outgoing_ports:
              
            #print("neighbour " + str(self.outgoing_ports[neighbour].out))

            if link_end == None:
                # looks like a local packet
                # try and forward it
                self.outgoing_ports[neighbour].put(packet)

            elif link_end.src_node.id() == neighbour:
                # don't send to where it came from
                if Verbose.level >= 2:
                    print("{:.3f}: Packet {}.{} dont send back from {} to {} after {:.3f}".format(self.env.now, packet.src, packet.id, self.id(), link_end.src_node.id(), (self.env.now - packet.time)))
                pass

            elif isinstance(self.outgoing_ports[neighbour].out.dst_node,  Host):
                # don't send to any connected Hosts
                if Verbose.level >= 2:
                    print("{:.3f}: Packet {}.{} dont send from {} to host {} after {:.3f}".format(self.env.now, packet.src, packet.id, self.id(), self.outgoing_ports[neighbour].out.dst_node.id(), (self.env.now - packet.time)))

            else:
                # forward the packet
                # send to SwitchPort
                self.outgoing_ports[neighbour].put(packet)

                if Verbose.level >= 1:
                    print("{:.3f}: Packet {}.{} forwarded from {} to {} after {:.3f}".format(self.env.now, packet.src, packet.id, self._routerid, neighbour, (self.env.now - packet.time)))
           

    def put(self, packet):
        """ The callback from an EventGenerator.
        """
        # We don't expect to send Events to Routers
        # but for backwards compatibility, we do this
         # add a tuple of (link_end, packet) to the packet store
        self.packet_store.put((None, packet))

    def recv(self, packet, link_end):
        """A packet is received from a LinkEnd of a neighbouring Router.
        """
        # this function should be called by the previous hop to send a packet to this router
        # packet_store is a simpy.Store(self.env, capacity=1)
        if packet.src == self._routerid:
            if Verbose.level >= 1:
                print("{:.3f}: Packet {}.{} ({:.3f}) created in {} after {:.3f}".format(self.env.now,
                packet.src, packet.id, packet.time, self._routerid, (self.env.now - packet.time)))
        else:
            if Verbose.level >= 1:
                print("{:.3f}: Packet {}.{} ({:.3f}) arrived in {} from {} after {:.3f}".format(self.env.now, packet.src, packet.id, packet.time, self._routerid, link_end.src_node.id(), (self.env.now - packet.time)))

        # add a tuple of (link_end, packet) to the packet store
        self.packet_store.put((link_end, packet))

    def neighbours(self):
        """Neighbours of Router"""
        return list(self.outgoing_ports.keys())

    def degree(self):
        """Degree of Router"""
        return len(self.outgoing_ports)

    def ports(self):
        """Dict of ports"""
        return self.outgoing_ports
            
    def id(self):
        """The id of this node"""
        return self._routerid

    def __str__(self):
        return "Router " + str(self._routerid) 

    def __repr__(self):
        return "Router " + str(self._routerid) 

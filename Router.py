import simpy
from SimComponents import SwitchPort, PacketSink
from Link import Link

LINKRATE = 100

class Router(object):
    """ A Router in the Simulation.
      Requires a put() method as a callback from the PacketGenerator.
    """
    def __init__(self, env, routerid):
        self.env = env
        self.routerid = routerid
        # create one SimComponent.SwitchPort for each neighbour_id
        self.outgoing_ports = dict()

        # Create a structure to retrieve packet sent to this router - think consumer (this router) and producer (the one that sent the packet) pattern
        # e.g. https://simpy.readthedocs.io/en/latest/examples/process_communication.html
        self.packet_store = simpy.Store(self.env, capacity=1)


        # create packet sink
        self.sink = PacketSink(env)

        # "Register" the process
        self.env.process(self.run())

        print ("Router " + str(routerid) + " running")

      
    def add_neighbours(self, neighbours, rate=LINKRATE):
        """ Add some neighbours from a dictionary with label : {router, propogation_delay}
currently {'b': (routerB,1), 'c':  (routerC,4)},
        """
        # Skip through all the neighbours
        for neighbour in neighbours.keys():
          
          neighbour_obj, propdelay = neighbours[neighbour]

          # check if the neighbour_obj already has a link
          if (neighbour_obj.contains_edge(self)):
              # no need to add a link
              print("Link Exists "  + str(neighbour) + " --> " + str(self.routerid) + " Cancel " +  str(self.routerid) + " --> " + str(neighbour) )
              pass
          else:
              print("Link Add " + self.routerid + " -> " + "neighbour " + str(neighbour) + " neighbour_obj " + str(neighbour_obj.routerid) + " delay " + str(propdelay))

              self.outgoing_ports[neighbour] = SwitchPort(self.env, rate=rate, limit_bytes=False)
        
              # create a link object for modelling propagation delay. 
              link = Link(env=self.env,
                          propagation_delay=propdelay,
                          dst_node=neighbour_obj)
              # here we connect our port to our neighbour
              self.outgoing_ports[neighbour].out = link

    def contains_edge(self, dest):
        """Is there an edge from this router to dest
        """
        if (dest.routerid in self.outgoing_ports):
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
            packet = yield self.packet_store.get()

            # now manage the packet
            self.manage_packet(packet)

    def manage_packet(self, packet):
        """ Manage a packet.  
         If it is for us, consume it
         Otherwise, forward it
        """
        if packet.dst == self.routerid:
            # consume the packet
            self.sink.put(packet)
            print("Packet {}.{} consumed in {} after {}".format(
                packet.src, packet.id, self.routerid, (self.env.now - packet.time)))
        else:
            # If the packet is not for us, forward to all neighbours.
            # This is where the main servicecast algorithm will be implemented.
          for neighbour in self.outgoing_ports:
            self.outgoing_ports[neighbour].put(packet)
            print("Packet {}.{} forwarded from {} to {} after {}".format(
                 packet.src, packet.id, self.routerid, neighbour, (self.env.now - packet.time)))
           

    def put(self, packet):
        """ The callback from the PacketGenerator
        """
        # this function should be called by the previous hop to send a packet to this router
        # packet_store is a simpy.Store(self.env, capacity=1)
        if packet.src == self.routerid:
            print("Packet {}.{} ({}) created in {} after {}".format(
                packet.src, packet.id, packet.time, self.routerid, (self.env.now - packet.time)))
        else:
            print("Packet {}.{} ({}) arrived in {} after {}".format(
                packet.src, packet.id, packet.time, self.routerid, (self.env.now - packet.time)))
        self.packet_store.put(packet)



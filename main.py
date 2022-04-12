# Simulation of the ServiceCast system
# Uses simpy and grotto networking:
# https://www.grotto-networking.com/DiscreteEventPython.html
from SimComponents import SwitchPort, PacketGenerator, PacketSink
import simpy
import numpy as np


def process_message():
    pass



LINKRATE = 100

# Lets defind the topology of the network

class Router:
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
        self.incoming_packet = simpy.Store(self.env, capacity=1)


        # create packet sink
        self.sink = PacketSink(env)

        # "Register" the process
        self.env.process(self.run())
      
    def add_neighbours(self, neighbours):
        """ Add some neighbours from a dictionary with label : {router, propogation_delay}
currently {'b': (routerB,1), 'c':  (routerC,4)},
        """
        for neighbour in neighbours.keys():
          
          neighbour_obj, propdelay = neighbours[neighbour]
          self.outgoing_ports[neighbour] = SwitchPort(self.env, rate=LINKRATE, limit_bytes=False)
        
          # create a link object for modelling propagation delay. 
          link = Link(env=self.env,
                      propagation_delay=propdelay,
                      dst_node=neighbour_obj)
          # here we connect our port to our neighbour
          self.outgoing_ports[neighbour].out = link

    def run(self):
        # This function defines the process (in the simpy sense) of receiving a packet
        while True:

            # yielding here will basically "freeze" this process until there is a packet in self.in_packets
            packet = yield self.incoming_packet.get()

            self.manage_packet(packet)

    def manage_packet(self, packet):
        if packet.dst == self.routerid:
            # consume the packet
            self.sink.put(packet)
            print("Packet {} consumed in {} at {}".format(
                packet.id, self.routerid, self.env.now))
        else:
            # If the packet is not for us, forward to all neighbours. This is where the main servicecast algorithm will be implemented.
          for neighbour in self.outgoing_ports:
            self.outgoing_ports[neighbour].put(packet)
            print("Packet {} forwarded from {} to {} at {}".format(
                 packet.id, self.routerid, neighbour, self.env.now))
           

    def put(self, packet):
        # this function should be called by the previous hop to send a packet to this router
        self.incoming_packet.put(packet)


class Link:
    """A Link in the Simulation"""
    def __init__(self, env, propagation_delay, dst_node):
        self.env = env
        self.propagation_delay = propagation_delay
        self.dst_node = dst_node

    def _send(self, packet):
        yield self.env.timeout(self.propagation_delay)
        self.dst_node.put(packet)

    def put(self, packet):
        self.env.process(self._send(packet))


def create_packet_generator(env,
                            id,
                            possible_destinations,
                            exponential_lambda=1,
                            packet_size=100,
                            seed=None):
    # PacketGenerator accepts three (zero arguments) functions as arguments, one that gives the inter arrival times, one  the packet sizes and one that gives the destinations

    # We first define our random numberr generator so that we can reproduce results
    gen = np.random.RandomState(seed=seed)

    def adist():
        # The interarrival times of a poisson process follow an exponential
        next_time = gen.exponential(exponential_lambda)
        return next_time

    def sdist():
        # We'll just assume all packets have the same size given by packet_size
        return packet_size

    def destinations_dist():
        return gen.choice(possible_destinations)

    # Create the packet generator oobject
    packet_generator = PacketGenerator(env,
                                       id=id,
                                       adist=adist,
                                       sdist=sdist,
                                       destinations_dist=destinations_dist)
    return packet_generator

######################
# Code starts here
#############################
def square_topology_example():

  # 1 - First we create the simpy environment 
    env = simpy.Environment()


  # 2 - We define the routers. This needs to be changed to a list/array of routers
    a=Router(env, "a")
    b=Router(env, "b")
    c=Router(env, "c")
    d=Router(env, "d")
    e=Router(env, "e")

  # 3 - Now we add the neighbours from the topology.
    neighbours = {
        'a': {'b': (b,1), 'c':  (c,4)},
        'b': {'c': (c,3), 'd':  (d,2), 'e':  (e,2)},
        'c': {},
        'd': {'b': (b,1), 'c':  (c,5)},
        'e': {'d': (d,5)}
      }

    a.add_neighbours(neighbours["a"])
    b.add_neighbours(neighbours["b"])
    c.add_neighbours(neighbours["c"])
    d.add_neighbours(neighbours["d"])
    e.add_neighbours(neighbours["e"])

  # 4 - Now we create the packet generator. For now, only router a generates packets
    pg = create_packet_generator(env,
                                 "a", ["b", "c", "d","e"],
     
                                 exponential_lambda=5)
  # This line makes packet generator member out poiting to a. it will then do self.out.put() which puts the packet in the receiving queue of router a
    pg.out = a
    env.run(until=400)


square_topology_example()

#

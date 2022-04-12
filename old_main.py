# Simluation of the ServiceCast system
# Uses simpy and grotto networking:
# https://www.grotto-networking.com/DiscreteEventPython.html
from SimComponents import SwitchPort, PacketGenerator, PacketSink
import simpy
import numpy as np


def process_message():
    pass


PROPAGATIONDELAY = 100
LINKRATE = 100


class Router:
    def __init__(self, env, routerid, neighbours, routing_table):
        self.env = env
        self.routerid = routerid
        # create one SimComponent.SwitchPort for each neighbour_id
        self.outgoing_ports = dict()
        for neighbour in neighbours:
            self.outgoing_ports[neighbour.routerid] = SwitchPort(
                env, rate=LINKRATE, limit_bytes=False)

            # create a link object for modelling propagation delay
            link = Link(env=self.env,
                        propagation_delay=PROPAGATIONDELAY,
                        dst_node=neighbour)
            # here we connect our port to our neighbour
            self.outgoing_ports[neighbour.routerid].out = link

            # Create a structure to retrieve packet sent to this router - think consumer (this router) and producer (the one that sent the packet) pattern
        # e.g. https://simpy.readthedocs.io/en/latest/examples/process_communication.html
        self.incoming_packet = simpy.Store(self.env, capacity=1)

        self.routing_table = routing_table

        # create packet sink
        self.sink = PacketSink(env)

        # "Register" the process
        self.env.process(self.run())

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
            # forward
            next_hop = self.routing_table[packet.dst]
            self.outgoing_ports[next_hop].put(packet)
            print("Packet {} forwarded from {} to {} at {}".format(
                packet.id, self.routerid, next_hop, self.env.now))

    def put(self, packet):
        # this function should be called by the previous hop to send a packet to this router
        self.incoming_packet.put(packet)


class Link:
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


def square_topology_example():
    env = simpy.Environment()

    r4_routing_table = {}
    r4 = Router(env, "r4", [], r4_routing_table)

    r3_routing_table = {"r4": "r4"}
    r3 = Router(env, "r3", [r4], r3_routing_table)

    r2_routing_table = {"r3": "r3"}
    r2 = Router(env, "r2", [r3], r2_routing_table)

    r1_routing_table = {"r2": "r2", "r3": "r2", "r4": "r4"}
    r1 = Router(env, "r1", [r2, r4], r1_routing_table)

    pg = create_packet_generator(env,
                                 "r1_pg", ["r2", "r3", "r4"],
                                 exponential_lambda=5)
    pg.out = r1
    env.run(until=400)


square_topology_example()

#

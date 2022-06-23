from SimComponents import PacketGenerator
from Server import ServerPacket
from Client import ClientPacket
import numpy as np


class ServerPacketGenerator(PacketGenerator):
    """ A PacketGenerator for a Server."""
    def __init__(self, env, id,  adist, sdist, destinations_dist, initial_delay=0, finish=float("inf"), flow_id=0):
        super().__init__(env, id,  adist, sdist, destinations_dist, initial_delay=0, finish=float("inf"), flow_id=0)

    # Prepare a packet for transmission
    # Use a ServerPacket
    def preparePacket(self):
        """Prepare a packet for transmission"""
        # Use the ServerPacket class
        p = ServerPacket(self.env.now, self.sdist(), self.packets_sent, src=self.id, dst=self.destinations_dist(), flow_id=self.flow_id)
        self.out.put(p)


class ClientPacketGenerator(PacketGenerator):
    """ A PacketGenerator for a Client."""
    def __init__(self, env, id,  adist, sdist, destinations_dist, initial_delay=0, finish=float("inf"), flow_id=0):
        super().__init__(env, id,  adist, sdist, destinations_dist, initial_delay=0, finish=float("inf"), flow_id=0)

    # Prepare a packet for transmission
    # Use a ServerPacket
    def preparePacket(self):
        """Prepare a packet for transmission"""
        # Use the ServerPacket class
        p = ClientPacket(self.env.now, self.sdist(), self.packets_sent, src=self.id, dst=self.destinations_dist(), flow_id=self.flow_id)
        self.out.put(p)



class Generator(object):
    """A Generator of packets, using server_packet_generator() for ServerPacketGenerator
    """
    def __init__(self, network, generator):
        self.generator = generator
        self.network = network

    #  A packet generator for a server
    @classmethod
    def server_packet_generator(cls, network, id, possible_destinations,
                         exponential_lambda=1,
                         packet_size=100,
                         seed=None):
        """ Generates packets from node with 'id', and sends to 'possible_destinations'.
            'exponential_lambda' is passed to the arrival distribution.
            'packet_size' is used for the size distribution.
        """

        env = network.env

        # PacketGenerator accepts three (zero arguments) functions as arguments,
        # - one that gives the inter arrival times,
        # - one that gives the packet sizes, and
        # - one that gives the destinations.

        # We first define our random number generator so that we can reproduce results
        gen = np.random.RandomState(seed=seed)

        # The interarrival times of a poisson process follow an exponential
        def arrival_dist():
            next_time = gen.exponential(exponential_lambda)
            return next_time

        # Assume all packets have the same size given by packet_size
        def size_dist():
            return packet_size

        # Send to all destinations
        def destinations_dist():
            return gen.choice(possible_destinations)

        # Create the packet generator oobject
        packet_generator = ServerPacketGenerator(env, id=id,
                                           adist=arrival_dist, sdist=size_dist,
                                           destinations_dist=destinations_dist)


        # This line makes packet generator member out poiting to a. it will then do self.out.put() which puts the packet in the receiving queue of router a
        packet_generator.out = network[id]
    


        return Generator(network, packet_generator)

    #  A packet generator for a server
    @classmethod
    def client_packet_generator(cls, network, id, possible_destinations,
                         exponential_lambda=1,
                         packet_size=100,
                         seed=None):
        """ Generates packets from node with 'id', and sends to 'possible_destinations'.
            'exponential_lambda' is passed to the arrival distribution.
            'packet_size' is used for the size distribution.
        """

        env = network.env

        # PacketGenerator accepts three (zero arguments) functions as arguments,
        # - one that gives the inter arrival times,
        # - one that gives the packet sizes, and
        # - one that gives the destinations.

        # We first define our random number generator so that we can reproduce results
        gen = np.random.RandomState(seed=seed)

        # The interarrival times of a poisson process follow an exponential
        def arrival_dist():
            next_time = gen.exponential(exponential_lambda)
            return next_time

        # Assume all packets have the same size given by packet_size
        def size_dist():
            return packet_size

        # Send to all destinations
        def destinations_dist():
            return gen.choice(possible_destinations)

        # Create the packet generator oobject
        packet_generator = ClientPacketGenerator(env, id=id,
                                           adist=arrival_dist, sdist=size_dist,
                                           destinations_dist=destinations_dist)


        # This line makes packet generator member out poiting to a. it will then do self.out.put() which puts the packet in the receiving queue of router a
        packet_generator.out = network[id]
    


        return Generator(network, packet_generator)
    

from SimComponents import EventGenerator, Event
import numpy as np


class ServerEventGenerator(EventGenerator):
    """ A Packet Generator for a Server."""
    def __init__(self, env, id,  adist, sdist, destinations_dist, initial_delay=0, finish=float("inf"), flow_id=0):
        super().__init__(env, id,  adist, sdist, destinations_dist, initial_delay, finish, flow_id)

    # Prepare a ServerEvent 
    def create_event(self):
        """Create an Event"""
        e = ServerEvent(self.env.now, self.sdist(), self.event_count, src=self.id, dst=self.destinations_dist(), flow_id=self.flow_id)
        return e

class ServerEvent(Event):
    """A ServerEvent is an Event that also holds an integer
    """
    def __init__(self, time, size, id, src, dst, flow_id=0):
        self.type = "NetworkEvent"
        self.time = time
        self.size = size
        self.id = id
        self.src = src
        self.dst = dst
        self.flow_id = flow_id


class ClientEventGenerator(EventGenerator):
    """ A Packet Generator for a Client."""
    def __init__(self, env, id,  adist, sdist, destinations_dist, initial_delay=0, finish=float("inf"), flow_id=0):
        super().__init__(env, id,  adist, sdist, destinations_dist, initial_delay, finish, flow_id)

    # Prepare a ClientEvent
    def create_event(self):
        """Create an Event"""
        e = ClientEvent(self.env.now, self.sdist(), self.event_count, src=self.id, dst=self.destinations_dist(), flow_id=self.flow_id)
        return e


class ClientEvent(Event):
    """A ClientEvent is an Event that also holds an integer
    """
    def __init__(self, time, size, id, src, dst, flow_id=0):
        self.type = "NetworkEvent"
        self.time = time
        self.size = size
        self.id = id
        self.src = src
        self.dst = dst
        self.flow_id = flow_id

class Generator(object):
    """A Generator of events, using server_event_generator() for ServerEventGenerator
    """
    def __init__(self, network, generator):
        self.generator = generator
        self.network = network

    #  A event generator for a server
    @classmethod
    def server_event_generator(cls, network, id, possible_destinations,
                         exponential_lambda=1,
                         packet_size=100,
                         seed=None):
        """ Generates events from node with 'id', and sends to 'possible_destinations'.
            'exponential_lambda' is passed to the arrival distribution.
            'packet_size' is used for the size distribution.
        """

        env = network.env

        # EventGenerator accepts three (zero arguments) functions as arguments,
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

        # Create the event generator oobject
        event_generator = ServerEventGenerator(env, id=id,
                                           adist=arrival_dist, sdist=size_dist,
                                           destinations_dist=destinations_dist)


        # This line makes event generator member out pointing to node 'id'.
        # It will then do self.out.put() which puts the event in the receiving queue
        # of node 'id'
        event_generator.out = network[id]
    


        return Generator(network, event_generator)

    #  A event generator for a server
    @classmethod
    def client_event_generator(cls, network, id, possible_destinations,
                         exponential_lambda=1,
                         packet_size=100,
                         seed=None):
        """ Generates events from node with 'id', and sends to 'possible_destinations'.
            'exponential_lambda' is passed to the arrival distribution.
            'packet_size' is used for the size distribution.
        """

        env = network.env

        # EventGenerator accepts three (zero arguments) functions as arguments,
        # - one that gives the inter arrival times,
        # - one that gives the event sizes, and
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

        # Create the event generator oobject
        event_generator = ClientEventGenerator(env, id=id,
                                           adist=arrival_dist, sdist=size_dist,
                                           destinations_dist=destinations_dist)


        # This line makes event generator member out pointing to node 'id'.
        # It will then do self.out.put() which puts the event in the receiving queue
        # of node 'id'
        event_generator.out = network[id]
    


        return Generator(network, event_generator)
    

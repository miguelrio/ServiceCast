from SimComponents import EventGenerator, Event
import numpy as np


class ServerEventGenerator(EventGenerator):
    """ An Event Generator for a Server."""
    def __init__(self, env, id,  adist, sdist, destinations_dist, initial_delay=0, finish=float("inf"), flow_id=0):
        super().__init__(env, id,  adist, sdist, destinations_dist, initial_delay, finish, flow_id)
        self.network = None


    # Prepare a ServerEvent 
    def create_event(self):
        """Create an Event"""
        e = ServerEvent(self.env.now, self.sdist(), self.event_count, src=self.id, dst=self.destinations_dist(), flow_id=self.flow_id)
        return e

class ServerLoadEventGenerator(EventGenerator):
    """ An Event Generator for a Server."""
    def __init__(self, env, id,  adist, flowdist, loaddist, destinations_dist, initial_delay=0, finish=float("inf"), flow_id=0):
        # we dont use sdist here, so set to None
        super().__init__(env, id,  adist, None, destinations_dist, initial_delay, finish, flow_id)
        self.flowdist = flowdist
        self.loaddist = loaddist
        self.network = None


    # Prepare a ServerEvent 
    def create_event(self):
        """Create an Event"""
        e = ServerLoadEvent(self.env.now, self.id, self.event_count, self.destinations_dist(), self.flowdist(), self.loaddist(), self)
        return e

class ServerEvent(Event):
    """A ServerEvent is an Event that holds a src and dst address, and also holds an integer as size
    """
    def __init__(self, time, size, seq, src, dst, flow_id=0):
        self.type = "NetworkEvent"
        self.seq = seq
        self.time = time
        self.size = size
        self.src = src
        self.dst = dst
        self.flow_id = flow_id

class ServerLoadEvent(Event):
    """A ServerEvent is an Event that holds some load info
    """
    def __init__(self, time, id, seq, service_name, flows, load, generator):
        self.type = "LoadEvent"
        self.seq = seq
        self.time = time
        self.id = id
        self.service_name = service_name
        self.no_of_flows = flows
        self.load = load
        self.generator = generator

    def __repr__(self):
        return "{}: time: {} id: {} seq: {} service: {} no_of_flows: {} load: {}".\
            format(self.type, self.time, self.id, self.seq, self.service_name, self.no_of_flows, self.load)

        
# Generate Events for a Single Client, with a specified address
class ClientEventGenerator(EventGenerator):
    """ An Event Generator for a Client."""
    def __init__(self, env, id, adist, sdist, destinations_dist, initial_delay=0, finish=float("inf"), flow_id=0):
        super().__init__(env, id,  adist, sdist, destinations_dist, initial_delay, finish, flow_id)
        self.network = None

    # Prepare a ClientEvent
    def create_event(self):
        """Create an Event"""
        src = self.destinations_dist()
        e = ClientEvent(self.env.now, self.sdist(), self.event_count, src=self.id, dst=self.destinations_dist(), flow_id=self.flow_id)
        return e


# Generate Events for a Multiple Clients, with a specified address
class MultiClientEventGenerator(EventGenerator):
    """ An Event Generator for Multiple Clients."""
    def __init__(self, env, id, adist, sdist, destinations_dist, initial_delay=0, finish=float("inf"), flow_id=0):
        super().__init__(env, id,  adist, sdist, destinations_dist, initial_delay, finish, flow_id)
        self.network = None

    # Prepare a ClientEvent
    def create_event(self):
        """Create an Event"""
        src = self.destinations_dist()
        e = ClientEvent(self.env.now, self.sdist(), self.event_count, src=src, dst=self.id, flow_id=self.flow_id)
        return e

    # Process an event
    # Having a separate method makes it easier to do subclasses
    def process_event(self, ev):
        """Process an event"""
        # Put the event in the out channel of the selected client
        out = self.network[ev.src]
        out.put(ev)



class ClientEvent(Event):
    """A ClientEvent is an Event that also holds an integer
    """
    def __init__(self, time, size, seq, src, dst, flow_id=0):
        self.type = "NetworkEvent"
        self.seq = seq
        self.time = time
        self.size = size
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
        event_generator.network = network


        return Generator(network, event_generator)

    #  A event generator for a server
    @classmethod
    def server_load_event_generator(cls, network, id, possible_service_names,
                         exponential_lambda=1,
                         packet_size=100,
                         seed=None):
        """ Generates events from node with 'id', and sends to the immediate neighbour.
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

        # The interarrival time is the same
        def arrival_dist():
            ##next_time = gen.exponential(exponential_lambda)
            next_time = 10
            return next_time

        # No of flows is poisson
        def no_of_flows_dist():
            next_val = gen.poisson(1.0)
            return next_val

        def load_dist():
            # normal 0 - 100,  mu = 50 +/- 20 stddevs
            # next_val = gen.normal(loc=50.0, scale=20, size=None)

            next_val = gen.choice([0, 1, 2, 3, 4])
            return next_val
        
        # Select one service
        def service_name():
            return gen.choice(possible_service_names)

        event_generator = ServerLoadEventGenerator(env, id=id,
                                               adist=arrival_dist, flowdist=no_of_flows_dist,
                                               loaddist=load_dist,
                                                   destinations_dist=service_name)


        # This line makes event generator member out pointing to node 'id'.
        # It will then do self.out.put() which puts the event in the receiving queue
        # of node 'id'
        event_generator.out = network[id]
        event_generator.network = network


        return Generator(network, event_generator)

    # A event generator for a client
    # Sends from a specific node with 'id', and sends to 'possible_destinations'
    @classmethod
    def client_event_generator(cls, network, id, possible_destinations,
                         exponential_lambda=1,
                         packet_size=100,
                         seed=None):
        """ Generates events from a specific node with 'id', and sends to 'possible_destinations'.
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
    
    # A event generator for a number of clients
    # Drops Events on clients in 'possible_sources' list
    @classmethod
    def multi_client_event_generator(cls, network, possible_sources, target_name,
                         exponential_lambda=1,
                         packet_size=100,
                         seed=None):
        """ Generates events from nodes from 'possible_sources'.
            'exponential_lambda' is passed to the arrival distribution.
            'packet_size' is used for the size distribution.
        """

        env = network.env

        # EventGenerator accepts three (zero arguments) functions as arguments,
        # - one that gives the inter arrival times,
        # - one that gives the event sizes, and
        # - one that gives the sources

        # We first define our random number generator so that we can reproduce results
        gen = np.random.RandomState(seed=seed)

        # The interarrival times of a poisson process follow an exponential
        def arrival_dist():
            next_time = gen.exponential(exponential_lambda)
            return next_time

        # Assume all packets have the same size given by packet_size
        def size_dist():
            return packet_size

        # Send to sources
        def sources_dist():
            return gen.choice(possible_sources)

        # Create the event generator oobject
        event_generator = MultiClientEventGenerator(env, target_name,
                                           adist=arrival_dist, sdist=size_dist,
                                                    destinations_dist=sources_dist)


        # This line makes event generator member out pointing to node 'id'.
        # It will then do self.out.put() which puts the event in the receiving queue
        # of node 'id'
        event_generator.network = network



        return Generator(network, event_generator)
    

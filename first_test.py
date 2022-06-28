# Simulation of the ServiceCast system
# Uses simpy and grotto networking:
# https://www.grotto-networking.com/DiscreteEventPython.html
from SimComponents import PacketGenerator
from Router import Router
from Verbose import Verbose
import numpy as np
import simpy

#def process_message():
#    pass

# Lets define a packet generator
def create_packet_generator(env,
                            id,
                            possible_destinations,
                            exponential_lambda=1,
                            packet_size=100,
                            seed=None):
    """ Generates packets from node with 'id', and sends to 'possible_destinations'.
        'exponential_lambda' is passed to the arrival distribution.
        'packet_size' is used for the size distribution.
    """

    # PacketGenerator accepts three (zero arguments) functions as arguments, one that gives the inter arrival times, one  the packet sizes and one that gives the destinations

    # We first define our random numberr generator so that we can reproduce results
    gen = np.random.RandomState(seed=seed)

    def arrival_dist():
        # The interarrival times of a poisson process follow an exponential
        next_time = gen.exponential(exponential_lambda)
        return next_time

    def size_dist():
        # We'll just assume all packets have the same size given by packet_size
        return packet_size

    def destinations_dist():
        return gen.choice(possible_destinations)

    # Create the packet generator oobject
    packet_generator = PacketGenerator(env,
                                       id=id,
                                       adist=arrival_dist,
                                       sdist=size_dist,
                                       destinations_dist=destinations_dist)
    return packet_generator

# Lets defind the topology of the network
def square_topology_example_orig():
    Verbose.level = 2
  
  # 1 - First we create the simpy environment 
    env = simpy.Environment()


  # 2 - We define the routers. This needs to be changed to a list/array of routers
    a=Router("a", env)
    b=Router("b", env)
    c=Router("c", env)
    d=Router("d", env)
    e=Router("e", env)

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
    pg = create_packet_generator(env, "a", ["b", "c", "d","e"], exponential_lambda=5)

  # This line makes packet generator member out poiting to a. it will then do self.out.put() which puts the packet in the receiving queue of router a
    pg.out = a


    # 5 - start the run

    # start the routers first
    a.start()
    b.start()
    c.start()
    d.start()
    e.start()


    env.run(until=400)

    
square_topology_example_orig()

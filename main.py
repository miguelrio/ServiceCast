# Simulation of the ServiceCast system
# Uses simpy and grotto networking:
# https://www.grotto-networking.com/DiscreteEventPython.html
from SimComponents import PacketGenerator
from Router import Router
from Link import Link
from AdjList import Graph
from Network import Network
import simpy
import numpy as np


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

    
def square_topology_example_adj():
    # 1 - First we create the simpy environment 
    env = simpy.Environment()

    # 2 - Define the topology
    topo = {
        'a': { 'b', ('c', 4)},
        'b': { ('c', 3), ('d', 2), ('e', 2)},
        'c': { },
        'd': { 'b', ('c', 5)},
        'e': { ('d', 5)}
      }

    # 3 - build the network
    graph = Graph.from_dict(topo)
    network = Network(env, graph)
    
    # graph.print()
    
    # 4 - Now we create the packet generator. For now, only router a generates packets
    pg = create_packet_generator(env,
                                 "a", ["b", "c", "d","e"],
                                 exponential_lambda=5)
    # This line makes packet generator member out poiting to a. it will then do self.out.put() which puts the packet in the receiving queue of router a
    pg.out = network['a']
    
    env.run(until=400)

    
# go !


# spec = {'A': set([('B', 10), ('C', 20)]),
#               'B': set(['A', 'D', 'E']),
#               'C': set(['A', 'F']),
#               'D': set(['B']),
#               'E': set(['B', 'F']),
#               'F': set(['C', 'E'])}

# graph = Graph.from_dict(spec)
    
# print(graph['A'])
# print(graph[0])

# graph.print()

#network = Network(simpy.Environment(), graph)
#print (network)

square_topology_example_adj()

#square_topology_example_orig()




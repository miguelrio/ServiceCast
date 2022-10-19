from Network import Network
from Generator import Generator
from Verbose import Verbose
import simpy

def ev_print(ev):
    print("{:>8.3f}: {:5d} {:>6s} {:5d}".format(ev.time, ev.seq, ev.src, ev.size ))
        
# Use a topology from an adjacency list
def topology_setup():
    Verbose.level = 2

    # - create the simpy environment 
    env = simpy.Environment()

    network = Network(env)
    
    # Clients 'c1' ... 'c5' generates packets from arriving events
    generator_m1 = Generator.multi_client_event_generator(network, ["c1", "c2", "c3", "c4", "c5"], "§a", exponential_lambda=3, seed=30072022)
    # bind in the ev_print function
    generator_m1.generator.elsefn = ev_print

    # run

    network.start(until=400)


# go !
topology_setup()


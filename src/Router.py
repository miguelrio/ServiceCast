import simpy
from SimComponents import SwitchPort, PacketSink, Packet
from Link import LinkEnd
from Host import Host
from Verbose import Verbose
from Utility import Utility
from Server import Server, ServerMetricMessageType
from enum import Enum
# importing "collections" for defaultdict
import collections
import itertools


class Compare(Enum):
    Same = 0
    Worse = 1
    Better = 2

    def __repr__(self):
        return self.name

    

# Port rate in BITS PER MILLISECOND (= 10 Mbit/s), so that the transmission
# time size*8/rate comes out in clock milliseconds (see src/units.py).
LINKRATE = 10000


def less_than(x,y):
    return x < y

def greater_than(x,y):
    return x > y

def same_as(x,y):
     return x == y


# The comparison functions by name, for config files (Importer)
COMPARATORS = {
    "less_than": less_than,
    "greater_than": greater_than,
    "same_as": same_as,
}


class Router(object):
    """ A Router in the emulation.
      Requires a put() method as a callback from the PacketGenerator.
    """

    # threshold for FIB utility change factor  10% -> 0.1
    # 5 Nov 2026: 0.0001 (was 0.1; runs so far used 0.001), so by default the
    # FIB changes on any real improvement in utility, while differences from
    # float rounding (~1e-16) never flip it
    fib_utility_update_threshold = 0.0001

    # routing mode: True for hop-by-hop anycast, False for first-decide unicast
    hop_by_hop = False

    # Remove FIB if all replicas in the RIB have utility of zero 
    remove_fib_entry_when_all_utilities_zero = True

    # Only send ServerMetric updates to neighbours whose unicast next hop
    # toward the replica is this router (children in the replica's
    # shortest-path tree). Others would drop them as not on the unicast route.
    # NB: reads the neighbour's FIB directly - a simulation shortcut.
    # Nov 2026 (T-13): on by default (was off). Message counts stay comparable
    # with runs that have it off: see tree_skipped and skipped_sent.
    forward_to_tree_children_only = True

    # Nov 2026 (T-12): after a withdrawal, announce entries the withdrawn
    # one was dominating (see announce_freed_entries). False (the default
    # for now) gives the original behaviour: they wait for the next
    # announcement to arrive. Off until its cost and effect on accuracy are
    # measured on more placements and the full CAIDA topology (on the 1K
    # CAIDA subset: about 8% more messages and 12% more run time).
    announce_freed_after_withdraw = False

    # count of ServerMetric updates dropped as not from the unicast route,
    # in total and by operation (A / W)
    invalid_route_drops = 0
    invalid_route_drops_op = {'A': 0, 'W': 0}

    # ServerMetric updates not sent because of forward_to_tree_children_only
    # (A / W): exactly the ones a run with it off would send and then drop as
    # INVALID_ROUTE_DROPS (except any still in flight when the run ends), as
    # long as the two runs stay the same: with the flag off these updates
    # also take port transmission time, so on a busy network the runs drift
    # apart and the counts agree only roughly (Nov 2026, T-13: 0.3% on 1K)
    tree_skipped = {'A': 0, 'W': 0}

    # end-of-run counts (see Network.print_metrics_summary):
    # ServerMetric receptions by operation (A / W), as RECV_PACKET lines would show
    recv_server_metric = {'A': 0, 'W': 0}
    # FIB stability actions per router, as the *_BEST_REPLICA lines would show
    fib_actions = {}

    @classmethod
    def count_fib_action(cls, router_id, action):
        counts = cls.fib_actions.get(router_id)
        if counts is None:
            counts = cls.fib_actions[router_id] = {'SET': 0, 'KEEP': 0, 'CHANGED': 0, 'REMOVED': 0}
        counts[action] += 1

    # reset the end-of-run counters (class-level, so shared by all routers)
    @classmethod
    def reset_counters(cls):
        cls.invalid_route_drops = 0
        cls.invalid_route_drops_op = {'A': 0, 'W': 0}
        cls.tree_skipped = {'A': 0, 'W': 0}
        cls.recv_server_metric = {'A': 0, 'W': 0}
        cls.fib_actions = {}

    # The following staticmethods can be reset from the outside
    # to change the behaviour of the algorithms

    # default better than fn
    
    # the default better for load is less_than
    better_than_fn_load = staticmethod(less_than)
    # the default better for delay is less_than
    better_than_fn_delay = staticmethod(less_than)

    # default same as fn

    # the default same as for load is less_than
    same_as_fn_load = staticmethod(same_as)
    # the default same as for delay is less_than
    same_as_fn_delay = staticmethod(same_as)




    # network can be a Network or an simpy.Environment()
    # this gives flexibility in usage
    def __init__(self, routerid, network=None):
        self.network = network
        self._routerid = routerid
        self.pkt_no = 1
        self.type = "Router"

        # create one SimComponent.SwitchPort for each neighbour_id
        self.outgoing_ports = dict()

        # the ports with their neighbours, for announce_metrics (see _ports_by_neighbour)
        self._ports = None
        self._ports_n = -1

        # a unicast forwarding table
        # each entry is { destination: (destination, next_hop, weight) }
        self.unicast_forwarding_table = dict()
        
        # set the simulation environment
        self.set_env(network)

        # a database of metrics, keyed by replica name (one entry per replica)
        # (was a TinyDB table; plain dicts are O(1) for the equality lookups
        # this code does, and avoid TinyDB's per-scan closure overhead)
        self.service_RIB = dict()
        # forwarding utility of each RIB entry, keyed by replica: computed when
        # the entry is added or updated, so the FIB update does not re-evaluate
        # every entry for every announcement
        self.rib_utility = dict()

        # sent announcements: replica -> {neighbour: None} (insertion-ordered
        # set of neighbours the metric was sent to; a dict, not a set, so
        # iteration order is deterministic and matches insertion order)
        self.sent_table = dict()

        # Nov 2026 (T-13), with forward_to_tree_children_only: the neighbours
        # that a run without it would also have in sent_table[replica] (those
        # skipped as not tree children). For one replica that set is always
        # empty, all such neighbours but one, or all of them, so it is kept
        # as: no key = empty; a neighbour name = all but that one; True = all.
        # A replica with skipped neighbours also has a sent_table key (maybe
        # an empty dict), so the decisions below, which test whether a
        # replica was sent, behave exactly as with the flag off.
        self.skipped_sent = dict()

        # best replica info
        self.best_replica = None
        self.best_neighbour = None
        self.servicename = None
        self.best_utility = -0.0000000001   # just a tiny bit < 0

        # provenance of the best replica estimate:
        # the RIB values the utility was calculated from,
        # and the creation time of the update they came from (t_update)
        self.best_load = None
        self.best_delay = None
        self.best_update_time = None

        # service forwarding table -- the FIB
        # keeps neighbour for who to forward to
        # and the best replica and utility
        self.service_FIB = dict()

        # no of changes to the service_FIB
        self.service_fib_updates = 0

        # are we aggregating directly connected replicas
        self.aggregating_connected = False
        # aggregate of connected capacity
        self.connected_capacity = dict()
        # connected capacity initial total
        self.connected_capacity_total = { 'load': 0, 'no_of_flows': 0, 'slots': 0 }
 
        # declaring defaultdict
        # sets default value 'Key Not found' to absent keys
        defd = collections.defaultdict(lambda : None)

        # setup metrics list
        # name and better function
        self.metric_list =  [
            # specify the metric functions for 'load'
            # currently get them from the class variables
            { 'name': 'load',
              'same': Router.same_as_fn_load,
              'better': Router.better_than_fn_load

             },
            # specify the metric functions for 'delay'
            # currently get them from the class variables
            { 'name': 'delay',
              'same': Router.same_as_fn_delay,
              'better': Router.better_than_fn_delay
             }
        ]
    


    # sets env
    # checks if network is a Network or an simpy.Environment()
    def set_env(self, val):
        """ Set the env"""

        from Network import Network
        if isinstance(val, Network):
            # it is a Network
            self.env = val.env
        elif isinstance(val, simpy.Environment):
            # it is a Environment
            self.env = val
            self.network = None
        else:
            self.env = None


        # Create a structure to retrieve packet sent to this router - think consumer (this router) and producer (the one that sent the packet) pattern
        # e.g. https://simpy.readthedocs.io/en/latest/examples/process_communication.html
        self.packet_store = simpy.Store(self.env, capacity=1)

        # create packet sink
        self.sink = PacketSink(self.env)
        
    def start(self):
        """Start the Router.
        Calls back to the simpy env to start processing"""
        # "Register" the process
        self.env.process(self.run())

        if Verbose.level >= 2:
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

    # Nov 2026 (T-17): propdelay has no default (it was 1 ms); callers pass
    # the link's delay, defaults come from Network.default_link_delay
    def add_neighbour(self, neighbour_obj, propdelay, rate=LINKRATE):
        """Add a neighbour to this router"""
        neighbour = neighbour_obj.id()
            
        # check if the neighbour_obj already has a link
        if (self.contains_edge(neighbour_obj)):
            # no need to add a link

            if Verbose.level >= 2:
                print("LinkEnd Exists "  + str(self.id()) + " --> " + str(neighbour) + " No Duplicate " +  str(self.id()) + " --> " + str(neighbour) )

            return ("exists", self.outgoing_ports[neighbour_obj.id()])

        else:
            if Verbose.level >= 2:
                print("LinkEnd Add " + self.id() + " -> " + "neighbour " + str(neighbour) + " neighbour_obj " + str(neighbour_obj.id()) + " delay " + str(propdelay))

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

    # manage an incoming packet
    def manage_packet(self, packet_tuple):
        """ Manage a packet.  
        """
        (link_end, packet) = packet_tuple
        
        if packet.dst == self._routerid:
            # packet addressed to me
            # consume the packet

            # pass to the PacketSink which collects arrival information
            # may or may not be useful here
            # self.sink.put(packet)


            # a server load info packet
            if getattr(packet, 'type', False) == "ServerMetric":   #  packet.type == "ServerMetric":
                # we got a ServerMetric message which contains some server metrics
                self.incoming_server_metrics_packet(link_end, packet)

            else:
                # packet for me, but not a ServerMetric
                if Verbose.level >= 2:
                    print("{:.3f}: {:5s} PACKET_CONSUME {}.{}  ({:.3f}) consumed in {} after {:.3f}".format(self.env.now, self.id(), packet.src, packet.pkt_no, packet.time, self.id(), (self.env.now - packet.time)))



        else:
            # If the packet is not for us, forward to neighbours.
            # This is where the main servicecast algorithm will be implemented.
            # MR: if packet is data packet (ClientRequest)
            # MR:   STEP 8 forward to right link based on fw table
        

            if self.is_service(packet.dst):
                # this packet is for a Service name
                if getattr(packet, 'type', False) == "ClientRequest": #  packet.type == "ClientRequest":
                    self.client_request_packet(link_end, packet)
                    
            else:
                # normal forwarding
                self.normal_forwarding_packet(packet, link_end)



    # Is the destination address a service name:  e.g. §a
    def is_service(self, name):
        """Is the destination address a service name:  e.g. §a"""
        if name == None:
            return False
        elif name.startswith("§"):
            return True
        else:
            return False

    # We received a packet of type ServerMetric
    def incoming_server_metrics_packet(self, link_end, packet):
        """The process for a packet with type ServerMetric"""

        Router.recv_server_metric[packet.operation] = Router.recv_server_metric.get(packet.operation, 0) + 1

        if Verbose.level >= 0:
            print("{:.3f}: {:5s} RECV_PACKET  ServerMetric {} {}.{} ({:.3f}) [{}.{}] MT({:.3f}) managed in {} after {:.3f}".format(self.env.now, self.id(), packet.operation, packet.src, packet.pkt_no, packet.time, packet.replica, packet.id, packet.msg_time, self.id(), (self.env.now - packet.time)))

        # collect incoming metrics table [servicename, replicaID, metrics (delay, load), original messageID, creation timestamp, last update timestamp, link_received, calculated utility]
        servicename = packet.service
        replica = packet.replica
        msgID = packet.id
        creationTime = round(packet.msg_time, 6)
        metrics = packet.payload
        operation = ServerMetricMessageType.from_val(packet.operation)


        if Verbose.level >= 1:
            #print("{:.3f}: INCOMING_VALUES '{}' link_end: {} msgID: {} replica: {} time: {}  service: {} op: {} aggregate: {} metrics: {}".format(self.env.now, self.id(), str(link_end), msgID, replica, creationTime, servicename, operation, hasattr(packet,'aggregate'), metrics))
            print("{:.3f}: {:5s} INCOMING_VALUES [{}.{}] link_end: {} msgID: {} replica: {} time: {}  service: {} op: {} metrics: {}".format(self.env.now, self.id(), replica, msgID, str(link_end), msgID, replica, creationTime, servicename, operation, metrics))

        # add the delay of the last hop to the metrics
        metrics['delay'] +=  link_end.propagation_delay

        # and the cost of crossing the router it came from, unless that router
        # hosts the replica (as in the routing tables, see Routing)
        crossing = getattr(self.network, 'crossing_delay', None)
        if crossing:
            sender = link_end.src_node.id()
            if sender in crossing and replica not in link_end.src_node.outgoing_ports:
                metrics['delay'] += crossing[sender]


        # If the announcement has arrived on a link that is not the one
        # in the forwarding table, for the replica then Drop the message
        valid_route = self.arrived_from_unicast_route(replica, link_end)

        if Verbose.level >= 2:
            print("{:.3f}: {:5s} UNICAST_ROUTE for {} from {} --> {} ".format(self.env.now, self.id(), replica, link_end.src_node.id(), 'VALID' if valid_route else 'INVALID'))

        if not valid_route:
            Router.invalid_route_drops += 1
            Router.invalid_route_drops_op[packet.operation] = Router.invalid_route_drops_op.get(packet.operation, 0) + 1
            return

        # Only sent if propagation_time < anouncement_distance 
        # Where:
        #   Propagation_time = recv_time - send_time_of_original_packet
        
        # Announcement distance calculated at each router, each time capacity changes

        # Announcement Distance = 
        #   (replica_available_capacity / an estimate of system_available_capacity)
        #   * (load_utility - average load_utility + 1) * network diameter 
        #       Where:
        #       network diameter    = shortest path between the two most distant
        #                             nodes - longest shortest path
        #       load_utility        = contribution to the utility function of the 
        #                              load metric of that replica
        #                           = alpha * load (in current simulator)
        #       average load_utilty = Network object collects all 
        #                             load_utility values, and returns average

        # process the incoming packet
        if (operation == ServerMetricMessageType.Announce):
            # it's an announcement

            # Announcement distance prototype, commented out (Oct 2026). It is not
            # used yet: announcement_distance was computed for every announcement
            # but only printed (ANNOUNCEMENT_DISTANCE, verbose >= 2), and every
            # announcement is processed whatever its value. It was also costly:
            # average_normalised_load() loops over every server in the network, and
            # it ran for every announcement at every router, so its cost grew with
            # servers x messages. Profiled on CAIDA with 1000 servers and 50 clients
            # (60 s simulated, 35M load messages) it took about 21% of simulation
            # time. It also reads global state from the Network object (average
            # load, total capacity, diameter) that a real router would not have.
            # A real version needs a cheap per-message test using information the
            # router has locally; see "Announcement Radius" in doc/TODO.md.

            # # avoid least loaded going everywhere
            # # check the propagation_time

            # propagation_time = metrics['delay']
            # network_diameter = self.network.network_diameter()
            # normalised_load = self.network.get_normalised_load(replica)
            # average_normalised_load = self.network.average_normalised_load()
            # replica_available_capacity = self.network.get_replica_capacity(replica, 'slots')
            # system_available_capacity = self.network.get_total_replica_capacity('slots')

            # if system_available_capacity == 0:
            #     if Verbose.level >= 2:
            #         print("SYSTEM_AVAILABLE_CAPACITY " + "'" + str(self.id()) + "'" + " == 0 announcement_distance 0")
            #     announcement_distance = 0
            # else:
            #     announcement_distance =  (replica_available_capacity / system_available_capacity)  * (normalised_load - average_normalised_load + 1) * network_diameter 

            # if Verbose.level >= 2:
            #     # example:   381.000: POT   ANNOUNCEMENT_DISTANCE msgid: 24 replica: s4 msg time: 379.0  propagation_time: 2 load_utility(s4): 2.0 average_load_utility: 1.9 replica_capacity: 45 system_available_capacity: 232 announcement_distance: 1.494 
            #     print("{:.3f}: {:5s} ANNOUNCEMENT_DISTANCE msgid: {} replica: {} msg time: {}  propagation_time: {} normalised_load({}): {} average_normalised_load: {} replica_capacity: {} system_available_capacity: {} announcement_distance: {} ".format(self.env.now, self.id(), msgID, replica, creationTime, round(propagation_time, 6), replica, normalised_load, round(average_normalised_load, 6), replica_available_capacity, system_available_capacity,  round(announcement_distance, 3)))

            # do the announcement
            self.incoming_server_metrics_packet_announce(link_end, packet)
            
        elif (operation == ServerMetricMessageType.Withdraw):
            # it's a withdrawal
            self.incoming_server_metrics_packet_withdraw(link_end, packet)
        else:
            pass    



    # We received a packet of type ServerMetric Announcement
    def incoming_server_metrics_packet_announce(self, link_end, packet):
        # collect incoming metrics table [servicename, replicaID, metrics (delay, load), original messageID, creation timestamp, last update timestamp, link_received, calculated utility]
        servicename = packet.service
        replica = packet.replica
        msgID = packet.id
        creationTime = round(packet.msg_time, 6)
        metrics = packet.payload
        operation = ServerMetricMessageType.from_val(packet.operation)
        neighbour = link_end.src_node.id()

        # marked for later use
        marked  = None


        # did the ServerMetric come from a direct neighbour Host
        if self.is_neighbour(replica):
            if self.is_neighbour_host(replica):
                if Verbose.level >= 3:
                    print("server_metrics_packet_announce: IS_NEIGHBOUR_HOST: " + replica + " " + str(operation))

                # check if we are aggregating directly connected replicas
                if self.aggregating_connected:
                    # for directly connected neighbours we keep
                    # an aggregate of the connected capacity
                    # and expose it to the Network
                    self.expose_aggregated_connected_capacity(packet)

                    # now we consider to patch up the local values so
                    # the RIB has an aggregated entry
                    # in particular the replica to announce is not
                    # the connected server but this router
                    aggReplica = self.aggregate_name()

                    # TODO: complete this

                else:
                    # expose metrics for replica to the Network
                    self.expose_replica_connected_capacity(packet)

            else:
                if Verbose.level >= 3:
                    print("server_metrics_packet_announce: IS_NEIGHBOUR: " + replica + " " + str(operation))
                    
        else:
            if Verbose.level >= 3:
                print("server_metrics_packet_announce: NOT_NEIGHBOUR: " + replica + " " + str(operation))

                
            

        #
        ### never have more than 1 entry for each replica

        # store important data (including metrics) for later use in table
        # 'replica' is key for decision for deleting old data

        # If there is an existing entry in the service RIB
        existing = self.service_RIB.get(replica)

        if Verbose.level >= 1:
            print("{:.3f}: {:5s} METRIC_SEARCH_RESULTS link_end: {} replica: {} ==> {}".format(self.env.now, self.id(), link_end, replica, list(self.service_RIB.items())))

        # check results
        # If there is NO existing entry in the service RIB
        if existing is None:
            # nothing found - it must be new, so add it
            self.service_RIB[replica] = { 'replica': replica, 'neighbour': neighbour, 'link_end': str(link_end), 'msgID': msgID, 'servicename': servicename, 'creationTime': creationTime, 'load': metrics['load'], 'no_of_flows': int(metrics['no_of_flows']), 'delay': metrics['delay'], 'slots': metrics['slots']  }
            self.rib_utility[replica] = Utility.eval_forwarding_utility(self.service_RIB[replica])

            if Verbose.level >= 2:
                print ("{:.3f}: {:5s} ADD_METRIC metric from {}".format(self.env.now, self.id(), replica) )

        else:
            # something found in service_RIB

            # existing entry is newer than the incoming update
            if existing['creationTime'] > creationTime:
                # we found an entry with a newer time
                if Verbose.level >= 2:
                    print("{:.3f}: {:5s} METRIC_TOO_OLD link_end: {} replica: {} ==> {}".format(self.env.now, self.id(), link_end, replica, existing))

                return

            # Update the metrics in the existing RIB entry

            # replica stays the same
            # update other values
            existing.update({ 'neighbour': neighbour, 'link_end': str(link_end), 'msgID': msgID, 'servicename': servicename, 'creationTime': creationTime, 'load': metrics['load'], 'no_of_flows': metrics['no_of_flows'], 'delay': metrics['delay'], 'slots': metrics['slots'] })
            self.rib_utility[replica] = Utility.eval_forwarding_utility(existing)

            if Verbose.level >= 2:
                print("{:.3f}: {:5s} UPDATE_METRIC metric {} msgID: {} creationTime: {:.6f}  load: {} delay: {}".format(self.env.now, self.id(), replica, msgID, creationTime, metrics['load'], metrics['delay'] ))

            # mark this replica, if in sent_table (a key is only there while
            # the replica is sent to someone, counting skipped tree non-children)
            if replica in self.sent_table:
                # it is in the sent_table
                marked = existing
                if Verbose.level >= 2:
                    print("{:.3f}: {:5s} MARK_METRIC {}".format(self.env.now, self.id(), replica))

                
        # STEP 5,11 forward to appropriate links based on routing information base (fix code below)
        # Now we need to decide which messages go on which links
        # For each entry in the RIB
        #   compare with all the others
        # if any of the metrics is better than that metric in all the other entries
        # announce on all the links that it wasn't received from


        if Verbose.level >= 1:
            self.print_metric_table()

        # ---- Announcement Decision Phase ----

        #  decide the PBR entries to announce
        decide_pbr = self.decide_announcements(list(self.service_RIB.values()))

        if Verbose.level >= 1:
            self.print_announce_info(decide_pbr)

        # Work out what to send from the PBR and the sent_table

        # First evaluate the metrics from the sent_table

        # sent is the list of RIB metrics for replicas we have announced
        sent_set = [self.service_RIB[r] for r in self.sent_table if r in self.service_RIB]

        if sent_set:
            if Verbose.level >= 3:
                print("\t\t >>> sent_set " + str(len(sent_set)) + " " + str(sent_set))

        # announce set are those in decide_pbr and not in sent
        # plus the marked one, if it is in the decide_pbr

        marked_set = [marked] if marked in decide_pbr else []

        if marked_set:
            if Verbose.level >= 3:
                print("\t\t >>> marked_set " + str(len(marked_set)) + " " + str(marked_set))

        sent_replicas = set(self.sent_table.keys()) & self.service_RIB.keys()
        decide_replicas = set(d['replica'] for d in decide_pbr)
        announce_set = [m for m in decide_pbr if m['replica'] not in sent_replicas] + marked_set


        # use all of them and label announce entries to have message type Announce
        announce = list(zip(announce_set, itertools.repeat(ServerMetricMessageType.Announce)))

        if announce:
            if Verbose.level >= 3:
                print("\t\t >>> announce_set " + str(len(announce)) + " " + str(announce))


        # withdraw set are those in sent_table minus those in decide_pbr
        withdraw_set = [s for s in sent_set if s['replica'] not in decide_replicas]

        # label withdraw_set entries to have message type Withdraw
        withdraw = list(zip(withdraw_set, itertools.repeat(ServerMetricMessageType.Withdraw)))

        if withdraw:
            if Verbose.level >= 3:
                print("\t\t>>> withdraw_set " + str(len(withdraw)) + " " + str(withdraw))


        # if there is a metric in the marked_set
        # we need to clear it from the sent_table
        if marked_set != []:
            # delete from sent_table for marked
            self.clear_sent_table(marked_set[0]['replica'])


        #  announce the metrics if announce or withdraw has entries
            

        if announce or withdraw:
            self.announce_metrics(announce + withdraw)


        if Verbose.level >= 2:
            self.print_sent_table()


        # STEP 6,12 check if fw table needs changing. If yes, change it. Choose the one with best utility function.
        # and update the FIB

        self.choose_best_forwarding_replica_update_fib()

        

    # We received a packet of type ServerMetric Withdraw
    def incoming_server_metrics_packet_withdraw(self, link_end, packet):
        # collect incoming metrics table [servicename, replicaID, metrics (delay, load), original messageID, creation timestamp, last update timestamp, link_received, calculated utility]
        servicename = packet.service
        replica = packet.replica
        msgID = packet.id
        creationTime = round(packet.msg_time, 6)
        metrics = packet.payload
        operation = ServerMetricMessageType.from_val(packet.operation)

        # did the ServerMetric come from a direct neighbour
        if self.is_neighbour(replica):
            if Verbose.level >= 2:
                print("{:.3f}: {:5s} SERVER_METRICS_PACKET_WITHDRAW: IS_NEIGHBOUR: ".format(self.env.now, self.id(), replica))

            # for neighbours we keep an aggregate of the connected capacity
            self.withdraw_connected_capacity(packet)
        else:
            if Verbose.level >= 2:
                print("{:.3f}: {:5s} SERVER_METRICS_PACKET_WITHDRAW: NOT_NEIGHBOUR: ".format(self.env.now, self.id(), replica))
            

        # withdrawal might have to go to neighbours too
        # should be in sent_table

        # If there is an existing entry in the service RIB
        candidate = self.service_RIB.get(replica)

        # check results
        # If there is NO existing entry in the service RIB
        if candidate is None:
            # nothing found - nothing to do
            pass
        else:
            if Verbose.level >= 2:
                print("{:.3f}: {:5s} WITHDRAW_SEARCH_RESULTS link_end: {} replica: {} ==> {}".format(self.env.now, self.id(), link_end, replica, candidate))

            # T-12: can removing this entry free another one? Checked before
            # the sent table and RIB entry are cleared below. Only if:
            #   - the withdrawn entry was announced (sent_table key). An
            #     unannounced one was beaten by another entry, which also
            #     beats everything it beat, so it frees nothing (5 Nov: skips
            #     about 40% of the checks on Cogentco). The exception: a
            #     router with one router neighbour has no key for an entry
            #     from that neighbour (nobody to send it to), and if a server
            #     is attached such an entry can free the server's, which
            #     then goes to the neighbour. Hardly possible (the remote
            #     entry has a core link more), and cheap there (small RIB),
            #     so checked anyway;
            #   - some other entry is not announced (sent_table keys are the
            #     announced replicas, a subset of the RIB's).
            recheck = (Router.announce_freed_after_withdraw and
                       (replica in self.sent_table or self._stub_with_server()) and
                       len(self.sent_table) - (replica in self.sent_table) < len(self.service_RIB) - 1)

            # now check the sent table: neighbours we announced this replica to
            sent_neighbours = self.sent_table.get(replica, {})

            # how many neighbours did we find in the sent_table
            no_found_in_sent_table = len(sent_neighbours)

            #self.print_sent_table()


            # withdrawals not sent to skipped tree non-children (T-13)
            if replica in self.skipped_sent:
                self.count_skipped_withdraws(replica, link_end.src_node.id())

            if no_found_in_sent_table == 0:
                # nothing in sent_table
                # so no withdrawals sent on
                if Verbose.level >= 2:
                    print("{:.3f}: {:5s} SENT_TABLE_NOTHING in sent_table: for {}".format(self.env.now, self.id(), replica))

                # drop an empty key left by skipped tree non-children
                if replica in self.sent_table:
                    self.clear_sent_table(replica)

                # now delete the candidate metric from the RIB
                self.delete_rib_entry(candidate)

                if Verbose.level >= 2:
                    self.print_metric_table()

            else:
                # this metric is in the sent table
                if Verbose.level >= 2:
                    print("{:.3f}: {:5s} SENT_TABLE_FOUND {} in sent_table:  metric [{}] need to withdraw".format(self.env.now,  self.id(), no_found_in_sent_table, replica))


                # do we need any withdrawal announcements
                for neighbour in sent_neighbours:

                    # check link_end
                    if link_end.src_node.id() == neighbour:
                        # don't send to where it came from
                        if Verbose.level >= 2:
                            print("{:.3f}: {:5s} WITHDRAW_PACKET {}.{} dont send back to {} ".format(self.env.now, self.id(), packet.src, packet.pkt_no, link_end.src_node.id()))
                        pass

                    else:
                        # create a new packet
                        new_packet = self.metric_to_packet(candidate, ServerMetricMessageType.Withdraw, neighbour)

                        self.pkt_no += 1

                        # forward the packet
                        if Verbose.level >= 2:
                            print("{:.3f}: {:5s} WITHDRAW_FORWARD {} to {}".format(self.env.now, self.id(), candidate['replica'], neighbour))

                        # send to relevant SwitchPort
                        self.send_packet_to_neighbour(new_packet, neighbour)


                # whatever the previous decision
                # clear sent_table for this metric
                self.clear_sent_table(replica)

                #self.print_sent_table()

                # now delete the candidate metric from the RIB
                self.delete_rib_entry(candidate)

                if Verbose.level >= 2:
                    self.print_metric_table()


            # check if withdrawn replica is best replica
            if replica == self.best_replica:
                if Verbose.level >= 2:
                    print("{:.3f}: {:5s} WITHDRAW_BEST_REPLICA_START replica: {}".format(self.env.now, self.id(), replica))

                self.best_replica = None
                self.best_utility = -0.0000000001
                self.best_load = None
                self.best_delay = None
                self.best_update_time = None

                # now we need to select the best replica
                # as we splatted the previous one
                # due to the withdraw
                self.choose_best_forwarding_replica_update_fib()
                
                if Verbose.level >= 2:
                    print("{:.3f}: {:5s} WITHDRAW_BEST_REPLICA_END replica: {}".format(self.env.now, self.id(), replica))

            # T-12: announce the entries the withdrawn one was dominating
            if recheck:
                self.announce_freed_entries(candidate)

            if Verbose.level >= 2:
                print("{:.3f}: {:5s} WITHDRAW_END".format(self.env.now, self.id()))
        

    # Nov 2026 (T-12): after a withdrawal, announce the entries that are no
    # longer dominated. The original code only deleted the withdrawn entry
    # and passed the withdrawal on, so an entry that only the withdrawn one
    # was beating stayed unannounced until the next announcement for any
    # replica reached this router (and made it decide again).
    #
    # The result is that of deciding again over the remaining entries and
    # announcing what is decided but not yet announced (removing an entry
    # cannot make another one dominated, so there is nothing to withdraw).
    # Other comparisons than the default decide again in full.
    #
    # With the default comparisons dominance is transitive, so only the
    # unannounced entries that the withdrawn one was at least as good as
    # (the candidates) can be freed. If there is one, _decide_skyline (sort
    # and scan, the same rule as a full decision) runs over the remaining
    # RIB and the decided candidates are announced. (5 Nov: replaced a check
    # of each candidate against every other entry, k x n pairs, plus a copy
    # of the RIB on every withdrawal; same messages.) Deciding over only the
    # announced entries plus the candidates is not enough: an entry with no
    # sent_table key (nobody to send it to) can still beat a candidate.
    # tests/test_announce_freed.py checks this against a full decision.
    #
    # withdrawn: the RIB entry just removed.
    def announce_freed_entries(self, withdrawn):
        Announce, Withdraw = ServerMetricMessageType.Announce, ServerMetricMessageType.Withdraw
        sent = self.sent_table
        if not self.uses_default_comparisons():
            decided = self.decide_announcements(list(self.service_RIB.values()))
            decided_replicas = set(d['replica'] for d in decided)
            out = [(e, Announce) for e in decided if e['replica'] not in sent]
            out += [(self.service_RIB[r], Withdraw) for r in list(sent)
                    if r in self.service_RIB and r not in decided_replicas]
        else:
            wd, wl = withdrawn['delay'], withdrawn['load']
            rib = list(self.service_RIB.values())
            out = []
            for e in rib:
                if e['replica'] not in sent and wd <= e['delay'] and wl <= e['load']:
                    out = [(d, Announce) for d in self._decide_skyline(rib)
                           if d['replica'] not in sent and wd <= d['delay'] and wl <= d['load']]
                    break

        if Verbose.level >= 2:
            print("{:.3f}: {:5s} ANNOUNCE_FREED after withdrawal of {}: {}".format(
                self.env.now, self.id(), withdrawn['replica'], [(e['replica'], str(t)) for e, t in out]))
        if out:
            self.announce_metrics(out)

    # the replica capacity only and expose to Network
    def expose_replica_connected_capacity(self, packet):
        replica = packet.replica
        creationTime = round(packet.msg_time, 6)
        metrics = packet.payload

        value = {'creationTime': creationTime, 'load': metrics['load'], 'no_of_flows': int(metrics['no_of_flows']), 'slots': int(metrics['slots']), 'capacity': metrics['slots'] -  metrics['used_slots']}

        self.connected_capacity[replica] = value

        self.network.update_replica_capacity(replica, value)

    # aggregate the connected capacity and expose to Network
    def expose_aggregated_connected_capacity(self, packet):
        replica = packet.replica
        creationTime = round(packet.msg_time, 6)
        metrics = packet.payload
        
        self.connected_capacity[replica] = {'creationTime': creationTime, 'load': metrics['load'], 'no_of_flows': int(metrics['no_of_flows']), 'slots': int(metrics['slots']), 'capacity': metrics['slots'] -  metrics['used_slots']}

        # calculate total
        self.connected_capacity_total = { 'load': 0, 'no_of_flows': 0, 'slots': 0, 'capacity': 0 }

        for key in self.connected_capacity:
            entry = self.connected_capacity[key]

            if Verbose.level >= 2:
                print("announce_aggregated_connected_capacity: server " + key + " entry " + str(entry))
            
            self.connected_capacity_total["load"] += entry["load"]
            self.connected_capacity_total["no_of_flows"] += entry["no_of_flows"]
            self.connected_capacity_total["slots"] += entry["slots"]
            self.connected_capacity_total["capacity"] += entry["capacity"]

        if Verbose.level >= 2:
            print ("{:.3f}: CONNECTED_CAPACITY {} 'load': {}, 'no_of_flows': {}, 'slots': {}, 'capacity': {}".format(self.env.now, self.id(),  self.connected_capacity_total["load"],  self.connected_capacity_total["no_of_flows"],  self.connected_capacity_total["slots"], self.connected_capacity_total["capacity"]   ))

        self.network.update_replica_capacity(self.id(), self.connected_capacity_total)
                                            
    # aggregate the connected capacity on an announcement
    def withdraw_connected_capacity(self, packet):
        pass

    # Announce the entries: send each (metric, Announce/Withdraw) in
    # announcements on every port to a router, except the one it came from
    # and, with forward_to_tree_children_only, ports to routers whose next
    # hop to the replica is not this router.
    def announce_metrics(self, announcements):
        Announce, Withdraw = ServerMetricMessageType.Announce, ServerMetricMessageType.Withdraw
        debug = Verbose.level >= 2
        tree_children_only = Router.forward_to_tree_children_only
        me = self._routerid
        ports = self._ports_by_neighbour()

        for metric_to_send, msg_type in announcements:
            replica = metric_to_send['replica']
            came_from = metric_to_send['neighbour']
            # T-13: skipped tree non-children, for the not-sent counts
            skipped_state = self.skipped_sent.get(replica)
            n_skipped = 0
            came_from_skipped = False

            if debug:
                if self.is_neighbour_host(replica):
                    print("{:.3f}: {:5s} ANNOUNCE directly connected {}".format(self.env.now, self.id(), replica))
                else:
                    print("{:.3f}: {:5s} ANNOUNCE NOT directly connected {}".format(self.env.now, self.id(), replica))

            # send to neighbours
            for neighbour, port, dst_node, is_host in ports:
                if is_host:
                    # don't send to any connected Hosts
                    if debug:
                        print("{:.3f}: {:5s} NOT_TO_HOST {} - metric {}".format(self.env.now, self.id(), dst_node, replica))
                    continue

                if came_from == neighbour:
                    # don't send to where it came from
                    if debug:
                        print("{:.3f}: {:5s} NO_RETURN to {} - metric {}".format(self.env.now, self.id(), neighbour, replica))
                    if tree_children_only and dst_node.unicast_forwarding_table.get(replica) != me:
                        came_from_skipped = True
                    continue

                if tree_children_only and dst_node.unicast_forwarding_table.get(replica) != me:
                    # neighbour's next hop toward this replica isn't us: it would drop this
                    # (reads the neighbour's forwarding table directly: a simulation shortcut)
                    if debug:
                        print("{:.3f}: {:5s} NOT_TREE_CHILD {} - metric {}".format(self.env.now, self.id(), neighbour, replica))
                    # T-13: would a run with the flag off send this? It
                    # follows the same sent-table rules as below.
                    n_skipped += 1
                    in_sent = skipped_state is True or (skipped_state is not None and neighbour != skipped_state)
                    if msg_type == Announce:
                        if not in_sent:
                            Router.tree_skipped['A'] += 1
                    elif in_sent:
                        Router.tree_skipped['W'] += 1
                    continue

                # a candidate for forwarding
                if msg_type == Announce:
                    if neighbour in self.sent_table.get(replica, ()):
                        # this is in the sent table, so no need to send
                        if debug:
                            print("{:.3f}: {:5s} ALREADY_IN_SENT_TABLE neighbour {} metric {} msgID {}".format(self.env.now, self.id(), neighbour, replica, metric_to_send['msgID']))
                        continue

                    new_packet = self.metric_to_packet(metric_to_send, msg_type, neighbour)
                    self.pkt_no += 1
                    if Verbose.level >= 1:
                        print("{:.3f}: {:5s} FORWARD_METRIC to {} msg {}".format(self.env.now, self.id(), dst_node.id(), metric_to_send))
                    port.put(new_packet)
                    self.update_sent_table(metric_to_send, neighbour)

                elif msg_type == Withdraw:
                    if neighbour in self.sent_table.get(replica, ()):
                        # this is in the sent table, so send the withdraw
                        new_packet = self.metric_to_packet(metric_to_send, msg_type, neighbour)
                        self.pkt_no += 1
                        if debug:
                            print("{:.3f}: {:5s} FORWARD_WITHDRAW to {} msg {}".format(self.env.now, self.id(), dst_node.id(), metric_to_send))
                        port.put(new_packet)
                    elif debug:
                        # not in sent_table, so no need to send the withdraw
                        print("{:.3f}: {:5s} NOT_IN_SENT_TABLE neighbour {} metric {} msgID {}".format(self.env.now, self.id(), neighbour, replica, metric_to_send['msgID']))

                else:
                    print("UNKNOWN ServerMetricMessageType " + msg_type)

            # T-13: after an Announce, the skipped neighbours (all but came_from)
            # are in the flag-off sent table too
            if n_skipped and msg_type == Announce:
                if skipped_state is None:
                    skipped_state = came_from if came_from_skipped else True
                elif skipped_state is not True and skipped_state != came_from:
                    skipped_state = True
                self.skipped_sent[replica] = skipped_state
                self.sent_table.setdefault(replica, {})

            # if the msg_type is Withdraw, clear sent_table
            if msg_type == Withdraw:
                self.clear_sent_table(replica)

        if debug:
            print("{:.3f}: {:5s} ANNOUNCE_END".format(self.env.now, self.id()))

    # (neighbour, port, neighbour node, is the neighbour a Host) for each
    # outgoing port, in outgoing_ports order, so that announce_metrics does
    # not look these up for every port on every update. Built on first use
    # and again if ports are added.
    def _ports_by_neighbour(self):
        if self._ports_n != len(self.outgoing_ports):
            self._ports = [(neighbour, port, port.out.dst_node, isinstance(port.out.dst_node, Host))
                           for neighbour, port in self.outgoing_ports.items()]
            self._ports_n = len(self.outgoing_ports)
            self._is_stub_with_server = (sum(1 for p in self._ports if not p[3]) == 1 and
                                         any(isinstance(p[2], Server) for p in self._ports))
        return self._ports

    # one router neighbour and a server attached (see the T-12 pre-check in
    # incoming_server_metrics_packet_withdraw), from the cache above
    def _stub_with_server(self):
        self._ports_by_neighbour()
        return self._is_stub_with_server

    # Create a new packet from a metric
    def metric_to_packet(self, metric_to_send, msg_type, neighbour):
        new_packet = Packet(self.env.now, 3, metric_to_send['msgID'], self.id(), dst=neighbour)
        new_packet.type = "ServerMetric"
        new_packet.operation = msg_type.to_val()
        new_packet.service =  metric_to_send['servicename']
        new_packet.replica = metric_to_send['replica']
        new_packet.pkt_no =  self.pkt_no
        new_packet.msg_time = metric_to_send['creationTime']
        
        if self.aggregating_connected:
            if metric_to_send.get('aggregate', None):
                new_packet.aggregate = True

        new_packet.payload = { 'load': metric_to_send['load'], 'no_of_flows': metric_to_send['no_of_flows'], 'delay': metric_to_send['delay'], 'slots': metric_to_send['slots'] }

        return new_packet


    # If the announcement has arrived on a link that is not the one
    # in the forwarding table, for the replica then Drop the message
    def arrived_from_unicast_route(self, replica, link_end):
        # unicast_forwarding_table maps destination -> next hop:  's1': 'b'

        if replica in self.unicast_forwarding_table:
            # the next hop for the servicename
            link = self.unicast_forwarding_table[replica]

            if link_end.src_node.id() == link:
                return True
            else:
                return False

        else:
            # not in unicast_forwarding_table
            return False


    # is the metric arg2 is better than arg1
    def metric_is_better(self, arg1, arg2, same_fn, better_fn):
        if same_fn(arg1, arg2):
            # arg2 is same as arg1
            return Compare.Same
        elif better_fn(arg2, arg1):
            # arg2 is better than arg1
            return Compare.Better
        else:
            # arg2 is worse than arg1
            return Compare.Worse
         
    # is entry j better than entry i, in all metrics
    # Same if every metric is the same, Better if every metric is better or
    # the same, otherwise Worse. Single pass that stops at the first worse
    # metric; gives the same result as the per-metric version below.
    def is_better_in_any_metrics(self, j, i):
        if Verbose.level >= 4:
            # keep the per-metric debug output
            return self.is_better_in_any_metrics_per_metric(j, i)

        all_same = True
        for m_dict in self.metric_list:
            m = m_dict['name']
            if m_dict['same'](i[m], j[m]):
                continue
            all_same = False
            if not m_dict['better'](j[m], i[m]):
                return Compare.Worse

        return Compare.Same if all_same else Compare.Better

    # is entry j better than entry i, in all metrics -- evaluates every
    # metric and prints each result at Verbose.level >= 4
    def is_better_in_any_metrics_per_metric(self, j, i):
        # results list for better-ness
        better = [False for m in self.metric_list]

        for index_m, m_dict in enumerate(self.metric_list):
            # m_dict has the name of the metric and the better-ness function
            m = m_dict['name']
            same_fn = m_dict['same']
            better_fn = m_dict['better']
            
            # print("metric = " + m)

            # skip through each metric by selecting metric m of i and metric m of j
            # we want j[m] to be better than i[m]
            better[index_m] = self.metric_is_better(i[m], j[m], same_fn, better_fn)

            
            if Verbose.level >= 4:
                print("metric_is_better = " + str(better[index_m]) + " for " + "i["+ m + "] and j[" + m + "]")

        # return value
        if all(v == Compare.Same for v in better):            # ALL the Same
            return Compare.Same

        elif all((v == Compare.Better or v == Compare.Same) for v in better): # ALL Better or Same
            return Compare.Better

        else:
            return Compare.Worse


    # Decide the entries to announce, given a set of entries.
    #
    # An entry is announced unless another entry is Better (the Same or
    # better in every metric, and not the Same in all), and among entries
    # that are the Same in every metric only the last one in the list is
    # announced. Entries come back in their original order.
    #
    # Two implementations give the same result:
    #   - _decide_skyline: a sort and scan, used with the default comparisons
    #     (metrics load and delay, exact equality, lower is better);
    #   - _decide_pairwise: compares every pair of entries, for any other
    #     comparison functions. Needed for an equivalence margin ("the same
    #     within x"), which is not transitive, so a sort and scan would not
    #     give the pairwise result.
    # tests/test_decide_announcements.py checks that the two agree.
    def decide_announcements(self, entries):
        if self.uses_default_comparisons():
            return self._decide_skyline(entries)
        return self._decide_pairwise(entries)

    # metrics load and delay, compared with same_as and less_than
    def uses_default_comparisons(self):
        return ([m['name'] for m in self.metric_list] == ['load', 'delay'] and
                all(m['same'] is same_as and m['better'] is less_than for m in self.metric_list))

    # Sort the entries by (delay, load). An entry is beaten exactly when an
    # entry with a lower delay has a load no higher, or an entry with the
    # same delay has a lower load. So one pass in that order, keeping the
    # lowest load seen at lower delays, finds the entries to announce; of
    # entries with the same delay and load, the last in the list is kept.
    def _decide_skyline(self, entries):
        n = len(entries)
        if n <= 1:
            return list(entries)
        keys = [(e['delay'], e['load']) for e in entries]
        order = sorted(range(n), key=keys.__getitem__)
        keep = [False] * n
        best_load_before = None   # lowest load among entries with a strictly lower delay
        k = 0
        while k < n:
            # one group of entries with the same delay, sorted by load
            delay = keys[order[k]][0]
            g = k
            while g < n and keys[order[g]][0] == delay:
                g += 1
            group_min = keys[order[k]][1]
            idx = k
            while idx < g:
                load = keys[order[idx]][1]
                # the run of entries with this same (delay, load)
                r = idx
                last = order[idx]
                while r < g and keys[order[r]][1] == load:
                    if order[r] > last:
                        last = order[r]
                    r += 1
                dominated = (best_load_before is not None and best_load_before <= load) or group_min < load
                if not dominated:
                    keep[last] = True
                idx = r
            if best_load_before is None or group_min < best_load_before:
                best_load_before = group_min
            k = g
        if Verbose.level >= 3:
            print("announce: {}".format(keep))
        return [e for e, kp in zip(entries, keep) if kp]

    def _decide_pairwise(self, entries):
        n = len(entries)
        if n <= 1:
            return list(entries)
        mets = [(m['name'], m['same'], m['better']) for m in self.metric_list]
        vals = [[e[name] for name, _, _ in mets] for e in entries]
        fns = [(same, better) for _, same, better in mets]
        debug = Verbose.level >= 3
        announce = [False] * n
        for i in range(n):
            announce[i] = True
            vi = vals[i]
            for j in range(n):
                if j == i:
                    continue
                vj = vals[j]
                # Same / Better / Worse of j against i, as is_better_in_any_metrics
                all_same = True
                worse = False
                for k, (same, better) in enumerate(fns):
                    if same(vi[k], vj[k]):
                        continue
                    all_same = False
                    if not better(vj[k], vi[k]):
                        worse = True
                        break
                if worse:
                    # we keep i
                    if debug:
                        print("Compare.Worse: j_{} is not better than i_{}: {} {}".format(j, i, self.displayMetrics('j: ', entries[j]), self.displayMetrics('i: ', entries[i])))
                    continue
                if all_same:
                    # so we don't need j
                    announce[j] = False
                    if debug:
                        print("Compare.Same: j_{} is same as i_{}: {} {}".format(j, i, self.displayMetrics('j: ', entries[j]), self.displayMetrics('i: ', entries[i])))
                else:
                    # j is better than i, so we don't need i
                    announce[i] = False
                    if debug:
                        print("Compare.Better: j_{} is better than i_{}: {} {}".format(j, i, self.displayMetrics('j: ', entries[j]), self.displayMetrics('i: ', entries[i])))
                    break
        if debug:
            print("announce: {}".format(announce))
        return [e for e, a in zip(entries, announce) if a]

    # is the newly arrived metrics worse 
    def check_metrics_worse(self, metrics, doc):
        """Returns (replica, count in sent_table)"""
        # is it better or worse
        better_j_i = self.is_better_in_any_metrics(metrics, doc)

        if better_j_i == Compare.Worse:
            # it looks worse

            if Verbose.level >= 2:
                print("{:.3f}: check_worse_metrics {} metric [{}] --> {}".format(self.env.now, str(better_j_i), doc['replica'], doc))

            # now check the sent table
            # how many neighbours did we announce this replica to
            no_found_in_sent_table = len(self.sent_table.get(doc['replica'], ()))

            if no_found_in_sent_table > 0:
                # this metric is in the sent table
                if Verbose.level >= 2:
                    print("{:.3f}: is in sent_table: metric [{}] need to resend".format(self.env.now, doc['replica']))

            # return the replica of the metric (so it can be found later)
            # and how many times it was found
            return (doc['replica'], no_found_in_sent_table)
        else:
            # Nothing found
            return (None, 0)

        # END of check if new metrics are worse than found result

    # display metrics
    def displayMetrics(self, label, metric):
        return "{} replica: {} load: {} delay: {}".format(label, metric['replica'], metric['load'], metric['delay'])

    def displayMetrics2(self, label, metric):
        return "{} replica: {} load: {} delay: {}".format(label, metric['replica'], metric['load'], metric['delay'])

    #  Check if fw table needs changing
    # and update FIB
    def choose_best_forwarding_replica_update_fib(self):
        # pass in all RIB entries
        self._choose_best_forwarding_replica_update_fib_with_entries(list(self.service_RIB.values()))


    # Check if fw table needs changing and update FIB
    # by checking passed in RIB entries
    def _choose_best_forwarding_replica_update_fib_with_entries(self, entries):
        # best_utility=Infinity
        # best replica=1
        # for all replicas i
        #   calculate Utility
        #   if utility(i) < best_utility
        #     best_replica=i
        #     best_utility=utility(i)
        # point fw entry to best replica's announced link end

        if Verbose.level >= 2:
            print ("{:.3f}: {:5s} CHOOSE_BEST_FORWARDING_REPLICA: current best {} utility {}".format(self.env.now, self.id(), self.best_replica, self.best_utility))

        old_best_replica = self.best_replica
        old_best_utility = self.best_utility

        this_best_replica = None
        this_best_neighbour = None
        this_best_utility = -1
        this_servicename = None
        this_best_entry = None

        # create a list of utility values
        utility = [-1 for e in entries]


        # skip through all the entries
        # in order to find the one with the best utility

        for entry_no, entry in enumerate(entries):
            # run the utility pipeline: raw metrics -> metric utilities -> user utility
            # the RIB entry is the dict of raw metrics -- extra keys are ignored
            utility_i = self.rib_utility.get(entry['replica'])
            if utility_i is None:
                # not stored yet, or cleared because the delay scale changed
                utility_i = Utility.eval_forwarding_utility(entry)
                self.rib_utility[entry['replica']] = utility_i

            # keep the calculated utility into the utility table
            utility[entry_no] = utility_i

            if Verbose.level >= 2:
                # First we map the actual delay into a normalised_delay
                # which is a value between 0 and 1
                normalised_delay = self.network.get_normalised_delay(entry['delay'])


                print ("\t\t{:2d}. replica: {} neighbour: {} utility_i: {} alpha: {} normalised_load: {} delay: {} normalised_delay: {} ".format(entry_no, entry['replica'], entry['neighbour'], utility_i, Utility.alpha, entry['load'], entry['delay'], normalised_delay))



            # is utility of this entry > current best utility 
            if (utility_i > this_best_utility):
                # update best replica data
                this_best_replica = entry['replica']
                this_best_neighbour = entry['neighbour']
                this_servicename = entry['servicename']
                this_best_utility = utility_i
                this_best_entry = entry

            else:
                if Verbose.level >= 3:
                    print("utility_i < this_best_utility " + str(utility_i) + " < " + str(this_best_utility) + " for " + entry['replica'])
                
            # patch up the utility of the old_best_replica
            # with the current utility value
            if entry['replica'] == old_best_replica:
                # overwrite the previous value of utility
                # with the new one calculated from the metric table
                old_best_utility = utility_i

                if Verbose.level >= 3:
                    print("patched up utility value for " + old_best_replica + " to " + str(old_best_utility))

        if Verbose.level >= 2:
            self.print_utility_info(entries, utility)


        # if the option to remove FIB entries when all replicas have zero utility has been set then remove the existing FIB entry if all replicas in the RIB have zero utility
        if self.remove_fib_entry_when_all_utilities_zero is True:
            # check if all utilities are zero
            if this_best_utility == 0:
                # all replicas have utility 0 hence the FIB entry should be removed
                # grab the service name from the best FIB entry. Note that this is a bit of a hack. The Router class has not been fully written for multiple service names in the FIB/RIB. We need to fix this in a future iteration.
                service_name = this_best_entry['servicename']
                previous_fib_entry = self.service_FIB.get(service_name)
                if previous_fib_entry is not None:
                    # there was a previous FIB entry. We are removing it so we need to increment the FIB update counter
                    self.service_fib_updates += 1
                # remove the FIB entry
                self.service_FIB[service_name] = None
                Router.count_fib_action(self.id(), 'REMOVED')
                if Verbose.level >= 1:
                    print("{:.3f}: {:5s} REMOVED_BEST_REPLICA_FROM_FIB {}".format(self.env.now, self.id(), self.best_replica))   
                self.best_replica = None
                self.best_utility = -0.0000000001
                self.best_load = None
                self.best_delay = None
                self.best_update_time = None
                # do no further processing
                return

        # 5. Choose best replica for the forwarding plane/
        #
        # Currently send to the one target held in Service Forwarding Table.
        # We may want to dampen the changes in the Service Forwarding Table
        # so that we don't scatter requests to multiple servers.
        # Avoids flapping.  The damping may be based on a value threshold or a time window.
        
        # we check if the difference the new best utility and
        # the latest utility at the old best one
        # to make sure it is big enough
        diff = self.calculate_utility_difference(this_best_utility, old_best_utility)

        # check how much of a change in there is
        if (old_best_replica != this_best_replica):
            # different replicas

            if (diff == 0 and old_best_replica is not None):
                # no change, do nothing
                # (when there is no prior best replica there is nothing to
                #  damp against, so always adopt the new replica below)

                if Verbose.level >= 1:
                    print("{:.3f}: {:5s} CHOOSE_BEST_REPLICA: U_old({}, {}) U_new({}, {}) diff({} {} {}) {} {} to {}".format(self.env.now, self.id(), old_best_utility, old_best_replica, this_best_utility, this_best_replica, "", "0", "", " do not change ", old_best_replica, this_best_replica ))

            elif (diff < Router.fib_utility_update_threshold and old_best_replica is not None):
                # Compare diff to Router.fib_utility_update_threshold
                # change is too small, do nothing
                
                if Verbose.level >= 1:
                    print("{:.3f}:{:5s} CHOOSE_BEST_REPLICA: U_old({}, {}) U_new({}, {}) diff({} {} {}) {} {} to {}".format(self.env.now, self.id(), old_best_utility, old_best_replica, this_best_utility, this_best_replica, diff, "<", Router.fib_utility_update_threshold, " do not change ", old_best_replica, this_best_replica ))

            else:
                # diff > Router.fib_utility_update_threshold
                # change replica

                if Verbose.level >= 1:
                    print("{:.3f}: {:5s} CHOOSE_BEST_REPLICA: U_old({}, {}) U_new({}, {}) diff({} {} {}) {} {} to {}".format(self.env.now, self.id(), old_best_utility, old_best_replica, this_best_utility, this_best_replica, diff, ">", Router.fib_utility_update_threshold, " change ", old_best_replica, this_best_replica ))

                self.best_replica = this_best_replica
                self.best_neighbour = this_best_neighbour
                self.servicename = this_servicename
                self.best_utility = this_best_utility
                self.best_load = this_best_entry['load']
                self.best_delay = this_best_entry['delay']
                self.best_update_time = this_best_entry['creationTime']

                # update count
                self.service_fib_updates += 1

        else:
            # Same replica: keep it, and always refresh the tracked values
            # (utility/load/delay/update_time) from the newest RIB entry, so
            # SEL_UTIL_EST / t_update always reflect the most recent update.
            # This cannot affect the keep/switch damping: that comparison uses
            # patched-up fresh values on both sides (see above).
            # this_best_entry can be None (no usable RIB entries right now);
            # then there is nothing newer to record.

            if this_best_entry is not None:
                self.best_utility = this_best_utility
                self.best_load = this_best_entry['load']
                self.best_delay = this_best_entry['delay']
                self.best_update_time = this_best_entry['creationTime']

            if Verbose.level >= 1:
                if diff == 0:
                    diff_text, comparator, threshold_text = "", "0", ""
                elif diff < Router.fib_utility_update_threshold:
                    diff_text, comparator, threshold_text = diff, "<", Router.fib_utility_update_threshold
                else:
                    diff_text, comparator, threshold_text = diff, ">", Router.fib_utility_update_threshold

                print("{:.3f}: {:5s} CHOOSE_BEST_REPLICA: U_old({}, {}) U_new({}, {}) diff({} {} {}) {} {}".format(self.env.now, self.id(), old_best_utility, old_best_replica, this_best_utility, this_best_replica, diff_text, comparator, threshold_text, " keep ", old_best_replica ))

            if diff != 0 and diff >= Router.fib_utility_update_threshold:
                # update count
                # (kept: only counts the rare same-replica case where diff
                #  crosses the threshold, i.e. the old best had no RIB entry
                #  to patch from; value refreshes are not counted so the
                #  counter's meaning matches previous runs)
                self.service_fib_updates += 1


        # Count the FIB stability action the lines below print
        # (no prefix -- not counted -- when there was and is no best replica)
        if old_best_replica == None:
            fib_action = 'SET' if old_best_replica != self.best_replica else None
        else:
            fib_action = 'CHANGED' if old_best_replica != self.best_replica else 'KEEP'
        if fib_action is not None:
            Router.count_fib_action(self.id(), fib_action)

        # Print out some info on what changed
        if Verbose.level >= 1:

            # print ("old_best_replica " + str(old_best_replica) + " self.best_replica " + str(self.best_replica) + " self.best_neighbour " + str(self.best_neighbour))
            
            if self.best_replica == self.best_neighbour:
                # the best replica is the directly connected best neighbour
                if Verbose.level >= 1:
                    if old_best_replica == None:
                        print("{:.3f}: {:5s} {}BEST_REPLICA {} direct ".format(self.env.now, self.id(), ("SET_" if old_best_replica != self.best_replica else ""), self.best_replica))
                    else:
                        print("{:.3f}: {:5s} {}BEST_REPLICA {} direct ".format(self.env.now, self.id(), ("CHANGED_" if old_best_replica != self.best_replica else "KEEP_"), self.best_replica))

            else:
                # the best replica is via the best neighbour
                if Verbose.level >= 1:
                    if old_best_replica == None:
                        print("{:.3f}: {:5s} {}BEST_REPLICA {} via best neighbour {} ".format(self.env.now, self.id(), ("SET_" if old_best_replica != self.best_replica else ""), self.best_replica, self.best_neighbour))
                    else:
                        print("{:.3f}: {:5s} {}BEST_REPLICA {} via best neighbour {} ".format(self.env.now, self.id(), ("CHANGED_" if old_best_replica != self.best_replica else "KEEP_"), self.best_replica, self.best_neighbour))

        # update the FIB
        
        # keep track of best_neighbour, best_replica, best_utility for servicename
        if self.best_utility > 0:
            # only update FIB if the best replica has utility > 0
            self.service_FIB[self.servicename] = { 'neighbour': self.best_neighbour,
                                               'replica': self.best_replica,
                                               'utility': self.best_utility,
                                               'load': self.best_load,
                                               'delay': self.best_delay,
                                               'update_time': self.best_update_time }


        if Verbose.level >= 1:
            print("{:.3f}: {:5s} SERVICE_FIB update_count: {} {}".format(self.env.now, self.id(), self.service_fib_updates, self.service_FIB))


    # Work out utility difference from self.best_utility
    def calculate_utility_difference(self, utility, best_utility):
        diff = utility - best_utility 

        # print("calculate_utility_difference: diff = " + str(diff) + " utility = " + str(utility) + " best_utility = " + str(best_utility))

        return diff

    # Record the forwarding decision on the packet
    # This router is the deciding router:
    # the last router with hop_by_hop, the first router with first-decide
    def record_forwarding_decision(self, packet, fib_entry):
        """At the forwarding decision: snapshot ground truth (t_sel) and the
           FIB estimate the decision was based on (from the update at t_update).
           The snapshot is taken from THIS router's vantage so the ground truth
           (SEL_UTIL_SEL, BEST_UTIL_SEL) shares the latency basis of the FIB
           estimate (SEL_UTIL_EST)."""
        # The silent level has no consumer for this data: best_replica_utility
        # returns before reading it, so skip the ground-truth calculation.
        if Verbose.level < -1:
            return

        self.network.inject_snapshot_optimal_utility(packet, vantage=self.id())
        packet.selection_estimate = { 'update_time': fib_entry['update_time'],  # t_update
                                      'server_id': fib_entry['replica'],        # s_sel
                                      # RIB delay: this router's latency to the replica
                                      'latency': fib_entry['delay'],
                                      'load': fib_entry['load'],
                                      'utility': fib_entry['utility'] }         # SEL_UTIL_EST

    # Handle a ClientRequest
    def client_request_packet(self, link_end, packet):
        """A Client has sent a request"""

        if Verbose.level >= 2:
            print("{:.3f}: {:5s} RECV_PACKET ClientRequest {}.{} ({:.3f}) [{}.{}]  for service {} pkt: {} after {:.3f}".format(self.env.now, self.id(), packet.src, packet.pkt_no, packet.time, packet.src, packet.id, packet.dst, packet.id, (self.env.now - packet.time)))

        # Destination is likely to be a service name: e.g. §a
        service_name = packet.dst

        # no FIB entry, or one set to None when all utilities reached zero:
        # drop the request (the branches below assume a usable entry)
        if self.service_FIB.get(service_name) is None:
            if Verbose.level >= -1:
                print("{:.3f}: {:5s} REQUEST_NOT_FORWARDED [{}.{}] for service {} pkt: {}".format(self.env.now, self.id(), packet.src, packet.pkt_no, service_name, packet.id))
            return

        if Router.hop_by_hop:
            # --- Original Hop-by-Hop Anycast Routing ---
            if not service_name in self.service_FIB:
                # no service name in the service_FIB
                if Verbose.level >= 2:
                    print("{:.3f}: {:5s} NO_SERVICE_FIB_ENTRY ClientRequest for service {} pkt: {}.{}  Not Forwarded".format(self.env.now, self.id(), packet.dst, packet.src, packet.pkt_no))
            else:
                # we have that service name in the service_FIB
                neighbour = self.service_FIB[service_name]['neighbour']

                if Verbose.level >= 2:
                    print ("{:.3f}: {:5s} CLIENT_REQUEST_NEIGHBOUR ClientRequest  {}.{} = {}".format(self.env.now, self.id(), packet.src, packet.pkt_no, neighbour))

                if neighbour == None:
                    if Verbose.level >= 0:
                        print("{:.3f}: {:5s} NO_VALUE_FOR SERVICE_FIB ENTRY ClientRequest for service {} pkt: {}".format(self.env.now, self.id(), packet.dst, packet.id))
                else:
                    # Record the forwarding decision at the deciding router
                    # with hop_by_hop that is the last router only,
                    # i.e. when the neighbour is a host
                    if not hasattr(packet, 'optimal_snapshot') and self.is_neighbour_host(neighbour):
                        self.record_forwarding_decision(packet, self.service_FIB[service_name])

                    if Verbose.level >= 2:
                        print("{:.3f}: {:5s} FORWARD_PACKET ClientRequest for service {} pkt: {} send to neighbour {}".format(self.env.now, self.id(), packet.dst, packet.id, neighbour))
                    self.send_packet_to_neighbour(packet, neighbour)

        else:
            # --- First-Decide Single-Decision Unicast Routing ---
            if not service_name in self.service_FIB:
                # no service name in the service_FIB
                if Verbose.level >= 2:
                    print("{:.3f}: {:5s} NO_SERVICE_FIB_ENTRY ClientRequest for service {} pkt: {}.{}  Not Forwarded".format(self.env.now, self.id(), packet.dst, packet.src, packet.pkt_no))
            else:
                # we have that service name in the service_FIB
                best_replica = self.service_FIB[service_name]['replica']

                if Verbose.level >= 2:
                    print ("{:.3f}: {:5s} CLIENT_REQUEST_NEIGHBOUR ClientRequest  {}.{} = {}".format(self.env.now, self.id(), packet.src, packet.pkt_no, best_replica))

                if best_replica == None:
                    if Verbose.level >= 0:
                        print("{:.3f}: {:5s} NO_VALUE_FOR SERVICE_FIB ENTRY ClientRequest for service {} pkt: {}".format(self.env.now, self.id(), packet.dst, packet.id))
                else:
                    packet.service = service_name
                    packet.dst = best_replica
                    
                    # Record the forwarding decision at the deciding router
                    # with first-decide that is the first router
                    # (after packet.dst is set: the snapshot tie-breaks towards packet.dst)
                    if not hasattr(packet, 'optimal_snapshot'):
                        self.record_forwarding_decision(packet, self.service_FIB[service_name])

                    if Verbose.level >= 1:
                        print("{:.3f}: {:5s} SINGLE_DECISION ClientRequest {}.{} for service {} forwarded to replica {} send to neighbour {}".format(self.env.now, self.id(),  packet.src, packet.pkt_no, service_name, best_replica, link_end.dst_node))

                    # print forward info
                    neighbour = self.route_to(packet.dst)
                    if Verbose.level >= 2:
                        print("{:.3f}: {:5s} FORWARD_PACKET ClientRequest {}.{} for service {} pkt: {} send to neighbour {}".format(self.env.now, self.id(),  packet.src, packet.pkt_no, packet.dst, packet.id, link_end.dst_node))

                    self.normal_forwarding_packet(packet, link_end)                

    # Do normal forwarding
    def normal_forwarding_packet(self, packet, link_end):
        
        if packet.dst == None:
            # dont forward to None
            if Verbose.level >= 2:
                print("{:.3f}: {:5s} PACKET_ERROR {}.{} for {} NO forward from {} to {} after {:.3f}".format(self.env.now, self.id(), packet.src, packet.pkt_no, packet.dst, self.id(), packet.dst, (self.env.now - packet.time)))

        else:
            # forward the packet using unicast_forwarding_table
             
            # unicast_forwarding_table maps destination -> next hop:  's1': 'b'

            # get the next hop for the destination
            if packet.dst in self.unicast_forwarding_table:

                neighbour = self.route_to(packet.dst)
                
                if link_end and link_end.src_node and link_end.src_node.id() == neighbour:
                    # don't send to where it came from
                    if Verbose.level >= 2:
                        print("{:.3f}: {:5s} PACKET_ERROR {}.{} dont send back from {} to {} after {:.3f}".format(self.env.now, self.id(), packet.src, packet.pkt_no, self.id(), link_end.src_node.id(), (self.env.now - packet.time)))


                elif isinstance(self.neighbour_destination(neighbour),  Host) and packet.dst != self.neighbour_destination(neighbour).id():
                    # don't send to any connected Hosts unless it is the destination of the packet
                    if Verbose.level >= 2:
                        print("{:.3f}: {:5s} PACKET_ERROR {}.{} dont send to host from {} to {} after {:.3f}".format(self.env.now, self.id(), packet.src, packet.pkt_no, self.id(), self.neighbour_destination(neighbour).id(), (self.env.now - packet.time)))

                else:
                    # forward the packet
                    # send to SwitchPort
                    self.send_packet_to_neighbour(packet, neighbour)

                    if Verbose.level >= 1:
                        print("{:.3f}: {:5s} PACKET_FORWARD {}.{} for {} forwarded from {} to {} after {:.3f}".format(self.env.now, self.id(), packet.src, packet.pkt_no, packet.dst, self.id(), neighbour, (self.env.now - packet.time)))


            else:
                # not in unicast_forwarding_table
                if Verbose.level >= 2:
                    print("{:.3f}: {:5s} PACKET_ERROR {}.{} for {} not in unicast_forwarding_table at {} ".format(self.env.now, self.id(), packet.src, packet.pkt_no, packet.dst, self.id()))

                    print(str(self.unicast_forwarding_table))
        

    # Send packet to neighbour
    def send_packet_to_neighbour(self, packet, neighbour):
        # forward the packet
        # send to SwitchPort
        self.outgoing_ports[neighbour].put(packet)

    # Get the destination for a neighbour
    def neighbour_destination(self, neighbour):
        # get dst_node from the SwitchPort info for this neighbour
        return self.outgoing_ports[neighbour].out.dst_node

    def put(self, packet):
        """ The callback from an EventGenerator.
        """
        # We don't expect to send Events to Routers
        # but for backwards compatibility, we do this
         # add a tuple of (link_end, packet) to the packet store
        self.packet_store.put((None, packet))

    # check the sent table
    def check_sent_table(self, metric_to_send, neighbour):
        #print ("check_sent_table: " + neighbour + " ==> " + str(metric_to_send))

        # is this (replica, neighbour) pair in the sent table
        return neighbour in self.sent_table.get(metric_to_send['replica'], ())

    # delete a RIB entry
    def delete_rib_entry(self, metric):
        # remove the entry keyed by replica
        self.service_RIB.pop(metric['replica'], None)
        self.rib_utility.pop(metric['replica'], None)
        if Verbose.level >= 2:
            print ("{:.3f}: {:5s} REMOVE_METRIC metric {}".format(self.env.now, self.id(), metric) )
        
    # update the sent table
    def update_sent_table(self, metric_to_send, neighbour):
        # add info about the transmission to the sent_table
        replica = metric_to_send['replica']
        sent_neighbours = self.sent_table.setdefault(replica, {})

        if neighbour not in sent_neighbours:
            # nothing found - it must be new, so add it
            sent_neighbours[neighbour] = None

            if Verbose.level >= 2:
                print ("{:.3f}: {:5s} ADD_SENT_TABLE metric {} neighbour {}".format(self.env.now, self.id(), replica, neighbour) )

        else:
            # already recorded
            if Verbose.level >= 2:
                print ("{:.3f}: {:5s} UPDATE_SENT_TABLE metric {} neighbour {}".format(self.env.now, self.id(), replica, neighbour) )



    # clear entries in sent table
    def clear_sent_table(self, metric_replica):
        """Clear entries in sent table for replica 'metric_replica'"""
        
        if Verbose.level >= 2:
            print ("{:.3f}: {:5s} CLEAR_SENT_TABLE metric {}".format(self.env.now, self.id(), metric_replica) )

        self.sent_table.pop(metric_replica, None)
        self.skipped_sent.pop(metric_replica, None)

    # T-13: count the Withdraws a run without forward_to_tree_children_only
    # would send to the skipped tree non-children of replica (the
    # skipped_sent set, except came_from); the caller clears the set.
    def count_skipped_withdraws(self, replica, came_from):
        state = self.skipped_sent.get(replica)
        if state is None:
            return
        me = self._routerid
        n = 0
        for neighbour, port, dst_node, is_host in self._ports_by_neighbour():
            if is_host or neighbour == came_from or dst_node.unicast_forwarding_table.get(replica) == me:
                continue
            if state is True or neighbour != state:
                n += 1
        Router.tree_skipped['W'] += n

    # Print metric table
    def print_metric_table(self):
        if Verbose.table == 0:
            pass
        elif Verbose.table == 1:
            print("{:.3f}: {:5s} METRIC_TABLE {}".format(self.env.now, self.id(), str(list(self.service_RIB.values()))))
        else:
            print("{:.3f}: {:5s} METRIC_TABLE".format(self.env.now, self.id()))
            for metric_no, metric in enumerate(self.service_RIB.values()):
                print("\t\t{:2d}. replica({})  {}".format(metric_no+1, metric['replica'], metric))


    def print_sent_table(self):
        if Verbose.table == 0:
            pass
        elif Verbose.table == 1:
            print("{:.3f}: {:5s} SENT_TABLE {}".format(self.env.now, self.id(), str(self.sent_table)))
        else:
            print("{:.3f}: {:5s} SENT_TABLE".format(self.env.now, self.id()))
            for entry_no, (replica, neighbours) in enumerate(self.sent_table.items()):
                print("\t\t{:2d}. replica: {} neighbours: {}".format(entry_no+1, replica, sorted(neighbours)))


    # Print utility info
    def print_utility_info(self, entries, utility):
        if Verbose.table == 0:
            pass
        elif Verbose.table == 1:
            print ("{:.3f}: {:5s} UTILITY {} = {} ".format(self.env.now, self.id(), len(entries), list(zip (utility, map(lambda doc: "metric: {} load: {} delay: {} replica: {} neighbour: {}".format(doc['replica'],  doc['load'], doc['delay'], doc['replica'], doc['neighbour']), entries)))))
        else:
            print ("{:.3f}: {:5s} UTILITY {}".format(self.env.now, self.id(), len(entries)))
            for entry_no, entry in enumerate(entries):
                print("\t\t{:2d}.  replica({})  U({:.3f})  {}".format(entry_no+1, entry['replica'], utility[entry_no], entry))


    # Print announce info
    def print_announce_info(self, announce):
        if Verbose.table == 0:
            pass
        elif Verbose.table == 1:
            print("{:.3f}: {:5s} ANNOUNCE {} / {}".format(self.env.now, self.id(), len(announce), list(zip (map(lambda doc: doc['replica'], announce), announce))))
        else:
            print("{:.3f}: {:5s} ANNOUNCE count {}".format(self.env.now, self.id(), len(announce)))
            for entry_no, entry in enumerate(announce):
                print("\t\t{:2d}. replica({})  {}".format(entry_no+1, entry['replica'], entry))


    # Set the unicast forwarding table
    def set_unicast_forwarding_table(self, list_of_routes):
        """Set the forwarding table"""
        # takes a list of  entries like (destination, next_hop, weight)
        # and coverts into the internal forwarding table format

        # stored as destination -> next hop; the weight goes in the
        # router's latency_table row
        latency = self.network.latency_table.setdefault(self.id(), {})
        for entry in list_of_routes:
            self.unicast_forwarding_table[entry[0]] = entry[1]
            latency[entry[0]] = entry[2]

    # Get the unicast forwarding table
    def get_unicast_forwarding_table(self):
        """Get the forwarding table: {destination: next_hop}"""
        # the delay to each destination is the router's latency_table row
        # (see distance_to)

        return self.unicast_forwarding_table

    # Get the route to a specific node
    def route_to(self, dst):
        """Get the next hop for a route to a destination"""
        if isinstance(dst, str):
            return self.unicast_forwarding_table[dst]
        else:
            return self.unicast_forwarding_table[dst.id()]

    # Get the next hop to a destination, without raising
    def next_hop_to(self, dst):
        """Next hop toward dst, or None if no route"""
        return self.unicast_forwarding_table.get(dst)

    # Get the distance to a specific node
    def distance_to(self, dst):
        """Get the distance to a destination"""
        if isinstance(dst, str):
            return self.network.latency_table[self.id()][dst]
        else:
            return self.network.latency_table[self.id()][dst.id()]


    def recv(self, packet, link_end):
        """A packet is received from a LinkEnd of a neighbouring Router.
        """
        # this function should be called by the previous hop to send a packet to this router
        # packet_store is a simpy.Store(self.env, capacity=1)
        if packet.src == self._routerid:
            if Verbose.level >= 2:
                print("{:.3f}: {:5s} PACKET_CREATED {}.{} ({:.3f}) in {} after {:.3f}".format(self.env.now, self.id(), packet.src, packet.pkt_no, packet.time, self._routerid, (self.env.now - packet.time)))
        else:
            if Verbose.level >= 2:
                print("{:.3f}: {:5s} PACKET_ARRIVED {}.{} ({:.3f}) in {} from {} after {:.3f}".format(self.env.now, self.id(), packet.src, packet.pkt_no, packet.time, self.id(), link_end.src_node.id(), (self.env.now - packet.time)))

        # handle it at once (packet_store and run() are for this node's own packets)
        self.manage_packet((link_end, packet))

    def neighbours(self):
        """Neighbours of Router"""
        return list(self.outgoing_ports.keys())

    def is_neighbour(self, node):
        """Is neighbour of a Router"""
        keys = self.outgoing_ports.keys()
        return node in keys

    def is_neighbour_host(self, node):
        """Is neighbour of a Router a Host"""
        keys = self.outgoing_ports.keys()
        if node in keys:
            return isinstance(self.outgoing_ports[node].out.dst_node,  Host)
        else:
            False

    def weight_edge(self, dest):
        """Propagation delay of the link from this router to dest (a node
        name, Router or Host); 0 if dest is not a neighbour."""
        # Nov 2026: one lookup by name for routers and hosts. Before, a Host
        # object always gave 0 (only names and Router objects were looked up).
        name = dest if isinstance(dest, str) else getattr(dest, "id", lambda: None)()
        port = self.outgoing_ports.get(name)
        return port.out.propagation_delay if port is not None else 0

    def degree(self):
        """Degree of Router"""
        return len(self.outgoing_ports)

    def ports(self):
        """Dict of ports"""
        return self.outgoing_ports
            
    def id(self):
        """The id of this node"""
        return self._routerid

    def aggregate_name(self):
        """The id of this node"""
        return "!" + self._routerid

    def __str__(self):
        return "Router " + str(self._routerid) 

    def __repr__(self):
        return "Router " + str(self._routerid) 

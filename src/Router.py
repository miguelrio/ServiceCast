import simpy
from SimComponents import SwitchPort, PacketSink, Packet
from Link import LinkEnd
from Host import Host
from Verbose import Verbose
from Utility import Utility
from Server import ServerMetricMessageType
from tinydb import TinyDB, Query
from tinydb.storages import MemoryStorage
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

    

LINKRATE = 10000000


def less_than(x,y):
    return x < y

def greater_than(x,y):
    return x > y

def same_as(x,y):
     return x == y


class Router(object):
    """ A Router in the emulation.
      Requires a put() method as a callback from the PacketGenerator.
    """

    # threshold for FIB utility change factor  10% -> 0.1
    fib_utility_update_threshold = 0.1

    # routing mode: True for hop-by-hop anycast, False for first-decide unicast
    hop_by_hop = True

    # metric is better range
    # a way to accept one metric being the Same as another metric
    # if the difference between the values is < range
    metric_is_better_range = 0

    # The following staticmethods can be reset from the outside
    # to change the behaviour of the algorithms

    # default better than fn
    
    # dict of better than fns
    better_than_fn = {}
    # the default better for load is less_than
    better_than_fn['load'] = staticmethod(less_than)
    # the default better for delay is less_than
    better_than_fn['delay'] = staticmethod(less_than)

    # dict of same as fns
    same_as_fn = {}
    # the default same as for load is less_than
    same_as_fn['load'] = staticmethod(same_as)
    # the default same as for delay is less_than
    same_as_fn['delay'] = staticmethod(same_as)

    # better_than_fn = staticmethod(less_than)



    # network can be a Network or an simpy.Environment()
    # this gives flexibility in usage
    def __init__(self, routerid, network=None):
        self.network = network
        self._routerid = routerid
        self.pkt_no = 1
        self.type = "Router"

        # create one SimComponent.SwitchPort for each neighbour_id
        self.outgoing_ports = dict()

        # a unicast forwarding table
        # each entry is { destination: (destination, next_hop, weight) }
        self.unicast_forwarding_table = dict()
        
        # set the simulation environment
        self.set_env(network)

        # a database of metrics
        # self.db = TinyDB('/tmp/router-metrics-' + str(routerid) + '.json')
        self.db = TinyDB(storage=MemoryStorage)
        
        # the table for metrics
        self.service_RIB = self.db.table('metrics')
        self.service_RIB.truncate()
        
        # the table for announcements which have been sent
        self.sent_table = self.db.table('sent')
        self.sent_table.truncate()

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
              'same': Router.same_as_fn['load'],
              'better': Router.better_than_fn['load']

             },
            # specify the metric functions for 'delay'
            # currently get them from the class variables
            { 'name': 'delay',
              'same': Router.same_as_fn['delay'],
              'better': Router.better_than_fn['delay']
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

    def add_neighbour(self, neighbour_obj, propdelay=1, rate=LINKRATE):
        """Add a neighbour to this router"""
        neighbour = neighbour_obj.id()
            
        # check if the neighbour_obj already has a link
        if (self.contains_edge(neighbour_obj)):
            # no need to add a link

            if Verbose.level >= 2:
                print("LinkEnd Exists "  + str(self.id()) + " --> " + str(neighbour) + " Cancel " +  str(self.id()) + " --> " + str(neighbour) )

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


        # If the announcement has arrived on a link that is not the one
        # in the forwarding table, for the replica then Drop the message
        valid_route = self.arrived_from_unicast_route(replica, link_end)

        if Verbose.level >= 2:
            print("{:.3f}: {:5s} UNICAST_ROUTE for {} from {} --> {} ".format(self.env.now, self.id(), replica, link_end.src_node.id(), 'VALID' if valid_route else 'INVALID'))

        if not valid_route:
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

            # avoid least loaded going everywhere
            # check the propagation_time

            propagation_time = metrics['delay']

            network_diameter = self.network.network_diameter()

            normalised_load = self.network.get_normalised_load(replica)

            average_normalised_load = self.network.average_normalised_load()

            replica_available_capacity = self.network.get_replica_capacity(replica, 'slots')

            system_available_capacity = self.network.get_total_replica_capacity('slots')

            
            if system_available_capacity == 0:
                if Verbose.level >= 2:
                    print("SYSTEM_AVAILABLE_CAPACITY " + "'" + str(self.id()) + "'" + " == 0 announcement_distance 0")
                announcement_distance = 0
            else:
                announcement_distance =  (replica_available_capacity / system_available_capacity)  * (normalised_load - average_normalised_load + 1) * network_diameter 


            if Verbose.level >= 2:
                # example:   381.000: POT   ANNOUNCEMENT_DISTANCE msgid: 24 replica: s4 msg time: 379.0  propagation_time: 2 load_utility(s4): 2.0 average_load_utility: 1.9 replica_capacity: 45 system_available_capacity: 232 announcement_distance: 1.494 
                print("{:.3f}: {:5s} ANNOUNCEMENT_DISTANCE msgid: {} replica: {} msg time: {}  propagation_time: {} normalised_load({}): {} average_normalised_load: {} replica_capacity: {} system_available_capacity: {} announcement_distance: {} ".format(self.env.now, self.id(), msgID, replica, creationTime, round(propagation_time, 6), replica, normalised_load, round(average_normalised_load, 6), replica_available_capacity, system_available_capacity,  round(announcement_distance, 3)))

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
        # so find entry from database for replica
        searchR = Query()
        results = self.service_RIB.search((searchR.replica == replica))

        if Verbose.level >= 1:
            print("{:.3f}: {:5s} METRIC_SEARCH_RESULTS link_end: {} replica: {} ==> {}".format(self.env.now, self.id(), link_end, replica, list(zip (map(lambda doc: doc.doc_id, results), results))))
        
        # check results
        # If there is NO existing entry in the service RIB
        if results == []:
            # nothing found - it must be new, so add it
            val = self.service_RIB.insert({ 'replica': replica, 'neighbour': neighbour, 'link_end': str(link_end), 'msgID': msgID, 'servicename': servicename, 'creationTime': creationTime, 'load': metrics['load'], 'no_of_flows': int(metrics['no_of_flows']), 'delay': metrics['delay'], 'slots': metrics['slots']  })

            if Verbose.level >= 2:
                print ("{:.3f}: {:5s} ADD_METRIC metric from {} as no {}".format(self.env.now, self.id(), replica, val) )

        else:
            # something found in service_RIB

            # existing entry is newer than the incoming update
            searchT = Query()
            resultsT = self.service_RIB.search((searchT.replica == replica) & (searchT.creationTime > creationTime))

            # check results
            if resultsT != []:
                # we found an entry with a newer time
                if Verbose.level >= 2:
                    print("{:.3f}: {:5s} METRIC_TOO_OLD link_end: {} replica: {} ==> {}".format(self.env.now, self.id(), link_end, replica, list(zip (map(lambda doc: doc.doc_id, results), resultsT))))
                    
                return

            # Update the metrics in the existing RIB entry

            # replica stay the same
            # update other values
            val = self.service_RIB.update({ 'neighbour': neighbour, 'link_end': str(link_end), 'msgID': msgID, 'servicename': servicename, 'creationTime': creationTime, 'load': metrics['load'], 'no_of_flows': metrics['no_of_flows'], 'delay': metrics['delay'], 'slots': metrics['slots'] } , doc_ids=[ r.doc_id for r in results ])

            if Verbose.level >= 2:
                print("{:.3f}: {:5s} UPDATE_METRIC metric no {} msgID: {} creationTime: {:.6f}  load: {} delay: {}".format(self.env.now, self.id(), val, msgID, creationTime, metrics['load'], metrics['delay'] ))

            # mark this doc_id, if in sent_table
            # val[0] is a doc_id
            sent_query = Query()
            sent_results = self.sent_table.search(sent_query.metric_doc_id == val[0])

            if sent_results != []:
                # it is in the sent_table
                metric = self.service_RIB.get(doc_id=val[0])
                marked = metric
                if Verbose.level >= 2:
                    print("{:.3f}: {:5s} MARK_METRIC {}".format(self.env.now, self.id(), metric['replica']))

                
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
        decide_pbr = self.decide_announcements(self.service_RIB.all())

        if Verbose.level >= 1:
            self.print_announce_info(decide_pbr)

        # Work out what to send from the PBR and the sent_table

        # First evaluate the metrics from the sent_table
        
        # get unique list of sent doc_ids
        sent_doc_ids = list(set([s['metric_doc_id'] for s in self.sent_table]))
        # sent is list of metrics
        sent_set = [self.service_RIB.get(doc_id=d) for d in sent_doc_ids]

        if sent_set:
            if Verbose.level >= 3:
                print("\t\t >>> sent_set " + str(len(sent_set)) + " " + str(sent_set))

        # announce set are those in decide_pbr and not in sent
        # plus the marked one, if it is in the decide_pbr

        marked_set = [marked] if marked in decide_pbr else []

        if marked_set:
            if Verbose.level >= 3:
                print("\t\t >>> marked_set " + str(len(marked_set)) + " " + str(marked_set))
                
        announce_set = [m for m in decide_pbr if m.doc_id not in [ s.doc_id for s in sent_set ]] + marked_set


        # use all of them and label announce entries to have message type Announce
        announce = list(zip(announce_set, itertools.repeat(ServerMetricMessageType.Announce)))

        if announce:
            if Verbose.level >= 3:
                print("\t\t >>> announce_set " + str(len(announce)) + " " + str(announce))


        # withdraw set are those in sent_table minus those in decide_pbr
        withdraw_set = [s for s in sent_set if s.doc_id not in [ d.doc_id for d in decide_pbr ]]
        
        # label withdraw_set entries to have message type Withdraw
        withdraw = list(zip(withdraw_set, itertools.repeat(ServerMetricMessageType.Withdraw)))
                     
        if withdraw:
            if Verbose.level >= 3:
                print("\t\t>>> withdraw_set " + str(len(withdraw)) + " " + str(withdraw))
            

        # if there is a metric in the marked_set
        # we need to clear it from the sent_table
        if marked_set != []:
            # delete from sent_table for marked
            self.clear_sent_table(marked_set[0].doc_id)


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
        # so find entry from database for replica
        searchR = Query()
        results = self.service_RIB.search((searchR.replica == replica))

        # check results
        # If there is NO existing entry in the service RIB
        if results == []:
            # nothing found - nothing to do
            pass
        else:
            if Verbose.level >= 2:
                print("{:.3f}: {:5s} WITHDRAW_SEARCH_RESULTS link_end: {} replica: {} ==> {}".format(self.env.now, self.id(), link_end, replica, list(zip (map(lambda doc: doc.doc_id, results), results))))

            # there should only be 1 entry of relevance
            candidate = results[0]

            # now check the sent table
            sent_query = Query()
            sent_results = self.sent_table.search((sent_query.metric_doc_id == candidate.doc_id))

            # how many times did we find this doc_id in the sent_table
            no_found_in_sent_table = len(sent_results)

            #self.print_sent_table()


            if no_found_in_sent_table == 0:
                # nothing in sent_table
                # so no withdrawals sent on
                if Verbose.level >= 2:
                    print("{:.3f}: {:5s} SENT_TABLE_NOTHING in sent_table: for {}".format(self.env.now, self.id(), candidate.doc_id))

                # now delete the candidate metric from the RIB
                self.delete_rib_entry(candidate)

                if Verbose.level >= 2:
                    self.print_metric_table()
            
            else:
                # this metric is in the sent table
                if Verbose.level >= 2:
                    print("{:.3f}: {:5s} SENT_TABLE_FOUND {} in sent_table:  metric [{}] need to withdraw".format(self.env.now,  self.id(), no_found_in_sent_table, candidate.doc_id))

            
                # do we need any withdrawal announcements
                for sent_entry in sent_results:
                    #print("link_end = " + str(link_end) + " sent_entry = " + str(sent_entry))

                    neighbour = sent_entry['neighbour']

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
                self.clear_sent_table(candidate.doc_id)

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

            if Verbose.level >= 2:
                print("{:.3f}: {:5s} WITHDRAW_END".format(self.env.now, self.id()))
        

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

    # Announce the entries
    # Consider some specific limits and caveats
    # e.g. announce on all the links that it wasn't received from
    def announce_metrics(self, announcements):
                
        # skip through all the announcements
        for metric_no, metric_to_send_tuple in enumerate(announcements):

            # unpick metric and force from the tuple
            metric_to_send, msg_type = metric_to_send_tuple

            # print("{:.3f}: Check {} - metric no {} {} announcement {} withdraw {}".format(self.env.now, self.id(),  metric_to_send.doc_id, msg_type, msg_type == ServerMetricMessageType.Announce, msg_type == ServerMetricMessageType.Withdraw))

            # 12/9/2023
            # is neighbour a directly connected host
            if self.is_neighbour_host(metric_to_send['replica']):
                if Verbose.level >= 2:
                    print("{:.3f}: {:5s} ANNOUNCE directly connected {}".format(self.env.now, self.id(), metric_to_send['replica']))

                # if we are doing aggregation, then use values from
                # the metric_to_send in the connected_capacity table

                # we adapt the metric to send to have the connected total
                # iff we use aggregation
                # if self.aggregating_connected:
                #    metric_to_send['replica'] = self.id()
                #    metric_to_send['aggregate'] = True
                #    metric_to_send['load'] = self.connected_capacity_total['load']
                #    metric_to_send['no_of_flows'] = self.connected_capacity_total['no_of_flows']
                #    metric_to_send['slots'] = self.connected_capacity_total['slots']
                
            else:
                if Verbose.level >= 2:
                    print("{:.3f}: {:5s} ANNOUNCE NOT directly connected {}".format(self.env.now, self.id(), metric_to_send['replica']))



            # send to neighbours
            for neighbour in self.outgoing_ports:

                # print("Check " +  metric_to_send['link_end'] +  " <--> " + str(neighbour))

                if isinstance(self.neighbour_destination(neighbour),  Host):
                    # don't send to any connected Hosts
                    if Verbose.level >= 2:
                        print("{:.3f}: {:5s} NOT_TO_HOST {} - metric no {}".format(self.env.now, self.id(), self.neighbour_destination(neighbour), metric_to_send.doc_id))
                    pass


                elif metric_to_send['neighbour'] == str(neighbour):
                    # don't send to where it came from
                    if Verbose.level >= 2:
                        print("{:.3f}: {:5s} NO_RETURN to {} - metric no {}".format(self.env.now, self.id(), neighbour,  metric_to_send.doc_id))
                    pass

                else:
                    # a candidate for forwarding

                    # check if it is an Announcement or a Withdraw

                    if msg_type == ServerMetricMessageType.Announce:
                        # Announce

                        if self.check_sent_table(metric_to_send, neighbour):
                            # this is in the sent table, so no need to send
                            if Verbose.level >= 2:
                                print ("{:.3f}: {:5s} ALREADY_IN_SENT_TABLE neighbour {} metric no {} msgID {}".format(self.env.now, self.id(), neighbour, metric_to_send.doc_id, metric_to_send['msgID']) )
                                pass


                        else:
                            # send a new packet

                            # create a new packet
                            new_packet = self.metric_to_packet(metric_to_send, msg_type, neighbour)

                            self.pkt_no += 1

                            # forward the packet
                            if Verbose.level >= 1:
                                print("{:.3f}: {:5s} FORWARD_METRIC to {} msg {}".format(self.env.now,  self.id(), self.neighbour_destination(neighbour).id(), metric_to_send))

                            # send to relevant SwitchPort
                            self.send_packet_to_neighbour(new_packet, neighbour)

                            # update sent_table
                            self.update_sent_table(metric_to_send, neighbour)

                    elif msg_type == ServerMetricMessageType.Withdraw:
                        # Withdraw
                        
                        if self.check_sent_table(metric_to_send, neighbour):
                            # this is in the sent table, so send withdraw

                            # send a new packet

                            # create a new packet
                            new_packet = self.metric_to_packet(metric_to_send, msg_type, neighbour)

                            self.pkt_no += 1

                            # forward the packet
                            if Verbose.level >= 2:
                                print("{:.3f}: {:5s} FORWARD_WITHDRAW to {} msg {}".format(self.env.now, self.id(), self.neighbour_destination(neighbour).id(), metric_to_send))

                            # send to relevant SwitchPort
                            self.send_packet_to_neighbour(new_packet, neighbour)

                        else:
                            # not in sent_table, so no need to send Withdraw
                            if Verbose.level >= 2:
                                print ("{:.3f}: {:5s} NOT_IN_SENT_TABLE neighbour {} metric no {} msgID {}".format(self.env.now, self.id(), neighbour, metric_to_send.doc_id, metric_to_send['msgID']) )

                            pass
                    else:
                        print("UNKNOWN ServerMetricMessageType " + msg_type)
                
            # if the msg_type is Withdraw, clear sent_table
            if msg_type == ServerMetricMessageType.Withdraw:
                # delete from sent_table
                self.clear_sent_table(metric_to_send.doc_id)


        if Verbose.level >= 2:
            print("{:.3f}: {:5s} ANNOUNCE_END".format(self.env.now, self.id()))

        
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
        # unicast_forwarding_table entries look like:  's1': ('s1', 'b', 3)

        if replica in self.unicast_forwarding_table:
            entry = self.unicast_forwarding_table[replica]

            # get the Dijkstra link for the servicename
            link = entry[1]

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
    def  is_better_in_any_metrics(self, j,i):
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


    # decide the entries to announce, given a set of entries
    def decide_announcements(self, entries):
        if len(entries) == 1:
            return [entries[0]]

        else:
            # the list of things to announce
            announce = [False for i in entries]

            # skip through all entries - outer loop
            for index_i, i in enumerate(entries):

                # label i as True
                announce[index_i] = True
                
                # skip through all entries - inner loop
                for index_j, j in enumerate(entries):

                    # no need to do the diagonal
                    if index_i != index_j:

                        # is j better than i
                        better_j_i = self.is_better_in_any_metrics(j,i) 

                        if better_j_i == Compare.Better: # j is better than i in at least 1 metrics 
                            # so we don't need i anymore
                            announce[index_i] = False

                            if Verbose.level >= 3:
                                print("Compare.Better: j_{} is better than i_{}: {} {}".format(index_j, index_i, self.displayMetrics('j: ', j), self.displayMetrics('i: ', i)))
                        
                            break

                        elif better_j_i == Compare.Same: # j is same in all metrics

                            # so we don't need j
                            announce[index_j] = False
                            
                            if Verbose.level >= 3:
                                print("Compare.Same: j_{} is same as i_{}: {} {}".format(index_j, index_i, self.displayMetrics('j: ', j), self.displayMetrics('i: ', i)))


                        else:
                            # we keep i
                            if Verbose.level >= 3:
                                print("Compare.Worse: j_{} is not better than i_{}: {} {}".format(index_j, index_i, self.displayMetrics('j: ', j), self.displayMetrics('i: ', i)))
                        

            # at this point the announce list should have a True for all the entries to announce
            if Verbose.level >= 3:
                print("announce: {}".format(announce))

            # select those entries which are laballed as True in announce
            return [ entry for ann, entry in zip(announce, entries) if ann == True ]

    # is the newly arrived metrics worse 
    def check_metrics_worse(self, metrics, doc):
        """Returns (doc_id, count in sent_table)"""
        # is it better or worse
        better_j_i = self.is_better_in_any_metrics(metrics, doc)

        if better_j_i == Compare.Worse:
            # it looks worse

            if Verbose.level >= 2:
                print("{:.3f}: check_worse_metrics {} metric [{}] --> {}".format(self.env.now, str(better_j_i), doc.doc_id, doc))

            # now check the sent table
            sent_query = Query()
            sent_results = self.sent_table.search((sent_query.metric_doc_id == doc.doc_id))

            # how many times did we find this doc_id in the sent_table
            no_found_in_sent_table = len(sent_results)

            if no_found_in_sent_table > 0:
                # this metric is in the sent table
                if Verbose.level >= 2:
                    print("{:.3f}: is in sent_table: metric [{}] need to resend".format(self.env.now, doc.doc_id))

            # return the doc_id of the metric (so it can be found later)
            # and how many times it was found
            return (doc.doc_id, no_found_in_sent_table)
        else:
            # Nothing found
            return (None, 0)

        # END of check if new metrics are worse than found result

    # display metrics
    def displayMetrics(self, label, metric):
        return "{} replica: {} load: {} delay: {}".format(label, metric['replica'], metric['load'], metric['delay'])

    def displayMetrics2(self, label, metric):
        return "{} replica: {} load: {} delay: {}".format(label, metric['replica'], metric['load'], metric['delay'])

    # Call the forwarding_utility_fn
    # which is usually set as a lambda in forwarding_utility_fn
    # load is already normalised in range 0 -> 1
    # delay is actual link delay: 1 .. n
    def call_forwarding_utility(self, alpha, load, delay):

        # First we map the actual delay into a normalised_delay
        # which is a value between 0 and 1
        normalised_delay = self.network.get_normalised_delay(delay)

        if Verbose.level >= 3:
            print("{:.3f}: {:5s} normalised_delay = {} for delay {}".format(self.env.now, self.id(), normalised_delay, delay))
        
        # calculate the utility
        # pass in the delay and the normalised_delay
        forwarding_utility =  Utility.eval_forwarding_utility(alpha, load, delay, normalised_delay)

        if Verbose.level >= 2:
            print("{:.3f}: {:5s} forwarding_utility = {} for normalised_load {} delay {} normalised_delay {}".format(self.env.now, self.id(), forwarding_utility, load, delay, normalised_delay))
        
        return forwarding_utility

    #  Check if fw table needs changing
    # and update FIB
    def choose_best_forwarding_replica_update_fib(self):
        # pass in all RIB entries
        self._choose_best_forwarding_replica_update_fib_with_entries(self.service_RIB.all())


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
            # call call_forwarding_utility
            # entry['load'] is normalised
            # entry['delay'] is raw value which is normalised in call_forwarding_utility
            utility_i = self.call_forwarding_utility(Utility.alpha, entry['load'], entry['delay'])

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

        if Router.hop_by_hop:
            # --- Original Hop-by-Hop Anycast Routing ---
            if not service_name in self.service_FIB:
                # no service name in the service_FIB
                if Verbose.level >= 2:
                    print("{:.3f}: {:5s} NO_SERVICE_FIB_ENTRY ClientRequest for service {} pkt: {}.{}".format(self.env.now, self.id(), packet.dst, packet.src, packet.pkt_no))
            else:
                # we have that service name in the service_FIB
                neighbour = self.service_FIB[service_name]['neighbour']

                if Verbose.level >= 2:
                    print ("{:.3f}: {:5s} CLIENT_REQUEST_NEIGHBOUR ClientRequest  {}.{} = {}".format(self.env.now, self.id(), packet.src, packet.pkt_no, neighbour))

                if neighbour == None:
                    if Verbose.level >= 2:
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
                    print("{:.3f}: {:5s} NO_SERVICE_FIB_ENTRY ClientRequest for service {} pkt: {}.{}".format(self.env.now, self.id(), packet.dst, packet.src, packet.pkt_no))
            else:
                # we have that service name in the service_FIB
                best_replica = self.service_FIB[service_name]['replica']

                if Verbose.level >= 2:
                    print ("{:.3f}: {:5s} CLIENT_REQUEST_NEIGHBOUR ClientRequest  {}.{} = {}".format(self.env.now, self.id(), packet.src, packet.pkt_no, best_replica))

                if best_replica == None:
                    if Verbose.level >= 2:
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
                        print("{:.3f}: {:5s} SINGLE_DECISION ClientRequest for service {} mapped to replica {} pkt: {} send to neighbour {}".format(self.env.now, self.id(), service_name, best_replica, packet.id, link_end.dst_node))

                    # print forward info
                    neighbour = self.route_to(packet.dst)
                    if Verbose.level >= 2:
                        print("{:.3f}: {:5s} FORWARD_PACKET ClientRequest for service {} pkt: {} send to neighbour {}".format(self.env.now, self.id(), packet.dst, packet.id, link_end.dst_node))

                    self.normal_forwarding_packet(packet, link_end)                

    # Do normal forwarding
    def normal_forwarding_packet(self, packet, link_end):
        
        if packet.dst == None:
            # dont forward to None
            if Verbose.level >= 2:
                print("{:.3f}: {:5s} PACKET_ERROR {}.{} for {} NO forward from {} to {} after {:.3f}".format(self.env.now, self.id(), packet.src, packet.pkt_no, packet.dst, self.id(), packet.dst, (self.env.now - packet.time)))

        else:
            # forward the packet using unicast_forwarding_table
             
            # unicast_forwarding_table entries look like:  's1': ('s1', 'b', 3)

            # get the Dijkstra link for the destination
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
        
        # find entry from sent_table for (doc_id in service_RIB, neighbour)
        sent_query = Query()
        sent_results = self.sent_table.search((sent_query.metric_doc_id == metric_to_send.doc_id) & (sent_query.neighbour == neighbour))

        return sent_results

    # delete a RIB entry
    def delete_rib_entry(self, metric):
        # If there is an existing entry in the service RIB 
        # so find entry from database for replica
        searchR = Query()

        # and remove it
        self.service_RIB.remove((searchR.replica == metric['replica']))
        if Verbose.level >= 2:
            print ("{:.3f}: {:5s} REMOVE_METRIC metric no {}".format(self.env.now, self.id(), metric) )
        
    # update the sent table
    def update_sent_table(self, metric_to_send, neighbour):
        # add info about the transmission to the sent_table
        # find entry from sent_table for (doc_id in service_RIB, neighbour)
        sent_query = Query()
        sent_results = self.sent_table.search((sent_query.metric_doc_id == metric_to_send.doc_id) & (sent_query.neighbour == neighbour))

        #if Verbose.level >= 1:
        #    print("{:.3f}: {:5s} SENT_TABLE_SEARCH  ==> {} ".format(self.env.now, self.id(), sent_results))
            
        # check results
        if sent_results == []:
            # nothing found - it must be new, so add it
            val = self.sent_table.insert({'metric_doc_id': metric_to_send.doc_id, 'neighbour': neighbour })

            if Verbose.level >= 2:
                print ("{:.3f}: {:5s} ADD_SENT_TABLE metric no {} neighbour {}".format(self.env.now, self.id(), metric_to_send.doc_id, neighbour) )

        else:
            # update the table
            if Verbose.level >= 2:
                print ("{:.3f}: {:5s} UPDATE_SENT_TABLE metric no {} neighbour {}".format(self.env.now, self.id(), metric_to_send.doc_id, neighbour) )



    # clear entries in sent table
    def clear_sent_table(self, metric_doc_id):
        """Clear entries in sent table with 'metric_doc_id'"""
        
        if Verbose.level >= 2:
            print ("{:.3f}: {:5s} CLEAR_SENT_TABLE metric no {}".format(self.env.now, self.id(), metric_doc_id) )

        before = len(self.sent_table)
        # print("size before = " + str(before))

        sent_query = Query()
        sent_results = self.sent_table.search((sent_query.metric_doc_id == metric_doc_id))

        found = len(sent_results)
        # print("found = " + str(found))

        self.sent_table.remove((sent_query.metric_doc_id == metric_doc_id))

        after = len(self.sent_table)
        # print("size after = " + str(after))

    # Print metric table
    def print_metric_table(self):
        if Verbose.table == 0:
            pass
        elif Verbose.table == 1:
            print("{:.3f}: {:5s} METRIC_TABLE {}".format(self.env.now, self.id(), str(self.service_RIB.all())))
        else:
            print("{:.3f}: {:5s} METRIC_TABLE".format(self.env.now, self.id()))
            for metric_no, metric in enumerate(self.service_RIB.all()):
                print("\t\t{:2d}. doc_id({:d})  {}".format(metric_no+1, metric.doc_id, metric))


    def print_sent_table(self):
        if Verbose.table == 0:
            pass
        elif Verbose.table == 1:
            print("{:.3f}: {:5s} SENT_TABLE {}".format(self.env.now, self.id(), str(self.sent_table.all())))
        else:
            print("{:.3f}: {:5s} SENT_TABLE".format(self.env.now, self.id()))
            for entry_no, entry in enumerate(self.sent_table.all()):
                metric = self.service_RIB.get(doc_id=entry['metric_doc_id'])
                print("\t\t{:2d}. replica: {} {}".format(entry_no+1, metric['replica'], entry))


    # Print utility info
    def print_utility_info(self, entries, utility):
        if Verbose.table == 0:
            pass
        elif Verbose.table == 1:
            print ("{:.3f}: {:5s} UTILITY {} = {} ".format(self.env.now, self.id(), len(entries), list(zip (utility, map(lambda doc: "metric: {} load: {} delay: {} replica: {} neighbour: {}".format(doc.doc_id,  doc['load'], doc['delay'], doc['replica'], doc['neighbour']), entries)))))
        else:
            print ("{:.3f}: {:5s} UTILITY {}".format(self.env.now, self.id(), len(entries)))
            for entry_no, entry in enumerate(entries):
                print("\t\t{:2d}.  doc_id({:2d})  U({:.3f})  {}".format(entry_no+1, entry.doc_id, utility[entry_no], entry))


    # Print announce info
    def print_announce_info(self, announce):
        if Verbose.table == 0:
            pass
        elif Verbose.table == 1:
            print("{:.3f}: {:5s} ANNOUNCE {} / {}".format(self.env.now, self.id(), len(announce), list(zip (map(lambda doc: doc.doc_id, announce), announce))))
        else:
            print("{:.3f}: {:5s} ANNOUNCE count {}".format(self.env.now, self.id(), len(announce)))
            for entry_no, entry in enumerate(announce):
                print("\t\t{:2d}. doc_id({:d})  {}".format(entry_no+1, entry.doc_id, entry))


    # Set the unicast forwarding table
    def set_unicast_forwarding_table(self, list_of_routes):
        """Set the forwarding table"""
        # takes a list of  entries like (destination, next_hop, weight)
        # and coverts into the internal forwarding table format

        for entry in list_of_routes:
            self.unicast_forwarding_table[entry[0]] = entry

    # Get the unicast forwarding table
    def get_unicast_forwarding_table(self):
        """Get the forwarding table"""

        return self.unicast_forwarding_table

    # Get the route to a specific node
    def route_to(self, dst):
        """Get the next hop for a route to a destination"""
        if isinstance(dst, str):
            return self.unicast_forwarding_table[dst][1]
        else:
            return self.unicast_forwarding_table[dst.id()][1]

    # Get the distance to a specific node
    def distance_to(self, dst):
        """Get the distance to a destination"""
        if isinstance(dst, str):
            return self.unicast_forwarding_table[dst][2]
        else:
            return self.unicast_forwarding_table[dst.id()][2]


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

        # add a tuple of (link_end, packet) to the packet store
        self.packet_store.put((link_end, packet))

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
        """What is the weight of the edge from this router to dest"""
        if (dest.id() in self.outgoing_ports):
            link =  self.outgoing_ports[dest.id()].out
            return link.propagation_delay
        else:
            return 0
        
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

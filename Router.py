import simpy
from SimComponents import SwitchPort, PacketSink, Packet
from Link import LinkEnd
from Host import Host
from Verbose import Verbose
from tinydb import TinyDB, Query
from enum import Enum
# importing "collections" for defaultdict
import collections


# the forwarding utility function
def forwarding_utility(alpha, load, delay):
    """ the utility function U=alpha * load + (1-alpha)*delay """
    # we define the utility function U=alpha * load + (1-alpha)*delay
    return alpha * load + (1-alpha) * delay 
    




class Compare(Enum):
    Same = 0
    More = 1
    Less = 2

    def __repr__(self):
        return self.name


LINKRATE = 100


class Router(object):
    """ A Router in the Simulation.
      Requires a put() method as a callback from the PacketGenerator.
    """
    def __init__(self, routerid, env=None):
        self._routerid = routerid
        # create one SimComponent.SwitchPort for each neighbour_id
        self.outgoing_ports = dict()

        # a routing table
        # each entry is { destination: (destination, next_hop, weight) }
        self.routing_table = dict()
        
        # set the simulation environment
        self.set_env(env)

        # a database of metrics
        self.db = TinyDB('/tmp/router-metrics-' + str(routerid) + '.json')
        # the table for metrics
        self.metrics_table = self.db.table('metrics')
        self.metrics_table.truncate()
        # the table for announcements which have been sent
        self.sent_table = self.db.table('sent')
        self.sent_table.truncate()

        # best replica info
        self.best_replica = None
        self.best_utility = -1

        # forwarding table
        self.forwarding_table = dict()
 
        # declaring defaultdict
        # sets default value 'Key Not found' to absent keys
        defd = collections.defaultdict(lambda : None)

        # alpha
        alpha = 0


    def set_env(self,env):
        """ Set the env"""
        self.env = env
        # Create a structure to retrieve packet sent to this router - think consumer (this router) and producer (the one that sent the packet) pattern
        # e.g. https://simpy.readthedocs.io/en/latest/examples/process_communication.html
        self.packet_store = simpy.Store(self.env, capacity=1)

        # create packet sink
        self.sink = PacketSink(env)
        
    def start(self):
        """Start the Router.
        Calls back to the simpy env to start processing"""
        # "Register" the process
        self.env.process(self.run())

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
                print("LinkEnd Exists "  + str(self._routerid) + " --> " + str(neighbour) + " Cancel " +  str(self._routerid) + " --> " + str(neighbour) )

            return ("exists", self.outgoing_ports[neighbour_obj.id()])

        else:
            if Verbose.level >= 1:
                print("LinkEnd Add " + self._routerid + " -> " + "neighbour " + str(neighbour) + " neighbour_obj " + str(neighbour_obj.id()) + " delay " + str(propdelay))

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

    def manage_packet(self, packet_tuple):
        """ Manage a packet.  
        """
        (link_end, packet) = packet_tuple
        
        if packet.dst == self._routerid:
            # packet addressed to me
            # consume the packet

            # pass to the PacketSink which collects arrival information
            # may or may not be useful here
            self.sink.put(packet)


            # a server load info packet
            if getattr(packet, 'type', False) == "ServerLoad":   #  packet.type == "ServerLoad":
                # we got a ServerLoad message
                self.server_load_packet(link_end, packet)

            else:
                # packet for me, but not a ServerLoad
                if Verbose.level >= 1:
                    print("{:.3f}: PACKET {}.{} consumed in {} after {:.3f}".format(self.env.now, packet.src, packet.id, self._routerid, (self.env.now - packet.time)))



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
                self.normal_forwarding_packet(link_end, packet)



    # Is the destination address a service name:  e.g. §a
    def is_service(self, name):
        """Is the destination address a service name:  e.g. §a"""
        if name == None:
            return False
        elif name.startswith("§"):
            return True
        else:
            return False

    # We received a packet of type ServerLoad
    def server_load_packet(self, link_end, packet):
        """The process for a packet with type ServerLoad"""

        if Verbose.level >= 1:
            print("{:.3f}: RECV PACKET '{}' ServerLoad {}.{} ({:.3f}) [{}.{}] managed in {} after {:.3f}".format(self.env.now, self.id(), packet.src, packet.id, packet.time, packet.replica, packet.id, self._routerid, (self.env.now - packet.time)))

        # collect incoming metrics table [servicename, replicaID, metrics (delay, load), original messageID, creation timestamp, last update timestamp, link_received, calculated utility]
        servicename = packet.service
        replica = packet.replica
        msgID = packet.id
        creationTime = packet.time
        metrics = packet.payload

        # holds a doc_id
        update_val = None
        found_in_sent_table = 0

        if Verbose.level >= 1:
            print("{:.3f}: INCOMING VALUES '{}' link_end: {} msgID: {} replica: {} time: {}  service: {} metrics: {}".format(self.env.now, self.id(), str(link_end), msgID, replica, creationTime, servicename, metrics))

        # add the delay of the last hop to the metrics
        metrics['delay'] +=  link_end.propagation_delay


        #
        # NEW:   (link_end, replica) is NOT key for decision
        #
        # never have more than 1 entry for each replica

        # store important data (including metrics) for later use in table
        # (link_end, replica) is key for decision for deleting old data

        # find entry from database for replica
        searchR = Query()
        results = self.metrics_table.search((searchR.replica == replica))

        if Verbose.level >= 1:
            print("{:.3f}: METRIC_SEARCH_RESULTS '{}' link_end: {} replica: {} ==> {}".format(self.env.now, self.id(), link_end, replica, list(zip (map(lambda doc: doc.doc_id, results), results))))
        
        # check results
        if results == []:
            # nothing found - it must be new, so add it
            val = self.metrics_table.insert({'neighbour': link_end.src_node.id(), 'link_end': str(link_end), 'replica': replica, 'msgID': msgID, 'servicename': servicename, 'creationTime': creationTime, 'load': int(metrics['load']), 'no_of_flows': int(metrics['no_of_flows']), 'delay': int(metrics['delay']) })

            if Verbose.level >= 1:
                print ("{:.3f}: ADD METRIC '{}' metric no {}".format(self.env.now, self.id(), val) )

        else:
            # something found in metrics_table

            # check if the new metrics are worse than the found result
            # needs to be done early
            (update_val, found_in_sent_table) = self.check_metrics_worse(metrics, results[0])

            
            # for a specific replica
            # if there is a metric entry with a lower delay,
            # this is a Proxy for determining if it's on the unicast path
            searchD = Query()
            resultsD = self.metrics_table.search((searchD.replica == replica) & (searchD.delay < metrics['delay']))

            if Verbose.level >= 1:
                print("{:.3f}: METRIC_LOWER_DELAY '{}' link_end: {} replica: {} ==> {}".format(self.env.now, self.id(), link_end, replica, list(zip (map(lambda doc: doc.doc_id, results), resultsD))))

            # check results
            if resultsD != []:
                # The incoming delay is higher -- i.e. the existing metric has lower delay
                # then drop incoming msg
                # BUT we might keep them in future labelled DO_NOT_USE
                pass
            else:
                # There is an existing metric entry with an equal or higher delay

                # if they are equal we need to do more checks
                searchE = Query()
                resultsE = self.metrics_table.search((searchE.replica == replica) & (searchE.delay == metrics['delay']))

                # check results
                neighbourVal = None
                linkVal = None
                
                if resultsE != []:
                    # choose one of them
                    # a.  keep the one that's in there  [DOING THIS]
                    # OR b.  select the one with the 'lowest' name
                    print("{:.3f}: METRIC_EQUAL_DELAY '{}' link_end: {} replica: {} ==> {}".format(self.env.now, self.id(), link_end, replica, list(zip (map(lambda doc: doc.doc_id, results), resultsE))))
                    
                else:

                    # then update the metric
                    # replica stays the same
                    # update other values


                    # replica stay the same
                    # update other values
                    val = self.metrics_table.update({ 'neighbour': link_end.src_node.id(), 'link_end': str(link_end), 'msgID': msgID, 'servicename': servicename, 'creationTime': creationTime, 'load': int(metrics['load']), 'delay': int(metrics['delay']) } , doc_ids=[ r.doc_id for r in results ])

                    if Verbose.level >= 1:
                        print("{:.3f}: UPDATE METRIC '{}' metric no {} msgID: {} creationTime: {}  load: {} delay: {}".format(self.env.now, self.id(), val, msgID, creationTime, int(metrics['load']), int(metrics['delay']) ))

                    # clear out sent_table entries for this doc_id
                    self.clear_sent_table(val[0])

                
        # STEP 5,11 forward to appropriate links based on routing information base (fix code below)
        # Now we need to decide which messages go on which links
        # For each entry in the RIB
        #   compare with all the others
        # if any of the metrics is better than that metric in all the other entries
        # announce on all the links that it wasn't received from


        if Verbose.level >= 1:
            self.print_metric_table()


        #  find the entries to announce
        
        announce = self.decide_announcements(self.metrics_table.all())

        if Verbose.level >= 1:
            self.print_announce_info(announce)

        # double check the update_val and found_in_sent_table
        if update_val != None and found_in_sent_table > 0:

            # is update_val already in announce list
            if not (update_val in [ r.doc_id for r in announce ]):
                # it's not in the announce list
                # so collect it and add it
                extra = self.metrics_table.get(doc_id=update_val)

                print("{:.3f}: EXTRA_ANNOUNCE '{}' with {}".format(self.env.now, self.id(), update_val))
                self.print_announce_info([extra])


                announce.append(extra)


            

        if announce:
            # skip through all the announcements
            for metric_no, metric_to_send in enumerate(announce):

                # send to neighbours
                for neighbour in self.outgoing_ports:

                    if Verbose.level >= 3:
                        print("Check " +  metric_to_send['link_end'] +  " <--> " + str(neighbour))

                    if metric_to_send['neighbour'] == str(neighbour):
                        # don't send to where it came from
                        if Verbose.level >= 2:
                            print("{:.3f}: NO RETURN from {} to {} - metric no {}".format(self.env.now, self.id(), neighbour,  metric_to_send.doc_id))
                        pass

                    elif isinstance(self.outgoing_ports[neighbour].out.dst_node,  Host):
                        # don't send to any connected Hosts
                        if Verbose.level >= 2:
                            print("{:.3f}: NOT TO HOST from {} to {} - metric no {}".format(self.env.now, self.id(), self.outgoing_ports[neighbour].out.dst_node, metric_to_send.doc_id))
                        pass

                    else:
                        # a candidate for forwarding
                        
                        if self.check_sent_table(metric_to_send, neighbour):
                            # this is in the sent table, so no need to send
                            if Verbose.level >= 1:
                                print ("{:.3f}: ALREADY IN SENT_TABLE '{}' --> {} - metric no {} msgID {}".format(self.env.now, self.id(), neighbour, metric_to_send.doc_id, metric_to_send['msgID']) )
                            pass
                        else:
                            # send a new packet
                            
                            # create a new packet
                            new_packet = Packet(metric_to_send['creationTime'], 3, metric_to_send['msgID'], self.id(), dst=neighbour)
                            new_packet.type = "ServerLoad"
                            new_packet.service =  metric_to_send['servicename']
                            new_packet.replica = metric_to_send['replica']
                            new_packet.payload = { 'load': metric_to_send['load'], 'no_of_flows': metric_to_send['no_of_flows'], 'delay': metric_to_send['delay'] }

                            # forward the packet
                            if Verbose.level >= 1:
                                print("{:.3f}: FORWARD METRIC {} from {} to {}".format(self.env.now, metric_to_send.doc_id, self.id(), neighbour))

                            # send to relevant SwitchPort
                            self.outgoing_ports[neighbour].put(new_packet)

                            # update sent_table
                            self.update_sent_table(metric_to_send, neighbour)

            print("{:.3f}: ANNOUNCE_END '{}'".format(self.env.now, self.id()))


        #      STEP 6,12 check if fw table needs changing. If yes, change it. Choose the one with best utility function.

        self.choose_best_forwarding_replica(self.metrics_table.all())


    # is the metric arg2 is lower than arg1
    # bigger number is worse
    def metric_is_better(self, arg1, arg2):
        if arg2 == arg1:
            # arg2 is same
            return Compare.Same
        elif arg2 < arg1:
            # arg2 is lower
            return Compare.Less
        else:
            # arg2 is more
            return Compare.More
         
    # is entry j better than entry i, in all metrics
    def  is_better_in_any_metrics(self, j,i):
        metrics =  ['load', 'delay']
        better = [False for m in metrics]

        for index_m, m in enumerate(metrics):
            # skip through each metric by selecting metric m of i and metric m of j
            # print("metric = " + m)
            # we want j[m] to be lower than i[m]
            better[index_m] = self.metric_is_better(i[m], j[m])

            
        if Verbose.level == 3:
            print("better = " + str(better))

        # return value
        if all(v == Compare.Same for v in better):            # ALL the Same
            return Compare.Same

        elif all((v == Compare.Less or v == Compare.Same) for v in better): # ALL Less or Same
            return Compare.Less

        else:
            return Compare.More

    def  is_better_in_all_metrics_orig(self, j,i):
        for m in ['load', 'delay']:
            # skip through each metric by selecting metric m of i and metric m of j
            print("metric = " + m)
            # we want j[m] to be lower than i[m]
            if self.metric_is_better(i[m], j[m]):
                return False
            
        return True

    # decide the entries to announce, given a set of entries
    def decide_announcements(self, entries):
        if len(entries) == 1:
            return [entries[0]]

        else:
            # the list of things to announce
            announce = [False for i in entries]

            for index_i, i in enumerate(entries):
                announce[index_i] = True
                
                for index_j, j in enumerate(entries):

                    
                    if index_i != index_j:

                        better_j_i = self.is_better_in_any_metrics(j,i) 

                        if better_j_i == Compare.Less: # j is better than i in at least 1 metrics 
                            announce[index_i] = False

                            if Verbose.level == 3:
                                print("{:.3f}: j_{} is better than i_{}: {} {}".format(self.env.now, index_j, index_i, self.displayMetrics('j: ', j), self.displayMetrics('i: ', i)))
                        
                            break

                        elif better_j_i == Compare.Same: # j is same in all metrics

                            announce[index_j] = False
                            
                            if Verbose.level == 3:
                                print("{:.3f}: j_{} is same as i_{}: {} {}".format(self.env.now, index_j, index_i, self.displayMetrics('j: ', j), self.displayMetrics('i: ', i)))


                        else:
                            if Verbose.level == 3:
                                print("{:.3f}: j_{} is not better than i_{}: {} {}".format(self.env.now, index_j, index_i, self.displayMetrics('j: ', j), self.displayMetrics('i: ', i)))
                        

            # at this point the announce list should have a True for all the entries to announce
            if Verbose.level == 3:
                print("{:.3f}: announce: {}".format(self.env.now, announce))
            # select those entries which are laballed as True in announce
            return [ entry for ann, entry in zip(announce, entries) if ann == True ]

    # is the newly arrived metrics worse 
    def check_metrics_worse(self, metrics, doc):
        """Returns (doc_id, count in sent_table)"""
        # is it better or worse
        better_j_i = self.is_better_in_any_metrics(metrics, doc)

        if better_j_i == Compare.More:
            # it looks worse

            if Verbose.level >= 2:
                print("{:.3f}: check_worse_metrics {} metric [{}] --> {}".format(self.env.now, str(better_j_i), doc.doc_id, doc))

            # now check the sent table
            sent_query = Query()
            sent_results = self.sent_table.search((sent_query.metric_doc_id == doc.doc_id))

            no_found_in_sent_table = len(sent_results)

            if no_found_in_sent_table > 0:
                # this metric is in the sent table
                if Verbose.level >= 2:
                    print("{:.3f}: is in sent_table: metric [{}] need to resend".format(self.env.now, doc.doc_id))


            return (doc.doc_id, no_found_in_sent_table)
        else:
            return (None, 0)
            # END of check if new metrics are worse than found result

    # display metrics
    def displayMetrics(self, label, metric):
        return "{} replica: {} load: {} delay: {}".format(label, metric['replica'], metric['load'], metric['delay'])


    #  Check if fw table needs changing
    def choose_best_forwarding_replica(self, entries):
        # best_utility=Infinity
        # best replica=1
        # for all replicas i
        #   calculate Utility
        #   if utility(i) < best_utility
        #     best_replica=i
        #     best_utility=utility(i)
        # point fw entry to best replica's announced link end

        self.best_replica = None
        self.best_neighbour = None
        self.best_utility = float('inf')
        self.servicename = None

        # create a list of utility values
        utility = [-1 for e in entries]

        for entry_no, entry in enumerate(entries):
            utility_i = forwarding_utility(self.alpha, entry['load'], entry['delay'])
            utility[entry_no] = utility_i

            #print ("entry_no " + str(entry_no) + " neighbour " + entry['neighbour'] + " utility_i = " + str(utility_i))

            if (utility_i < self.best_utility):
                self.best_replica = entry['replica']
                self.best_neighbour = entry['neighbour']
                self.servicename = entry['servicename']
                self.best_utility = utility_i

        if Verbose.level >= 1:
            self.print_utility_info(entries, utility)
            

        if Verbose.level >= 1:
            if self.best_replica == self.best_neighbour:
                print("{:.3f}: BEST_REPLICA '{}' {} direct ".format(self.env.now, self.id(), self.best_replica))
            else:
                print("{:.3f}: BEST_REPLICA '{}' {} -> {} ".format(self.env.now, self.id(), self.best_replica, self.best_neighbour))

        self.forwarding_table[self.servicename] =  self.best_neighbour

        if Verbose.level >= 1:
            print("{:.3f}: FORWARDING_TABLE '{}' {}".format(self.env.now, self.id(), self.forwarding_table))


    # Handle a ClientRequest
    def client_request_packet(self, link_end, packet):
        """A Client has sent a request"""

        if Verbose.level >= 1:
            print("{:.3f}: RECV PACKET ClientRequest '{}' for service {} pkt: {}".format(self.env.now, self.id(), packet.dst, packet.id))

        # Destination is likely to be a service name: e.g. §a
        service_name = packet.dst

        # First we look up the service name
        neighbour = self.forwarding_table[service_name]

        if Verbose.level >= 2:
            print ("{:.3f}: ClientRequest neighbour =  {}".format(self.env.now, neighbour))

        if neighbour == None:
            # service_name isn't in forwarding_table
            print("{:.3f}: NO FORWARDING_TABLE ENTRY ClientRequest '{}' for service {} pkt: {}".format(self.env.now, self.id(), packet.dst, packet.id))
        else:
            # value is link_end
            # so forwarding the packet
            if Verbose.level >= 1:
                print("{:.3f}: FORWARD PACKET ClientRequest '{}' for service {} pkt: {} send to neighbour {}".format(self.env.now, self.id(), packet.dst, packet.id, neighbour))

            self.outgoing_ports[neighbour].put(packet)                

    # Do normal forwarding
    def normal_forwarding_packet(self, link_end, packet):
         for neighbour in self.outgoing_ports:

             # print("neighbour " + str(self.outgoing_ports[neighbour].out))

             if link_end == None:
                 # looks like a local packet
                 # try and forward it
                 self.outgoing_ports[neighbour].put(packet)

             elif link_end.src_node.id() == neighbour:
                 # don't send to where it came from
                 if Verbose.level >= 2:
                     print("{:.3f}: PACKET {}.{} dont send back from {} to {} after {:.3f}".format(self.env.now, packet.src, packet.id, self.id(), link_end.src_node.id(), (self.env.now - packet.time)))
                 pass

             elif isinstance(self.outgoing_ports[neighbour].out.dst_node,  Host):
                 # don't send to any connected Hosts
                 if Verbose.level >= 2:
                     print("{:.3f}: PACKET {}.{} dont send to host from {} to {} after {:.3f}".format(self.env.now, packet.src, packet.id, self.id(), self.outgoing_ports[neighbour].out.dst_node.id(), (self.env.now - packet.time)))

             else:
                 # forward the packet
                 # send to SwitchPort
                 self.outgoing_ports[neighbour].put(packet)

                 if Verbose.level >= 1:
                     print("{:.3f}: PACKET {}.{} for {} forwarded from {} to {} after {:.3f}".format(self.env.now, packet.src, packet.id, packet.dst, self._routerid, neighbour, (self.env.now - packet.time)))


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
        
        # find entry from sent_table for (doc_id in metrics_table, neighbour)
        sent_query = Query()
        sent_results = self.sent_table.search((sent_query.metric_doc_id == metric_to_send.doc_id) & (sent_query.neighbour == neighbour))

        return sent_results

    # update the sent table
    def update_sent_table(self, metric_to_send, neighbour):
        # add info about the transmission to the sent_table
        # find entry from sent_table for (doc_id in metrics_table, neighbour)
        sent_query = Query()
        sent_results = self.sent_table.search((sent_query.metric_doc_id == metric_to_send.doc_id) & (sent_query.neighbour == neighbour))

        #if Verbose.level >= 1:
        #    print("{:.3f}: SENT_TABLE '{}'  ==> {} ".format(self.env.now, self.id(), sent_results))
            
        # check results
        if sent_results == []:
            # nothing found - it must be new, so add it
            val = self.sent_table.insert({'metric_doc_id': metric_to_send.doc_id, 'neighbour': neighbour })

            if Verbose.level >= 1:
                print ("{:.3f}: ADD SENT_TABLE '{}' metric no {} neighbour {}".format(self.env.now, self.id(), metric_to_send.doc_id, neighbour) )

        else:
            # update the table
            if Verbose.level >= 1:
                print ("{:.3f}: UPDATE SENT_TABLE '{}' metric no {} neighbour {}".format(self.env.now, self.id(), metric_to_send.doc_id, neighbour) )



    # clear entries in sent table
    def clear_sent_table(self, metric_doc_id):
        """Clear entries in sent table with 'metric_doc_id'"""
        
        if Verbose.level >= 1:
            print ("{:.3f}: CLEAR SENT_TABLE '{}' metric no {}".format(self.env.now, self.id(), metric_doc_id) )

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
            print("{:.3f}: METRIC_TABLE '{}' {}".format(self.env.now, self.id(), str(self.metrics_table.all())))
        else:
            print("{:.3f}: METRIC_TABLE '{}'".format(self.env.now, self.id()))
            for metric_no, metric in enumerate(self.metrics_table.all()):
                print("       {:2d}  {}".format(metric_no+1, metric))


    # Print utility info
    def print_utility_info(self, entries, utility):
        if Verbose.table == 0:
            print ("{:.3f}: UTILITY '{}' = {} ".format(self.env.now, self.id(), list(zip (utility, map(lambda doc: "metric: {} load: {} delay: {} replica: {} neighbour: {}".format(doc.doc_id,  doc['load'], doc['delay'], doc['replica'], doc['neighbour']), entries)))))
        else:
            print ("{:.3f}: UTILITY '{}'".format(self.env.now, self.id()))
            for entry_no, entry in enumerate(entries):
                print("       {:2d}  ({})  {}".format(entry.doc_id, utility[entry_no], entry))


    # Print announce info
    def print_announce_info(self, announce):
        if Verbose.table == 0:
            print("{:.3f}: ANNOUNCE '{}' : {} / {}".format(self.env.now, self.id(), len(announce), list(zip (map(lambda doc: doc.doc_id, announce), announce))))
        else:
            print("{:.3f}: ANNOUNCE '{}' count {}".format(self.env.now, self.id(), len(announce)))
            for entry_no, entry in enumerate(announce):
                print("       {:2d}  {}".format(entry.doc_id, entry))

                # list(zip (map(lambda doc: doc.doc_id, announce), announce))))

    # Set the routing table
    def set_routing_table(self, list_of_routes):
        """Set the routing table"""
        # takes a list of  entries like (destination, next_hop, weight)
        # and coverts into the internal routing table format

        for entry in list_of_routes:
            self.routing_table[entry[0]] = entry

    # Get the routing table
    def get_routing_table(self):
        """Get the routing table"""

        return self.routing_table

    # Get the route to a specific node
    def route_to(self, dst):
        """Get the next hop for a route to a destination"""
        if isinstance(dst, str):
            return self.routing_table[dst][1]
        else:
            return self.routing_table[dst.id()][1]

    # Get the distance to a specific node
    def distance_to(self, dst):
        """Get the distance to a destination"""
        if isinstance(dst, str):
            return self.routing_table[dst][2]
        else:
            return self.routing_table[dst.id()][2]


    def recv(self, packet, link_end):
        """A packet is received from a LinkEnd of a neighbouring Router.
        """
        # this function should be called by the previous hop to send a packet to this router
        # packet_store is a simpy.Store(self.env, capacity=1)
        if packet.src == self._routerid:
            if Verbose.level >= 1:
                print("{:.3f}: PACKET {}.{} ({:.3f}) created in {} after {:.3f}".format(self.env.now,
                packet.src, packet.id, packet.time, self._routerid, (self.env.now - packet.time)))
        else:
            if Verbose.level >= 1:
                print("{:.3f}: PACKET {}.{} ({:.3f}) arrived in {} from {} after {:.3f}".format(self.env.now, packet.src, packet.id, packet.time, self._routerid, link_end.src_node.id(), (self.env.now - packet.time)))

        # add a tuple of (link_end, packet) to the packet store
        self.packet_store.put((link_end, packet))

    def neighbours(self):
        """Neighbours of Router"""
        return list(self.outgoing_ports.keys())

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

    def __str__(self):
        return "Router " + str(self._routerid) 

    def __repr__(self):
        return "Router " + str(self._routerid) 

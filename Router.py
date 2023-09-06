import simpy
from SimComponents import SwitchPort, PacketSink, Packet
from Link import LinkEnd
from Host import Host
from Verbose import Verbose
from Utility import Utility
from Server import ServerLoadMessageType
from tinydb import TinyDB, Query
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


def less_than1(x,y):
    return x < y

def greater_than1(x,y):
    return x > y


class Router(object):
    """ A Router in the Simulation.
      Requires a put() method as a callback from the PacketGenerator.
    """

    # forwarding utility change factor  10% -> 0.1
    forwarding_utility_change_factor = 0.1

    # The following staticmethods can be reset from the outside
    # to change the behaviour of the algorithms

    # default better than fn
    
    # dict of better than fns
    better_than_fn_dict = {}
    better_than_fn_dict['load'] = staticmethod(less_than1)
    better_than_fn_dict['delay'] = staticmethod(less_than1)

    better_than_fn = staticmethod(less_than1)



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
        self.db = TinyDB('/tmp/router-metrics-' + str(routerid) + '.json')
        
        # the table for metrics
        self.service_RIB = self.db.table('metrics')
        self.service_RIB.truncate()
        
        # the table for announcements which have been sent
        self.sent_table = self.db.table('sent')
        self.sent_table.truncate()

        # best replica info
        self.best_replica = None
        self.best_utility = -float('inf')

        # service forwarding table
        self.service_forwarding_table = dict()
 
        # declaring defaultdict
        # sets default value 'Key Not found' to absent keys
        defd = collections.defaultdict(lambda : None)

        # setup metrics list
        # name and better function
        self.metric_list =  [
            { 'name': 'load',  'better': Router.better_than_fn },
            { 'name': 'delay', 'better': Router.better_than_fn }   ]
    


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
            if getattr(packet, 'type', False) == "ServerLoad":   #  packet.type == "ServerLoad":
                # we got a ServerLoad message
                self.server_load_packet(link_end, packet)

            else:
                # packet for me, but not a ServerLoad
                if Verbose.level >= 1:
                    print("{:.3f}: PACKET {}.{}  ({:.3f}) consumed in {} after {:.3f}".format(self.env.now, packet.src, packet.pkt_no, packet.time, self._routerid, (self.env.now - packet.time)))



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
            print("{:.3f}: RECV PACKET '{}' ServerLoad {} {}.{} ({:.3f}) [{}.{}] managed in {} after {:.3f}".format(self.env.now, self.id(), packet.operation, packet.src, packet.pkt_no, packet.time, packet.replica, packet.id, self._routerid, (self.env.now - packet.time)))

        # collect incoming metrics table [servicename, replicaID, metrics (delay, load), original messageID, creation timestamp, last update timestamp, link_received, calculated utility]
        servicename = packet.service
        replica = packet.replica
        msgID = packet.id
        creationTime = round(packet.time, 6)
        metrics = packet.payload
        operation = ServerLoadMessageType.from_val(packet.operation)


        if Verbose.level >= 1:
            print("{:.3f}: INCOMING VALUES '{}' link_end: {} msgID: {} replica: {} time: {}  service: {} op: {} metrics: {}".format(self.env.now, self.id(), str(link_end), msgID, replica, creationTime, servicename, operation, metrics))

        # add the delay of the last hop to the metrics
        metrics['delay'] +=  link_end.propagation_delay


        # If the announcement has arrived on a link that is not the one
        # in the forwarding table, for the replica then Drop the message
        valid_route = self.arrived_from_unicast_route(replica, link_end)

        if Verbose.level >= 1:
            print("{:.3f}: UNICAST_ROUTE '{}' for {} from {} --> {} ".format(self.env.now, self.id(), replica, link_end.src_node.id(), 'VALID' if valid_route else 'INVALID'))

        if not valid_route:
            return

        # did the ServerLoad come from a direct neighbour
        if self.is_neighbour(packet.replica):
            print("IS_NEIGHBOUR: " + packet.replica)
        else:
            print("NOT_NEIGHBOUR: " + packet.replica)
            
        # process the incoming packet
        if (operation == ServerLoadMessageType.Announce):
            # it's an announcement
            self.server_load_packet_announce(link_end, packet)
            
        elif (operation == ServerLoadMessageType.Withdraw):
            # it's a withdrawal
            self.server_load_packet_withdraw(link_end, packet)
        else:
            pass    



    # We received a packet of type ServerLoad Announcement
    def server_load_packet_announce(self, link_end, packet):
        # collect incoming metrics table [servicename, replicaID, metrics (delay, load), original messageID, creation timestamp, last update timestamp, link_received, calculated utility]
        servicename = packet.service
        replica = packet.replica
        msgID = packet.id
        creationTime = round(packet.time, 6)
        metrics = packet.payload
        operation = ServerLoadMessageType.from_val(packet.operation)

        # marked for later use
        marked  = None
        
        #
        # never have more than 1 entry for each replica

        # store important data (including metrics) for later use in table
        # 'replica' is key for decision for deleting old data

        # If there is an existing entry in the service RIB 
        # so find entry from database for replica
        searchR = Query()
        results = self.service_RIB.search((searchR.replica == replica))

        if Verbose.level >= 1:
            print("{:.3f}: METRIC_SEARCH_RESULTS '{}' link_end: {} replica: {} ==> {}".format(self.env.now, self.id(), link_end, replica, list(zip (map(lambda doc: doc.doc_id, results), results))))
        
        # check results
        # If there is NO existing entry in the service RIB
        if results == []:
            # nothing found - it must be new, so add it
            val = self.service_RIB.insert({ 'replica': replica, 'neighbour': link_end.src_node.id(), 'link_end': str(link_end), 'msgID': msgID, 'servicename': servicename, 'creationTime': creationTime, 'load': int(metrics['load']), 'no_of_flows': int(metrics['no_of_flows']), 'delay': int(metrics['delay']), 'slots': metrics['slots']  })

            if Verbose.level >= 1:
                print ("{:.3f}: ADD METRIC '{}' metric no {}".format(self.env.now, self.id(), val) )

        else:
            # something found in service_RIB

            # existing entry is newer than the incoming update
            searchT = Query()
            resultsT = self.service_RIB.search((searchT.replica == replica) & (searchT.creationTime > creationTime))

            # check results
            if resultsT != []:
                # we found an entry with a newer time
                if Verbose.level >= 1:
                    print("{:.3f}: METRIC_TOO_OLD '{}' link_end: {} replica: {} ==> {}".format(self.env.now, self.id(), link_end, replica, list(zip (map(lambda doc: doc.doc_id, results), resultsT))))
                    
                return

            # Update the metrics in the existing RIB entry

            # replica stay the same
            # update other values
            val = self.service_RIB.update({ 'neighbour': link_end.src_node.id(), 'link_end': str(link_end), 'msgID': msgID, 'servicename': servicename, 'creationTime': creationTime, 'load': int(metrics['load']), 'no_of_flows': int(metrics['no_of_flows']), 'delay': int(metrics['delay']), 'slots': metrics['slots'] } , doc_ids=[ r.doc_id for r in results ])

            if Verbose.level >= 1:
                print("{:.3f}: UPDATE METRIC '{}' metric no {} msgID: {} creationTime: {:.6f}  load: {} delay: {}".format(self.env.now, self.id(), val, msgID, creationTime, int(metrics['load']), int(metrics['delay']) ))

            # mark this doc_id, if in sent_table
            # val[0] is a doc_id
            sent_query = Query()
            sent_results = self.sent_table.search(sent_query.metric_doc_id == val[0])

            if sent_results != []:
                # it is in the sent_table
                metric = self.service_RIB.get(doc_id=val[0])
                marked = metric
                print("{:.3f}: MARK METRIC '{}' {}".format(self.env.now, self.id(), metric['replica']))

                
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
            if Verbose.level >= 2:
                print("    >>> sent_set " + str(len(sent_set)) + " " + str(sent_set))

        # announce set are those in decide_pbr and not in sent
        # plus the marked one, if it is in the decide_pbr

        marked_set = [marked] if marked in decide_pbr else []

        if marked_set:
            if Verbose.level >= 2:
                print("    >>> marked_set " + str(len(marked_set)) + " " + str(marked_set))
                
        announce_set = [m for m in decide_pbr if m.doc_id not in [ s.doc_id for s in sent_set ]] + marked_set


        # use all of them and label announce entries to have message type Announce
        announce = list(zip(announce_set, itertools.repeat(ServerLoadMessageType.Announce)))

        if announce:
            if Verbose.level >= 2:
                print("    >>> announce_set " + str(len(announce)) + " " + str(announce))


        # withdraw set are those in sent_table minus those in decide_pbr
        withdraw_set = [s for s in sent_set if s.doc_id not in [ d.doc_id for d in decide_pbr ]]
        
        # label withdraw_set entries to have message type Withdraw
        withdraw = list(zip(withdraw_set, itertools.repeat(ServerLoadMessageType.Withdraw)))
                     
        if withdraw:
            if Verbose.level >= 2:
                print("    >>> withdraw_set " + str(len(withdraw)) + " " + str(withdraw))
            

        # if there is a metric in the marked_set
        # we need to clear it from the sent_table
        if marked_set != []:
            # delete from sent_table for marked
            self.clear_sent_table(marked_set[0].doc_id)


        #  announce the metrics if announce or withdraw has entries
            

        if announce or withdraw:
            self.announce_metrics(announce + withdraw)


        if Verbose.level >= 1:
            self.print_sent_table()


        # STEP 6,12 check if fw table needs changing. If yes, change it. Choose the one with best utility function.

        self.choose_best_forwarding_replica(self.service_RIB.all())

        

    # We received a packet of type ServerLoad Withdraw
    def server_load_packet_withdraw(self, link_end, packet):
        # collect incoming metrics table [servicename, replicaID, metrics (delay, load), original messageID, creation timestamp, last update timestamp, link_received, calculated utility]
        servicename = packet.service
        replica = packet.replica
        msgID = packet.id
        creationTime = round(packet.time, 6)
        metrics = packet.payload
        operation = ServerLoadMessageType.from_val(packet.operation)

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
            if Verbose.level >= 1:
                print("{:.3f}: WITHDRAW_SEARCH_RESULTS '{}' link_end: {} replica: {} ==> {}".format(self.env.now, self.id(), link_end, replica, list(zip (map(lambda doc: doc.doc_id, results), results))))

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
                print("{:.3f}: NOTHING in sent_table: '{}' for {}".format(self.env.now, self.id(), candidate.doc_id))

                # now delete the candidate metric from the RIB
                self.delete_rib_entry(candidate)

                self.print_metric_table()
            
            else:
                # this metric is in the sent table
                if Verbose.level >= 2:
                    print("{:.3f}: {} in sent_table: '{}' metric [{}] need to withdraw".format(self.env.now, no_found_in_sent_table, self.id(), candidate.doc_id))

            
                # do we need any withdrawal announcements
                for sent_entry in sent_results:
                    #print("link_end = " + str(link_end) + " sent_entry = " + str(sent_entry))

                    neighbour = sent_entry['neighbour']

                    # check link_end
                    if link_end.src_node.id() == neighbour:
                        # don't send to where it came from
                        if Verbose.level >= 2:
                            print("{:.3f}: WITHDRAW PACKET {}.{} dont send back from {} to {} ".format(self.env.now, packet.src, packet.pkt_no, self.id(), link_end.src_node.id()))
                        pass

                    else:
                        # create a new packet
                        new_packet = self.metric_to_packet(candidate, ServerLoadMessageType.Withdraw, neighbour)

                        self.pkt_no += 1

                        # forward the packet
                        if Verbose.level >= 1:
                            print("{:.3f}: WITHDRAW FORWARD {} from {} to {}".format(self.env.now, candidate['replica'], self.id(), neighbour))

                        # send to relevant SwitchPort
                        self.outgoing_ports[neighbour].put(new_packet)


                # whatever the previous decision
                # clear sent_table for this metric
                self.clear_sent_table(candidate.doc_id)

                #self.print_sent_table()

                # now delete the candidate metric from the RIB
                self.delete_rib_entry(candidate)

                self.print_metric_table()

            print("{:.3f}: WITHDRAW END".format(self.env.now))
        



    # Announce the entries
    # Consider some specific limits and caveats
    # e.g. announce on all the links that it wasn't received from
    def announce_metrics(self, announcements):
                
        # skip through all the announcements
        for metric_no, metric_to_send_tuple in enumerate(announcements):

            # unpick metric and force from the tuple
            metric_to_send, msg_type = metric_to_send_tuple

            # print("{:.3f}: Check {} - metric no {} {} announcement {} withdraw {}".format(self.env.now, self.id(),  metric_to_send.doc_id, msg_type, msg_type == ServerLoadMessageType.Announce, msg_type == ServerLoadMessageType.Withdraw))

            # send to neighbours
            for neighbour in self.outgoing_ports:

                # print("Check " +  metric_to_send['link_end'] +  " <--> " + str(neighbour))

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

                    # check if it is an Announcement or a Withdraw

                    if msg_type == ServerLoadMessageType.Announce:
                        # Announce

                        if self.check_sent_table(metric_to_send, neighbour):
                            # this is in the sent table, so no need to send
                            if Verbose.level >= 1:
                                print ("{:.3f}: ALREADY IN SENT_TABLE {} neighbour {} - metric no {} msgID {}".format(self.env.now, self.id(), neighbour, metric_to_send.doc_id, metric_to_send['msgID']) )
                                pass


                        else:
                            # send a new packet

                            # create a new packet
                            new_packet = self.metric_to_packet(metric_to_send, msg_type, neighbour)

                            self.pkt_no += 1

                            # forward the packet
                            if Verbose.level >= 1:
                                print("{:.3f}: FORWARD METRIC {} from {} to {}".format(self.env.now, metric_to_send.doc_id, self.id(), neighbour))

                            # send to relevant SwitchPort
                            self.outgoing_ports[neighbour].put(new_packet)

                            # update sent_table
                            self.update_sent_table(metric_to_send, neighbour)

                    elif msg_type == ServerLoadMessageType.Withdraw:
                        # Withdraw
                        
                        if self.check_sent_table(metric_to_send, neighbour):
                            # this is in the sent table, so send withdraw

                            # send a new packet

                            # create a new packet
                            new_packet = self.metric_to_packet(metric_to_send, msg_type, neighbour)

                            self.pkt_no += 1

                            # forward the packet
                            if Verbose.level >= 1:
                                print("{:.3f}: FORWARD WITHDRAW {} from {} to {}".format(self.env.now, metric_to_send.doc_id, self.id(), neighbour))

                            # send to relevant SwitchPort
                            self.outgoing_ports[neighbour].put(new_packet)

                        else:
                            # not in sent_table, so no need to send Withdraw
                            if Verbose.level >= 1:
                                print ("{:.3f}: NOT IN SENT_TABLE {} neighbour {} - metric no {} msgID {}".format(self.env.now, self.id(), neighbour, metric_to_send.doc_id, metric_to_send['msgID']) )

                            pass
                    else:
                        print("UNKNOWN ServerLoadMessageType " + msg_type)
                
            # if the msg_type is Withdraw, clear sent_table
            if msg_type == ServerLoadMessageType.Withdraw:
                # delete from sent_table
                self.clear_sent_table(metric_to_send.doc_id)


        print("{:.3f}: ANNOUNCE_END '{}'".format(self.env.now, self.id()))

        
    # Create a new packet from a metric
    def metric_to_packet(self, metric_to_send, msg_type, neighbour):
        new_packet = Packet(metric_to_send['creationTime'], 3, metric_to_send['msgID'], self.id(), dst=neighbour)
        new_packet.type = "ServerLoad"
        new_packet.operation = msg_type.to_val()
        new_packet.service =  metric_to_send['servicename']
        new_packet.replica = metric_to_send['replica']
        new_packet.pkt_no =  self.pkt_no
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
    def metric_is_better(self, arg1, arg2, better_fn):
        if arg2 == arg1:
            # arg2 is same
            return Compare.Same
        elif better_fn(arg2, arg1):
            # arg2 is better
            return Compare.Better
        else:
            # arg2 is worse
            return Compare.Worse
         
    # is entry j better than entry i, in all metrics
    def  is_better_in_any_metrics(self, j,i):
        # results list for better-ness
        better = [False for m in self.metric_list]

        for index_m, m_dict in enumerate(self.metric_list):
            # m_dict has the name of the metric and the better-ness function
            m = m_dict['name']
            fn = m_dict['better']
            
            # print("metric = " + m)

            # skip through each metric by selecting metric m of i and metric m of j
            # we want j[m] to be better than i[m]
            better[index_m] = self.metric_is_better(i[m], j[m], fn)

            
            if Verbose.level == 4:
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

                            if Verbose.level == 3:
                                print("Compare.Better: j_{} is better than i_{}: {} {}".format(index_j, index_i, self.displayMetrics('j: ', j), self.displayMetrics('i: ', i)))
                        
                            break

                        elif better_j_i == Compare.Same: # j is same in all metrics

                            # so we don't need j
                            announce[index_j] = False
                            
                            if Verbose.level == 3:
                                print("Compare.Same: j_{} is same as i_{}: {} {}".format(index_j, index_i, self.displayMetrics('j: ', j), self.displayMetrics('i: ', i)))


                        else:
                            # we keep i
                            if Verbose.level == 3:
                                print("Compare.Worse: j_{} is not better than i_{}: {} {}".format(index_j, index_i, self.displayMetrics('j: ', j), self.displayMetrics('i: ', i)))
                        

            # at this point the announce list should have a True for all the entries to announce
            if Verbose.level == 3:
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
    def call_forwarding_utility(self, alpha, load, delay):
        return Utility.forwarding_utility_fn(alpha, load, delay)

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

        print ("choose_best_forwarding_replica: '" + self.id() + "' best " + str(self.best_replica) + " utility " + str(self.best_utility) )

        old_best_replica = self.best_replica
        old_best_utility = self.best_utility

        this_best_replica = None
        this_best_neighbour = None
        this_best_utility = float('inf')
        this_servicename = None

        # create a list of utility values
        utility = [-1 for e in entries]

        for entry_no, entry in enumerate(entries):
            utility_i = self.call_forwarding_utility(Utility.alpha, entry['load'], entry['delay'])
            utility[entry_no] = utility_i

            print ("choose_best_forwarding_replica: '" + self.id() + "' entry_no " + str(entry_no) + " neighbour " + entry['neighbour'] + " utility_i = " + str(utility_i))

            # is utility of this entry < current best utility 
            if (utility_i < this_best_utility):
                # update best replica data
                this_best_replica = entry['replica']
                this_best_neighbour = entry['neighbour']
                this_servicename = entry['servicename']
                this_best_utility = utility_i

        if Verbose.level >= 1:
            self.print_utility_info(entries, utility)



        # 5. Choose best replica for the forwarding plane/
        #
        # Currently send to the one target held in Service Forwarding Table.
        # We may want to dampen the changes in the Service Forwarding Table
        # so that we don't scatter requests to multiple servers.
        # Avoids flapping.  The damping may be based on a value threshold or a time window.
        
        # we check if the difference to make sure it is big enough
        diff = self.calculate_utility_difference(this_best_utility, old_best_utility)

                
        # check how much of a change in there is
        if (old_best_replica != this_best_replica):
            # different replicas
            
            if (diff == 0):
                # no change, do nothing

                print("{:.3f}: CHOOSE_BEST_REPLICA: '{}' U_old({}, {}) U_new({}, {}) diff({} {} {}) {} {} to {}".format(self.env.now, self.id(), old_best_utility, old_best_replica, this_best_utility, this_best_replica, "", "0", "", " do not change ", old_best_replica, this_best_replica ))

            elif (diff < Router.forwarding_utility_change_factor):
                # change is too small, do nothing

                print("{:.3f}: CHOOSE_BEST_REPLICA: '{}' U_old({}, {}) U_new({}, {}) diff({} {} {}) {} {} to {}".format(self.env.now, self.id(), old_best_utility, old_best_replica, this_best_utility, this_best_replica, diff, "<", Router.forwarding_utility_change_factor, " do not change ", old_best_replica, this_best_replica ))

            else:
                # change replica

                print("{:.3f}: CHOOSE_BEST_REPLICA: '{}' U_old({}, {}) U_new({}, {}) diff({} {} {}) {} {} to {}".format(self.env.now, self.id(), old_best_utility, old_best_replica, this_best_utility, this_best_replica, diff, ">", Router.forwarding_utility_change_factor, " change ", old_best_replica, this_best_replica ))

                self.best_replica = this_best_replica
                self.best_neighbour = this_best_neighbour
                self.servicename = this_servicename 
                self.best_utility = this_best_utility
        else:
            # same replica - maype update values for this replica

            if (diff == 0):
                # no change, do nothing

                print("{:.3f}: CHOOSE_BEST_REPLICA: '{}' U_old({}, {}) U_new({}, {}) diff({} {} {}) {} {}".format(self.env.now, self.id(), old_best_utility, old_best_replica, this_best_utility, this_best_replica, "", "0", "", " do not update ", old_best_replica ))

            elif (diff < Router.forwarding_utility_change_factor):
                # change is too small, do nothing

                print("{:.3f}: CHOOSE_BEST_REPLICA: '{}' U_old({}, {}) U_new({}, {}) diff({} {} {}) {} {}".format(self.env.now, self.id(), old_best_utility, old_best_replica, this_best_utility, this_best_replica, diff, "<", Router.forwarding_utility_change_factor, " do not update ", old_best_replica ))


            else:
                # update utility for this replica
                
                print("{:.3f}: CHOOSE_BEST_REPLICA: '{}' U_old({}, {}) U_new({}, {}) diff({} {} {}) {} {}".format(self.env.now, self.id(), old_best_utility, old_best_replica, this_best_utility, this_best_replica, diff, ">", Router.forwarding_utility_change_factor, " update ", old_best_replica ))


                self.best_utility = this_best_utility



        if Verbose.level >= 1:
            if self.best_replica == self.best_neighbour:
                print("{:.3f}: {}BEST_REPLICA '{}' {} direct ".format(self.env.now, ("CHANGED " if old_best_replica != self.best_replica else ""), self.id(), self.best_replica))
            else:
                print("{:.3f}: {}BEST_REPLICA '{}' {} -> {} ".format(self.env.now, ("CHANGED " if old_best_replica != self.best_replica else ""), self.id(), self.best_replica, self.best_neighbour))

        self.service_forwarding_table[self.servicename] =  self.best_neighbour

        if Verbose.level >= 1:
            print("{:.3f}: SERVICE_FORWARDING_TABLE '{}' {}".format(self.env.now, self.id(), self.service_forwarding_table))


    # Work out utility difference from self.best_utility
    def calculate_utility_difference(self, utility, best_utility):
        diff = utility - best_utility 

        return round(abs(diff), 4)

    # Handle a ClientRequest
    def client_request_packet(self, link_end, packet):
        """A Client has sent a request"""

        if Verbose.level >= 1:
            print("{:.3f}: RECV PACKET '{}' ClientRequest {}.{} ({:.3f}) [{}.{}]  for service {} pkt: {} after {:.3f}".format(self.env.now, self.id(), packet.src, packet.pkt_no, packet.time, packet.src, packet.id, packet.dst, packet.id, (self.env.now - packet.time)))

        # Destination is likely to be a service name: e.g. §a
        service_name = packet.dst

        # Check if we know that service name
        if not service_name in self.service_forwarding_table:
            # service_name isn't in service_forwarding_table
            print("{:.3f}: NO SERVICE_FORWARDING_TABLE ENTRY ClientRequest '{}' for service {} pkt: {}.{}".format(self.env.now, self.id(), packet.dst, packet.src, packet.pkt_no))

        else:
            # First we look up the service name
            neighbour = self.service_forwarding_table[service_name]

            if Verbose.level >= 2:
                print ("{:.3f}: ClientRequest neighbour =  {}".format(self.env.now, neighbour))

            if neighbour == None:
                # service_name is in service_forwarding_table, but has no value
                print("{:.3f}: NO VALUE FOR SERVICE_FORWARDING_TABLE ENTRY ClientRequest '{}' for service {} pkt: {}".format(self.env.now, self.id(), packet.dst, packet.id))
            else:
                # value is link_end
                # so forwarding the packet
                if Verbose.level >= 1:
                    print("{:.3f}: FORWARD PACKET ClientRequest '{}' for service {} pkt: {} send to neighbour {}".format(self.env.now, self.id(), packet.dst, packet.id, neighbour))

                self.outgoing_ports[neighbour].put(packet)                

    # Do normal forwarding
    def normal_forwarding_packet(self, link_end, packet):
        
        if packet.dst == None:
            # dont forward to None
            if Verbose.level >= 2:
                print("{:.3f}: PACKET {}.{} for {} NO forward from {} to {} after {:.3f}".format(self.env.now, packet.src, packet.pkt_no, packet.dst, self._routerid, packet.dst, (self.env.now - packet.time)))

        else:
            # forward the packet using unicast_forwarding_table
             
            # unicast_forwarding_table entries look like:  's1': ('s1', 'b', 3)

            # get the Dijkstra link for the destination
            if packet.dst in self.unicast_forwarding_table:

                neighbour = self.route_to(packet.dst)
                
                if link_end.src_node.id() == neighbour:
                    # don't send to where it came from
                    if Verbose.level >= 2:
                        print("{:.3f}: PACKET {}.{} dont send back from {} to {} after {:.3f}".format(self.env.now, packet.src, packet.pkt_no, self.id(), link_end.src_node.id(), (self.env.now - packet.time)))


                elif isinstance(self.outgoing_ports[neighbour].out.dst_node,  Host):
                    # don't send to any connected Hosts
                    if Verbose.level >= 2:
                        print("{:.3f}: PACKET {}.{} dont send to host from {} to {} after {:.3f}".format(self.env.now, packet.src, packet.pkt_no, self.id(), self.outgoing_ports[neighbour].out.dst_node.id(), (self.env.now - packet.time)))

                else:
                    # forward the packet
                    # send to SwitchPort
                    self.outgoing_ports[neighbour].put(packet)

                    if Verbose.level >= 1:
                        print("{:.3f}: PACKET {}.{} for {} forwarded from {} to {} after {:.3f}".format(self.env.now, packet.src, packet.pkt_no, packet.dst, self._routerid, neighbour, (self.env.now - packet.time)))


            else:
                # not in unicast_forwarding_table
                if Verbose.level >= 1:
                    print("{:.3f}: PACKET {}.{} for {} FAILURE at {} ".format(self.env.now, packet.src, packet.pkt_no, packet.dst, self._routerid))

                    print(str(self.unicast_forwarding_table))
        


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
        if Verbose.level >= 1:
            print ("{:.3f}: REMOVE METRIC '{}' metric no {}".format(self.env.now, self.id(), metric) )
        
    # update the sent table
    def update_sent_table(self, metric_to_send, neighbour):
        # add info about the transmission to the sent_table
        # find entry from sent_table for (doc_id in service_RIB, neighbour)
        sent_query = Query()
        sent_results = self.sent_table.search((sent_query.metric_doc_id == metric_to_send.doc_id) & (sent_query.neighbour == neighbour))

        #if Verbose.level >= 1:
        #    print("{:.3f}: SENT_TABLE_SEARCH '{}'  ==> {} ".format(self.env.now, self.id(), sent_results))
            
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
            print("{:.3f}: METRIC_TABLE '{}' {}".format(self.env.now, self.id(), str(self.service_RIB.all())))
        else:
            print("{:.3f}: METRIC_TABLE '{}'".format(self.env.now, self.id()))
            for metric_no, metric in enumerate(self.service_RIB.all()):
                print("       {:2d}. doc_id({:d})  {}".format(metric_no+1, metric.doc_id, metric))


    def print_sent_table(self):
        if Verbose.table == 0:
            print("{:.3f}: SENT_TABLE '{}' {}".format(self.env.now, self.id(), str(self.sent_table.all())))
        else:
            print("{:.3f}: SENT_TABLE '{}'".format(self.env.now, self.id()))
            for entry_no, entry in enumerate(self.sent_table.all()):
                metric = self.service_RIB.get(doc_id=entry['metric_doc_id'])
                print("       {:2d}. replica: {} {}".format(entry_no+1, metric['replica'], entry))


    # Print utility info
    def print_utility_info(self, entries, utility):
        if Verbose.table == 0:
            print ("{:.3f}: UTILITY '{}' {} = {} ".format(self.env.now, self.id(), len(entries), list(zip (utility, map(lambda doc: "metric: {} load: {} delay: {} replica: {} neighbour: {}".format(doc.doc_id,  doc['load'], doc['delay'], doc['replica'], doc['neighbour']), entries)))))
        else:
            print ("{:.3f}: UTILITY '{}' {}".format(self.env.now, self.id(), len(entries)))
            for entry_no, entry in enumerate(entries):
                print("        {:2d}.  doc_id({:2d})  U({:.3f})  {}".format(entry_no+1, entry.doc_id, utility[entry_no], entry))


    # Print announce info
    def print_announce_info(self, announce):
        if Verbose.table == 0:
            print("{:.3f}: ANNOUNCE '{}' : {} / {}".format(self.env.now, self.id(), len(announce), list(zip (map(lambda doc: doc.doc_id, announce), announce))))
        else:
            print("{:.3f}: ANNOUNCE '{}' count {}".format(self.env.now, self.id(), len(announce)))
            for entry_no, entry in enumerate(announce):
                print("       {:2d}. doc_id({:d})  {}".format(entry_no+1, entry.doc_id, entry))


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
            if Verbose.level >= 1:
                print("{:.3f}: PACKET {}.{} ({:.3f}) created in {} after {:.3f}".format(self.env.now,
                packet.src, packet.pkt_no, packet.time, self._routerid, (self.env.now - packet.time)))
        else:
            if Verbose.level >= 1:
                print("{:.3f}: PACKET {}.{} ({:.3f}) arrived in {} from {} after {:.3f}".format(self.env.now, packet.src, packet.pkt_no, packet.time, self._routerid, link_end.src_node.id(), (self.env.now - packet.time)))

        # add a tuple of (link_end, packet) to the packet store
        self.packet_store.put((link_end, packet))

    def neighbours(self):
        """Neighbours of Router"""
        return list(self.outgoing_ports.keys())

    def is_neighbour(self, node):
        """Is neighbour of a Router"""
        keys = self.outgoing_ports.keys()
        print("is_neighbour keys = " + str(keys) + " node " + str(node))
        return node in keys

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

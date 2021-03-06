import simpy
from SimComponents import SwitchPort, PacketSink, Packet
from Link import LinkEnd
from Host import Host
from Verbose import Verbose
from tinydb import TinyDB, Query

LINKRATE = 100

class Router(object):
    """ A Router in the Simulation.
      Requires a put() method as a callback from the PacketGenerator.
    """
    def __init__(self, routerid, env=None):
        self._routerid = routerid
        # create one SimComponent.SwitchPort for each neighbour_id
        self.outgoing_ports = dict()

        # a database of metrics
        self.db = TinyDB('/tmp/router-metrics-' + str(routerid) + '.json')
        self.metrics_table = self.db.table('metrics')
        self.metrics_table.truncate()
        
        self.set_env(env)

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
            self.sink.put(packet)


            # a server load info packet
            if packet.type == "ServerLoad":
                # we got a ServerLoad message
                self.server_load_packet(link_end, packet)

            else:
                # packet for me, but not a ServerLoad
                if Verbose.level >= 1:
                    print("{:.3f}: Packet {}.{} consumed in {} after {:.3f}".format(self.env.now, packet.src, packet.id, self._routerid, (self.env.now - packet.time)))



        else:
            # If the packet is not for us, forward to neighbours.
            # This is where the main servicecast algorithm will be implemented.
            # MR: if packet is data packet (ClientRequest)
            # MR:   STEP 8 forward to right link based on fw table
        

            if self.is_service(packet.dst):
                # this packet is for a Service name
                if packet.type == "ClientRequest":
                    print("{:.3f}: Packet ClientRequest at {} for service {} ".format(self.env.now, self.id(), packet.dst))
                
            else:
                # normal forwarding
                for neighbour in self.outgoing_ports:

                  #print("neighbour " + str(self.outgoing_ports[neighbour].out))

                  if link_end == None:
                      # looks like a local packet
                      # try and forward it
                      self.outgoing_ports[neighbour].put(packet)

                  elif link_end.src_node.id() == neighbour:
                      # don't send to where it came from
                      if Verbose.level >= 2:
                          print("{:.3f}: Packet {}.{} dont send back from {} to {} after {:.3f}".format(self.env.now, packet.src, packet.id, self.id(), link_end.src_node.id(), (self.env.now - packet.time)))
                      pass

                  elif isinstance(self.outgoing_ports[neighbour].out.dst_node,  Host):
                      # don't send to any connected Hosts
                      if Verbose.level >= 2:
                          print("{:.3f}: Packet {}.{} dont send to host from {} to {} after {:.3f}".format(self.env.now, packet.src, packet.id, self.id(), self.outgoing_ports[neighbour].out.dst_node.id(), (self.env.now - packet.time)))

                  else:
                      # forward the packet
                      # send to SwitchPort
                      self.outgoing_ports[neighbour].put(packet)

                      if Verbose.level >= 1:
                          print("{:.3f}: Packet {}.{} for {} forwarded from {} to {} after {:.3f}".format(self.env.now, packet.src, packet.id, packet.dst, self._routerid, neighbour, (self.env.now - packet.time)))


    # Is the destination address a service name:  e.g. ??a
    def is_service(self, name):
        """Is the destination address a service name:  e.g. ??a"""
        if name == None:
            return False
        elif name.startswith("??"):
            return True
        else:
            return False

    # We received a packet of type ServerLoad
    def server_load_packet(self, link_end, packet):
        """The process for a packet with type ServerLoad"""
        print("{:.3f}: Packet {} ServerLoad {}.{} ({:.3f}) managed in {} after {:.3f}".format(self.env.now, self.id(), packet.src, packet.id, packet.time, self._routerid, (self.env.now - packet.time)))

        # collect incoming metrics table [servicename, replicaID, metrics (delay, load), original messageID, creation timestamp, last update timestamp, link_received, calculated utility]
        servicename = packet.service
        replica = packet.replica
        msgID = packet.id
        creationTime = packet.time
        metrics = packet.payload

        print("{:.3f}: VALUES {} link_end: {} msgID: {} replica: {} time: {}  service: {} metrics: {}".format(self.env.now, self.id(), str(link_end), msgID, replica, creationTime, servicename, metrics))

        # add the delay of the last hop to the metrics
        metrics['delay'] +=  link_end.propagation_delay

        # store important data (including metrics) for later use in table
        # (link_end, msgID, replica) is key for decision for deleting old data

        # find entry from database for (link_end, msgID, replica)
        metric = Query()
        results = self.metrics_table.search((metric.link_end == str(link_end)) & (metric.msgID == msgID) & (metric.replica == replica))

        print("{:.3f}: RESULTS {} link_end: {} msgID: {} replica: {} ==> {} ".format(self.env.now, self.id(), link_end, msgID, replica, results))
        
        # check results
        announce = False
        metrics_to_send = None
        
        if results == []:
            # nothing found - it must be new, so add it
            val = self.metrics_table.insert({'link_end': str(link_end), 'msgID': msgID, 'replica': replica, 'servicename': servicename, 'creationTime': int(creationTime), 'load': int(metrics['load']), 'no_of_flows': int(metrics['no_of_flows']), 'delay': int(metrics['delay']) })

            announce = True
            print ("{:.3f}: ADD {} metric {}".format(self.env.now, self.id(), val) )

            metric_to_send = self.metrics_table.get(doc_id=val)

        else:
            # something found - so check it
            if self.metric_is_better(metrics, results):
                # the metric is better
                print("{:.3f}: metric IS better {}".format(self.env.now, self.id()))
                # so update
                self.metrics_table.update({ 'load': int(metrics['load']), 'delay': int(metrics['delay']) } , doc_ids=[ r.doc_id for r in results ])

                # get the result
                metric_to_send = results[0]
            
                announce = True
            else:
                announce = False

                
        # STEP 5,11 forward to appropriate links based on routing information base (fix code below)
        # Now we need to decide which messages go on which links
        # For each entry in the RIB
        #   compare with all the others
        # if any of the metrics is better than that metric in all the other entries
        # announce on all the links that it wasn't received from

        if announce:
            # send to neighbours
            for neighbour in self.outgoing_ports:

                if link_end.src_node.id() == neighbour:
                    # don't send to where it came from
                    pass

                elif isinstance(self.outgoing_ports[neighbour].out.dst_node,  Host):
                    # don't send to any connected Hosts
                    pass

                else:
                    # create a new packet
                    new_packet = Packet(metric_to_send['creationTime'], 3, metric_to_send['msgID'], self.id(), dst=neighbour)
                    new_packet.type = "ServerLoad"
                    new_packet.service =  metric_to_send['servicename']
                    new_packet.replica = metric_to_send['replica']
                    new_packet.payload = { 'load': metric_to_send['load'], 'no_of_flows': metric_to_send['no_of_flows'], 'delay': metric_to_send['delay'] }

                    # forward the packet
                    print("{:.3f}: FORWARD {} to {}".format(self.env.now, self.id(), neighbour))
                    # send to SwitchPort
                    self.outgoing_ports[neighbour].put(new_packet)
            



        #      STEP 6,12 check if fw table needs changing. If yes, change it. Choose the one with best utility function.


    # is the metric better than the ones we have
    def metric_is_better(self, metrics, results):
        # currently just check the first result
        result = results[0]

        if metrics['load'] < result['load']:
            # load is lower
            return True

        if metrics['delay'] < result['delay']:
            # delay is lower
            return True

        return False
         
        
    def put(self, packet):
        """ The callback from an EventGenerator.
        """
        # We don't expect to send Events to Routers
        # but for backwards compatibility, we do this
         # add a tuple of (link_end, packet) to the packet store
        self.packet_store.put((None, packet))

    def recv(self, packet, link_end):
        """A packet is received from a LinkEnd of a neighbouring Router.
        """
        # this function should be called by the previous hop to send a packet to this router
        # packet_store is a simpy.Store(self.env, capacity=1)
        if packet.src == self._routerid:
            if Verbose.level >= 1:
                print("{:.3f}: Packet {}.{} ({:.3f}) created in {} after {:.3f}".format(self.env.now,
                packet.src, packet.id, packet.time, self._routerid, (self.env.now - packet.time)))
        else:
            if Verbose.level >= 1:
                print("{:.3f}: Packet {}.{} ({:.3f}) arrived in {} from {} after {:.3f}".format(self.env.now, packet.src, packet.id, packet.time, self._routerid, link_end.src_node.id(), (self.env.now - packet.time)))

        # add a tuple of (link_end, packet) to the packet store
        self.packet_store.put((link_end, packet))

    def neighbours(self):
        """Neighbours of Router"""
        return list(self.outgoing_ports.keys())

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

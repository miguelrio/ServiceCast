## Starting

After the Network topology has been [created](Topology.md), 
it is necessary to set up the routing tables for the network, and
configure some event generators for the Clients and Servers, and
finally **run** the system.


#### Routing tables

After the Network topology has been created, the routing tables for
each node needs to be calculated.
This function does this:

```
    network.calculate_forwarding_tables()
```

This computes, for every router, the next hop and the total delay
towards every server, and installs them as the router's forwarding
table and its row of the network's latency table (`src/Routing.py`).
It runs one shortest-path computation per server with scipy's compiled
Dijkstra, so it is fast even on large topologies (about 10000 ms for the
91K-router CAIDA topology with 100 servers).

- If the links carry business relationships (`type "c2p"` or
  `"p2p"` in the GML), routes are valley-free (Gao-Rexford): customer
  routes are preferred over peer routes, then provider routes, and a
  peer link is never used as transit. Set `Routing.policy =
  "shortest"` for plain shortest-delay paths instead.
- Links with no type are treated as `internal` (unrestricted), so a
  topology without relationships, such as a Topology Zoo file, gets
  plain shortest-delay paths.
- Servers, clients and nodes marked `Internal 0` in the GML are never
  used as transit.
- If the GML names an observed-cone file (graph attribute
  `observedCones`, written by the CAIDA topology builder), a router of
  AS p holds a customer route to a server in AS d only if p is d, p is
  a tier-1, or d is in p's observed customer cone; otherwise it falls
  back to peer and provider routes. A server marked `embedded 1` (a
  cache inside an ISP) is announced only within its host AS's observed
  cone, so routers outside it get no route to it. Set
  `Routing.observed_cones = False` to turn both off.
- A router with `internalDelayMs` (a single-router AS standing for a
  whole network) adds that delay to every route passing through it, but
  not to routes that start or end there; the ServerMetric delay metric
  includes it too. Set `Routing.crossing_delay = False` to leave it out.
- A router with no route to a server gets no entry for it.

Call it after every server and client is attached: the clients' latency
rows and the network diameter are derived from the routers' tables.
Routing tables written into a GML file (`nextHop` / `delayMs` lines)
are ignored.

#### Client event generators

We use ```Generator.multi_client_event_generator()``` to generate
*service requests* from a number of clients.


With the following form, Clients 'c1' ... 'c5' generate service
request packets from arriving events. 
These are sent for service "§a". 
As services are not addresses -- by convention they start with §.

ServiceCast will use the forwarding tables in each Router, to send the
request to the *best* Server.

```
    generator_m1 = Generator.multi_client_event_generator(network, ["c1", "c2", "c3", "c4", "c5", "c6"], "§a", arrival_lambda=2000, size_lambda=6000, seed=30072022)
```

`arrival_lambda` and `size_lambda` are milliseconds. `size_lambda` is the
mean session duration before scaling, not the packet size in bytes.

The event generator is based on the ```simpy``` ```EventGenerator```.

#### Server event generators

Here we create event generators at for the servers.
Each Server has it's own generator, and the Server can generate
packets from the  arriving events, if the load has changed.

Here too, the packets are sent for service "§a", and are processed by
the routers.


```
    generator_s1 = Generator.server_load_event_generator(network, "s1", ["§a"], exponential_lambda=55000, seed=30072022)
    generator_s2 = Generator.server_load_event_generator(network, "s2", ["§a"], exponential_lambda=55000, seed=30072022)
    ...
```

The `exponential_lambda` time parameter is in milliseconds.


The event generator is based on the ```simpy``` ```EventGenerator```.


#### Running the system

To run the system and trigger the event generators, we do the
following:

```
    network.start(until=3600000)
```

This runs the simulation engine for 3600000 milliseconds.

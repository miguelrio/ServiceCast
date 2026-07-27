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

This will calculate Dijkstra's algorithm for each node, and 
then convert the shortest path info into a routing table, and inject
the table into each node.

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
    generator_m1 = Generator.multi_client_event_generator(network, ["c1", "c2", "c3", "c4", "c5", "c6"], "§a", arrival_lambda=2, size_lambda=6, seed=30072022)
```

The event generator is based on the ```simpy``` ```EventGenerator```.

#### Server event generators

Here we create event generators at for the servers.
Each Server has it's own generator, and the Server can generate
packets from the  arriving events, if the load has changed.

Here too, the packets are sent for service "§a", and are processed by
the routers.


```
    generator_s1 = Generator.server_load_event_generator(network, "s1", ["§a"], exponential_lambda=55, seed=30072022)
    generator_s2 = Generator.server_load_event_generator(network, "s2", ["§a"], exponential_lambda=55, seed=30072022)
    ...
```


The event generator is based on the ```simpy``` ```EventGenerator```.


#### Running the system

To run the system and trigger the event generators, we do the
following:

```
    network.start(until=3600)
```

This runs the simulation engine for 3600 seconds.

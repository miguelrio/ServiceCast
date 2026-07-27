## Classes and Objects

The Classes and Objects utilized in ServiceCast are outlined here.

### Verbose

We use the Verbose class to adjust the logging output.
The higher the level, the more logging output is produced.


### Utility

A static class to define and hold the *utility function*.

Can be set using ```  Utility.forwarding_utility_fn = staticmethod(lambda alpha, load, delay: ...)```


### Graph

A Graph is a more abstract representation of a topology

The can be created in a number of ways - see [Topology](Topology.md)

### Network

A Network is a concrete representation of  the ServiceCast network,
and is used directly for the emulations.

It has a direct link to a simulation environment. See [Topology](Topology.md)

### Router

A Router in the emulation.

It has Links to other Routers and Hosts, as well as the ServiceCast
forwarding tables.

### Link

A link between Routers and Hosts.


### Host

A Host in the emulation.

### Client

A Client is a type of Host that sends *requests* to *service names*.

### Server

A Server is a type of Host that accepts Client requests, and sends
current *load information* to the network.

### Generator

This is a *simpy* event generator for creating Client requests and
background Server load.

### SimComponents

The emulation runs on top of the *simpy* simulation platform.
They are held in SimComponents.


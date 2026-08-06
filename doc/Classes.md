## Classes and Objects

The Classes and Objects utilized in ServiceCast are outlined here.

### Verbose

We use the Verbose class to adjust the logging output.
The higher the level, the more logging output is produced.


### MetricUtility

A static class holding step 2 of the *utility* pipeline: it maps each raw
metric of a replica into a *metric utility*, in the range 0 (useless) &rarr;
1 (the best it can be).

Can be set using ```  MetricUtility.metric_utility_fn['load'] = lambda value, scale: ...```

### Utility

A static class holding step 3 of the *utility* pipeline: it combines the
metric utilities into the *user utility*, also in the range 0 &rarr; 1.

Can be set using ```  Utility.user_utility_fn = staticmethod(lambda alpha, metric_utility: ...)```

See [Variables](Variables.md).


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


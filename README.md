# ServiceCast

A simulator for evaluating the ServiceCast protocol.

Allows us to build a topology with some ServiceCast aware routers, connected to some servers and clients.

The servers support a number of *slots* for handling workload, and will send updates to the network advertising the *metrics* of their capacity for more work.

The clients send requests for work to be done.

The routers in the network keep a table for the *metrics* sent from the servers.  They also keep a forwarding table for the best server replica to send a request.

## System variables

The system variables which are used for configuring each experimental
run are outlined [here](Variables.md)


## Topology

Information about building a topology are [here](Topology.md)


## Starting

This shows [how to start](Starting.md) the experimental runs



## Classes and Objects

The Classes and Objects utilized are [here](Classes.md)

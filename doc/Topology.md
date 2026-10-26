## Topology

There are 2 main ways to create a topology for ServiceCast.

1. Create a Graph, and then convert it to a Network.
2. Create a Network directly.

### Graph

A Graph is a more abstract representation of a topology

The can be created in a number of ways:

1. From an adjacency list, using a Python dict.
2. From a GML file
3. Creating a Graph object and explicitly adding the nodes and edges.

#### Using an adjacency list

First define a topology using an adjacency list, in the form of a
Python dict object.
Then convert the adjacency list into a Graph.

```
    # 1 - Define the topology
    topo = {
        'a': { 'b', ('c', 4)},
        'b': { ('c', 3), ('d', 2), ('e', 2)},
        'c': { },
        'd': { 'b', ('c', 5)},
        'e': { ('d', 5)}
      }


    # 2 - build the graph -- convert adjacency list -> graph
    graph = Graph.from_dict(topo)
```

#### From a GML file

```
    # 1 - Get a GML file
    gml_file = "topologies/gml/Dfn.gml"

    # 2 - build the graph -- read and convert the GML file
    graph = Graph.from_gml_file(gml_file)
```


#### Creating a Graph object and explicitly adding the nodes and edges

```
    # 1 - Create a Graph
    graph = Graph()
    
    # 2 - add nodes and edges
    graph.add_node('a')
    graph.add_node('b')
    graph.add_edge('a', 'b')
    
```

The ```add_edge``` function has an optional 3rd argument which is the
link weight -- the default is a weight of 1.



#### Extending a Graph


Once the Graph has been created, using one of the above forms, it is
possible to extend the Graph in order to add new nodes and new edges
by calling the ```add_node()``` function or ```add_edge()``` function.



#### Routing

Routes are computed on the Network, not the Graph: see
`network.calculate_forwarding_tables()` in [Starting](Starting.md).
The Graph keeps each GML edge's `type` (`c2p`, `p2p`, `internal`,
`hosts`, `access`) so that the routing can follow business
relationships.

#### Link delays from a GML file

Each GML link's delay (its weight) is set as follows; delays are in ms:

- A link touching an `Internal 0` node (a server's or client's
  attachment link, or a link to a Topology Zoo external peer): its
  `delayMs` if the GML gives one (and it is not 0), otherwise
  `Graph.default_client_attachment_delay_ms` (10 ms) for a client link,
  `Graph.default_server_attachment_delay_ms` (1 ms) for a server link,
  or `Graph.default_propagation_delay` for any other.
- A link touching a hyperedge node with no location:
  `Graph.default_propagation_delay`.
- Any other link: its `delayMs`, or else the great-circle distance
  between the two nodes' Latitude/Longitude at 0.009 ms per km.
- A remaining weight of 0 is replaced by
  `Graph.default_propagation_delay` when the Network is built.

Hosts attached in code (`add_server`, `add_client`) keep the weight
passed to them.






### Network

A Network is a concrete representation of  the ServiceCast network,
and is used directly for the emulations.
It has a direct link to a simulation environment, which can generate
events for Client requests and Server load.


The Network can be created in a number of ways:

1. Converting from a Graph
2. From a GML file
3. Creating a Network object and explicitly adding the nodes and edges.

#### Converting from a Graph

```
    # 1 - create the simpy environment 
    env = simpy.Environment()

    # 2 - convert from a graph -- pass in the simulation environment
    network = Network.from_graph(graph, env)
```

#### From a GML file

```
    # 1 - create the simpy environment 
    env = simpy.Environment()

    # 2 - Get a GML file
    gml_file = "topologies/gml/Dfn.gml"

    # 3 - build the network -- read and convert the GML file
    network = Network.from_gml_file(gml_file, env)
```

#### Creating a Network object and explicitly adding the nodes and edges

It is necessary to create a ```simpy``` Simulation environment for the network
operations to occur correctly.


```
    # 1 - Create a simpy environment
    env = simpy.Environment()

    # 2 - Create a Network -- pass in the environment
    network = Network(env)
    
    3 - add nodes and edges
    network.add_node('a')
    network.add_node('b')
    network.add_edge('a', 'b')
```

The ```add_edge``` function has an optional 3rd argument which is the
link weight -- the default is a weight of 1.



#### Extending a Network


Once the Network has been created, using one of the above forms, it is
possible to extend the Network in order to add new nodes and new edges
by calling the ```add_node()``` function or ```add_edge()``` function.
These functions extend the network core.

#### Adding Clients and Servers

As the ServiceCast emulation environment is based on events at Clients
and Servers, there are functions to add Clients ```add_client()``` and
to add Servers ```add_server()```.
Both functions take a node name and the network node to connect to.

To add a Client:
```
    network.add_client("c1", 'a')
```

To add a Server:

```
    network.add_server("s1", 'b')
```


Both of these functions, as well as the ```add_edge``` function have
the optional 3rd argument which is the link weight.

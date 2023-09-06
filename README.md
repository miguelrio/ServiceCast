# ServiceCast

A simulator for evaluating the ServiceCast protocol.

Allows us to build a topology with some ServiceCast aware routers, connected to some servers and clients.

The servers support a number of *slots* for handling workload, and will send updates to the network advertising the *metrics* of their capacity for more work.

The clients send requests for work to be done.

The routers in the network keep a table for the *metrics* sent from the servers.  They also keep a forwarding table for the best server replica to send a request.



### System variables

### Utility class

Set alpha value for Utility function  
```Utility.alpha = 0.50```

Set utility forwarding function

```
# load:  0 -> 1
utility_load = lambda load: (1-(0.12*load)) if load <  else (4.5-(4.5*load))
# delay: 0 -> 10
utility_delay = lambda delay: (1-(0.1*delay)) if delay <= 10 else 0

# actual utility fn
Utility.forwarding_utility_fn = staticmethod(lambda alpha, load, delay: round(1 - ((utility_load(load / (2 * Server.slots)) * utility_delay(delay))), 4))
```
 
### Server class

Default number of slots on a server  
```Server.slots = 50```
 
Set load functions

```
Server.load_up_fn = staticmethod(lambda val: val + 4)    
Server.load_down_fn = staticmethod(lambda val: val - 4)
```

Set flow functions  

```
Server.flows_up_fn = staticmethod(lambda val: val + 4)    
Server.flows_down_fn = staticmethod(lambda val: val - 4)
```

### Router class

Internal *better than* function, to determine if the metric arg2 is better than metric arg1

```
Router.better_than_fn = staticmethod(lambda x, y: x < y)
```

### Verbose class

Set verbose level for system outputs  
```Verbose.level = 2```

Set table printout style.  
- If table == 0, print tables simply on one line  
- If table == 1, try and print tables one row per line  
```Verbose.table = 0```

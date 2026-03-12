## System variables

The system variables which are used for configuring each experimental
run are outlined here.


### Utility class

The are values for the *utility function*, called when forwarding a
notification.  It allows the function and the coefficients to be set
for each run.

Set alpha value for Utility function  
```Utility.alpha = 0.50```

We can set the utility forwarding function:

```
# actual utility fn
Utility.forwarding_utility_fn = staticmethod(lambda alpha, load, delay: 1 / (1 + alpha * load + (1-alpha) * delay))
```


or a more complex version with subfunctions:

```
# load function with load:  0 -> 1
utility_load = lambda load: (1-(0.12*load)) if load <  else (4.5-(4.5*load))
# delay function with delay: 0 -> 10
utility_delay = lambda delay: (1-(0.1*delay)) if delay <= 10 else 0
```

```
# actual utility fn
Utility.forwarding_utility_fn = staticmethod(lambda alpha, load, delay: round(utility_load(load / (2 * Server.slots)) * utility_delay(delay), 4))
```
 
### Server class

##### Server slots

Default number of slots on a server  
```Server.slots = 50```
 
##### Set load functions

These are called when a new job comes, or a job finishes.
They increase the load or decrease the load on the server.
The default is to increase or decrease the load by 1 for each job.

We might change these as a job we are modelling may be more expensive
that a standard job.

```
Server.load_up_fn = staticmethod(lambda val: val + 2)    
Server.load_down_fn = staticmethod(lambda val: val - 2)
```


##### Set flow functions

These are called when a new job comes, or a job finishes.
They increase the no of flows or decrease the no of flows on the server.
The default is to increase or decrease the no of flows by 1 for each job.

We might change these as a job we are modelling may use many flows,
compared to a standard job.


```
Server.flows_up_fn = staticmethod(lambda val: val + 4)    
Server.flows_down_fn = staticmethod(lambda val: val - 4)
```

##### Load Change Factor

This is the amount by which the load value has to be different, so
that a notification is forwarded to the server's neighbours.

```
 Server.change_factor = 0.2
```

The default  change factor is 0.1 which represents a 10% change.

This is used to provide damping for the number of messages from the
server, and avoid sending on each small load change.


### Router class

##### Better Than function

A Router internal *better than* function, to determine if the metric arg2 is better than metric arg1

```
Router.better_than_fn = staticmethod(lambda x, y: x < y)
```

##### Forwarding Utility Change Factor

This is the amount by which the return value of calling the *utility
function* has to be different, so that a notification is forwarded to
the router's neighbours.

```
Router.forwarding_utility_change_factor = 0.05
```

The default  forwarding utility change factor is 0.1
which represents a 10% change.

This is used to provide damping for the number of messages from the
router, and avoid sending on each small change in the utility value.


### Logging output

We use the Verbose class to adjust the logging output.
The higher the level, the more logging output is produced.



Set verbose level for system [logging](Logging.md) outputs

```Verbose.level = 2```

Current values for ```Verbose.level``` are [0, 1, 2, 3].



Set table printout style.  
- If table == 0, print no table data  
- If table == 1, print tables simply on one line  
- If table == 2, print tables one line per entry  

```Verbose.table = 0```

Current values for ```Verbose.table``` are [0, 1, 2].

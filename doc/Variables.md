## System variables

The system variables which are used for configuring each experimental
run are outlined here.


### Utility and MetricUtility classes

The *utility* of a replica, called when forwarding a notification, is
calculated in 3 steps:

1. gather the raw metrics of the replica: *load* and *delay*
2. map each raw metric into a **metric utility**, in the range
   0 (useless) &rarr; 1 (the best it can be)
3. combine the metric utilities into the **user utility**, also in the
   range 0 &rarr; 1

Step 2 is done by the `MetricUtility` class, step 3 by the `Utility`
class.  Each can be set for a run, independently of the other.

##### Setting values

Set alpha value, the weight of *load* against *delay* in the default
user utility function  
```Utility.alpha = 0.50```


##### Step 2: metric utility functions

There is one function per metric name, in the
`MetricUtility.metric_utility_fn` dict.  Each takes the raw value and
that metric's *scale* -- the raw value at which the metric is at its
worst -- and returns a metric utility in the range 0 &rarr; 1.

```
# the default for both metrics
MetricUtility.metric_utility_fn['load'] = lambda value, scale: 1 - value / scale
MetricUtility.metric_utility_fn['delay'] = lambda value, scale: 1 - value / scale
```

or a version with a threshold:

```
# load:  raw 0 -> scale (a server with every slot used)
MetricUtility.metric_utility_fn['load'] = lambda load, scale: (1-(0.12*load)) if load < 0.8 else (4.5-(4.5*load))
```

The scales are held in `MetricUtility.metric_scale`.
`metric_scale['load']` is 1.0, a server with every slot used.
`metric_scale['delay']` is set to the network diameter by the Network
when the forwarding tables are calculated, so it should not be set by
an experiment.

```
MetricUtility.metric_scale['load'] = 2 * Server.slots
```

The returned value must be in the range 0 &rarr; 1.
A value outside that range raises a `ValueError` naming the function
at fault -- it is not silently clamped, because that would change the
utility values being measured without any warning.


##### Step 3: the user utility function

It takes *alpha* and the dict of metric utilities, keyed by metric name.

```
# the default
Utility.user_utility_fn = staticmethod(lambda alpha, metric_utility: alpha * metric_utility['load'] + (1-alpha) * metric_utility['delay'])
```

or combining the metric utilities as a product:

```
Utility.user_utility_fn = staticmethod(lambda alpha, metric_utility: round(metric_utility['load'] * metric_utility['delay'], 4))
```

The returned value must be in the range 0 &rarr; 1.
A value outside that range raises a `ValueError` naming the function
at fault -- it is not silently clamped, because that would change the
utility values being measured without any warning.



 
### Server class

##### Server slots

Default number of slots on a server  
```Server.slots = 50```
 
##### Set slots functions

These are called when a new job comes, or a job finishes.
They increase the slots used or decrease the slots used on the server.
The default is to increase or decrease the slots used by 1 for each job.

We might change these as a job we are modelling may be more expensive
that a standard job.

```
Server.slots_up_fn = staticmethod(lambda val: val + 2)    
Server.slots_down_fn = staticmethod(lambda val: val - 2)
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

A Router internal *better than* function, to determine if the metric arg2 is better than metric arg1.
There is one per metric name.

```
Router.better_than_fn['load'] = staticmethod(lambda x, y: x < y)
```

##### FIB Utility Update Threshold

This is the amount by which the return value of calling the *utility
function* has to be different, so that the FIB is updated to
change to a new  server.

```
Router.fib_utility_update_threshold = 0.05
```

The default utility update threshold is 0.1
which represents a 10% change.

This is used to provide damping for the number of changes that the
router will use, and avoid sending to different servers on
each small change in the utility value. 


##### Router doing Service Replica Selection

In the system, it is possible for a client request to be sent to a
server / replica by the first Router that sees a client request, or to
be routed hop-by-hop and have the last router in the chain, and the
one nearest to a server,  make the decision.

This approach gives a slightly different outcome to the selected
server.


To get the first router that sees a client request to make a decision, set:
```
Router.hop-by-hop = False
```

To get the last router that sees a client request to make a decision, set:

```
Router.hop-by-hop = True
```

### Network class

When a router makes its forwarding decision (the last router with
hop-by-hop, the first router with first-decide) it always records on the
packet a snapshot of the ground-truth utilities (at selection time) and
the FIB estimate the decision was based on. The snapshot is taken from
the deciding router's vantage (its own latency to each replica), so the
selection-time ground truth shares the latency basis of the FIB
estimate. These are reported when the request arrives at a Server as
the OUTCOME_GAP / DECISION_GAP / STALENESS_ERR log lines (see
Logging.md); OUTCOME_GAP uses the client's vantage.


### Logging output

We use the Verbose class to adjust the logging output.
The higher the level, the more logging output is produced.



Set verbose level for system [logging](Logging.md) outputs

```Verbose.level = 2```

Current values for ```Verbose.level``` to produced output are [0, 1, 2, 3].


Setting the value to -1 will produce no logging output.


Set table printout style.  
- If table == 0, print no table data  
- If table == 1, print tables simply on one line  
- If table == 2, print tables one line per entry  

```Verbose.table = 0```

Current values for ```Verbose.table``` are [0, 1, 2].

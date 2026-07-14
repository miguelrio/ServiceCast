## Logging

We use the Verbose class to adjust the logging output.
The higher the level, the more logging output is produced.

Current values for ```Verbose.level``` to produce output are [0, 1, 2, 3].


Setting the value to -1 will produce no logging output.


Set level value:  
- If level == 0, essential minimal statistics  
- If level == 1, to track behaviour of clients, routers, and servers  
- If level == 2, extra messages related to level 1  
- If level == 3, fine detail from loops (rarely used)

### Level 0

Verbose level 0 (extract metrics/results):


1. PACKET_CREATED.*ServerMetric (to count ServerMetric messages) -  A
count of these will be the number of server updates

1. RECV_PACKET.*ServerMetric  ServerMetric - A count of these should be
the total number of update packets 

1. OUTCOME_GAP - one per client request, printed when the request arrives
at a Server: the utility of the selected replica vs the best replica,
both at arrival time (B = BEST_UTIL_ARR - SEL_UTIL_ARR).
Utilities are computed from the CLIENT's vantage (client-to-replica
latency), as B measures the outcome from the client's point of view.
Status is SAME / EQUAL / DIFFERENT / BLOCKED, followed by the signed gap.

At Verbose level 0 the line is plain:

```
6.151: Net   OUTCOME_GAP 's1' [c3.1] SELECTED: time: 6.151 server: s1 load: 0.0 latency: 0.4 utility: 0.71429 BEST: time: 6.151 server: s1 load: 0.0 latency: 0.4 utility: 0.71429 SAME 0.0
```

At Verbose level >= 1 the notation from the BEST_REPLICA_UTILITY notes is
shown before each value, as field(NOTATION): value, and the metric formula
follows the tag; the trailing "KEYWORD gap" is identical at all levels:

```
6.151: Net   OUTCOME_GAP (B = BEST_UTIL_ARR - SEL_UTIL_ARR) 's1' [c3.1] SELECTED: time(t_arr): 6.151 server(SEL_ID): s1 load: 0.0 latency: 0.4 utility(SEL_UTIL_ARR): 0.71429 BEST: time(t_arr): 6.151 server(BEST_ID_ARR): s1 load: 0.0 latency: 0.4 utility(BEST_UTIL_ARR): 0.71429 SAME 0.0
```


### Level 1

Verbose level 1 (basic following of update message propagation,
routing decisions)

##### Per-request metrics

1. DECISION_GAP - the ground-truth best utility at selection time vs the
utility the deciding router believed the selected replica had
(A = BEST_UTIL_SEL - SEL_UTIL_EST)

1. STALENESS_ERR - the selected replica's actual utility at selection time
vs the utility the deciding router believed it had
(C = SEL_UTIL_SEL - SEL_UTIL_EST)

Both selection-time metrics are computed from the DECIDING ROUTER's
vantage (the last router with hop-by-hop, the first router with
first-decide): the ground-truth sections use the deciding router's
latency to each replica, matching the latency basis of the FIB estimate
SEL_UTIL_EST. So only load staleness contributes to C, and A compares
the decision against the best the router could have made from its own
position with fresh information.

t_update is the creation time of the most recent update the deciding
router has recorded for the selected replica. The tracked FIB values
follow every received update (damping only prevents switching replicas),
so staleness in SEL_UTIL_EST comes from server-side update suppression
(Server.change_factor) and in-flight propagation delay only.

Note that with hop-by-hop the deciding router is the selected replica's
attachment router, so DECISION_GAP is structurally close to zero; it is
most informative in first-decide mode.

As these lines only appear at Verbose >= 1, they always carry the
notation annotations, e.g.:

```
3131.183: Net   STALENESS_ERR (C = SEL_UTIL_SEL - SEL_UTIL_EST) 's5' [c3.128] SELECTED: time(t_update): 2871.037 server(SEL_ID): s5 load: 0.14 latency: 0.1 utility(SEL_UTIL_EST): 0.85857 ACTUAL: time(t_sel): 3131.083 server(SEL_ID): s5 load: 0.2 latency: 0.1 utility(SEL_UTIL_SEL): 0.75857 SAME -0.1
```

##### Server packets


1. SERVER_LOAD

1. INCREASE_LOAD / DECREASE_LOAD

1. CALCULATE_LOAD_DIFFERENCE

1. PACKET_DELIVER

1. HOST_RECV

##### Client packets

1. PACKET_CREATED


##### Router processing

1. RECV_PACKET.*ClientRequest

1. PACKET_FORWARD which are hop by hop messages of client and server messages

1. INCOMING_VALUES

1. UNICAST_ROUTE

1. METRIC_SEARCH_RESULTS 

1. METRIC_TABLE 

1. ANNOUNCE 

1. FORWARD_METRIC

1. CHOOSE_BEST_FORWARDING_REPLICA

1. CHOOSE_BEST_REPLICA

1. SINGLE_DECISION


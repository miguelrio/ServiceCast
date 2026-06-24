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

1. BEST_REPLICA_UTILITY - shows number of client requests when arriving
at a Server


### Level 1

Verbose level 1 (basic following of update message propagation,
routing decisions)

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


## Logging

We use the Verbose class to adjust the logging output.
The higher the level, the more logging output is produced, and each level
prints everything the level below prints.

| `Verbose.level` | Prints | Use for |
| --- | --- | --- |
| -2 | Silent: nothing per event, and the ground-truth calculations are skipped. | Pure timing runs. |
| **-1** | **Metrics:** the parameter header, the per-request lines (`OUTCOME_GAP`, `DECISION_GAP`, `STALENESS_ERR`, `REQUEST_NOT_FORWARDED`, blocked requests) and the end-of-run `SUMMARY_` counts. | **Large networks and long runs. This is the expected level for experiments at scale.** |
| 0 | + the per-update lines (`PACKET_CREATED`, `RECV_PACKET`). | Detailed protocol debugging, on small networks or short runs. |
| 1 | + FIB stability lines and other routing decisions. | As level 0. |
| 2 | + extra messages related to level 1, e.g. per-neighbour decisions. | As level 0. |
| 3 | + fine detail from loops and full table dumps (rarely used). | As level 0. |

`REQUEST_NOT_FORWARDED` is printed at every level, including -2.

### Which level to use

**Use level -1 for large-scale runs and large networks.** Its log grows
with the number of requests and routers, not with the number of update
messages, and it gives the same results from `scripts/quick_stats.py` and
`scripts/plot_load.py` as a level 1 log: the simulator counts the
per-update events itself and prints the totals once, at the end of the
run. It costs about 1-2% of run time over level -2.

**Levels 0 and above are for detailed protocol debugging.** They print a
line (level 0) or several lines (levels 1 and up) for every update message
a router receives, so the log grows with the number of messages. Use them
only on small networks or for short runs; otherwise the log files become
far too large to store.

Measured on a 1K-router network (60 simulated seconds, about 750K update
messages), and projected for a 500 s run on a 100K-router network:

| Level | 1K, 60 s | 100K, 500 s (projected) | Extra run time vs -2 at 100K (projected) |
| --- | --- | --- | --- |
| -1 | 1.9 MB | about 25 MB | about 1-2% |
| 0 | 93 MB | about 110 GB | about 5-10% |
| 1 | 1.4 GB | about 1.7 TB | about 40% |
| 2 | 3.2 GB | about 3.9 TB | about 100% |

Older logs: a log made at -1 before the -1/-2 change contains no
per-request lines, and an older level 0 log has no `DECISION_GAP` /
`STALENESS_ERR` or `SUMMARY_` lines. `quick_stats.py` reads both.

### Level -1

Verbose level -1 (metrics: everything the analysis scripts need).

##### Per-request metrics

1. OUTCOME_GAP - one per client request, printed when the request arrives
at a Server: the utility of the selected replica vs the best replica,
both at arrival time (B = BEST_UTIL_ARR - SEL_UTIL_ARR).
Utilities are computed from the CLIENT's vantage (client-to-replica
latency), as B measures the outcome from the client's point of view.
Status is SAME / EQUAL / DIFFERENT / BLOCKED, followed by the signed gap.
BLOCKED lines carry an extra MINLOAD section — the lowest-loaded replica at
`t_arr` — printed before the keyword; `load < 1.0` there means the blocked
request could have been served elsewhere:

```
270.990: Net   OUTCOME_GAP (B = BEST_UTIL_ARR - SEL_UTIL_ARR) 's1' [c4.141] SELECTED: time(t_arr): 270.990 server(SEL_ID): s1 load: 1.0 latency: 0.3 utility(SEL_UTIL_ARR): 0.28571 BEST: time(t_arr): 270.990 server(BEST_ID_ARR): s1 load: 1.0 latency: 0.3 utility(BEST_UTIL_ARR): 0.28571 MINLOAD: time(t_arr): 270.990 server(MIN_LOAD_ID): s3 load: 0.7 latency: 0.6 utility(MIN_LOAD_UTIL): 0.22143 BLOCKED 0.0
```

1. DECISION_GAP - the ground-truth best utility at selection time vs the
utility the deciding router believed the selected replica had
(A = BEST_UTIL_SEL - SEL_UTIL_EST)

1. STALENESS_ERR - the selected replica's actual utility at selection time
vs the utility the deciding router believed it had
(C = SEL_UTIL_SEL - SEL_UTIL_EST)

1. REQUEST_NOT_FORWARDED - a request reached a router with no FIB entry
for the service and was dropped.

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

At Verbose levels -1 and 0 the gap lines are plain:

```
3.015: Net   OUTCOME_GAP 's5' [c5.1] SELECTED: time: 3.015 server: s5 load: 0.0 latency: 0.747 utility: 0.9577 BEST: time: 3.015 server: s5 load: 0.0 latency: 0.747 utility: 0.9577 SAME 0.0
3.015: Net   DECISION_GAP 's5' [c5.1] SELECTED: time: 0.000 server: s5 load: 0.0 latency: 0.747 utility: 0.9577 BEST: time: 2.268 server: s5 load: 0.0 latency: 0.647 utility: 0.9635 SAME 0.0058
3.015: Net   STALENESS_ERR 's5' [c5.1] SELECTED: time: 0.000 server: s5 load: 0.0 latency: 0.747 utility: 0.9577 ACTUAL: time: 2.268 server: s5 load: 0.0 latency: 0.647 utility: 0.9635 SAME 0.0058
```

At Verbose level >= 1 the notation from the BEST_REPLICA_UTILITY notes is
shown before each value, as field(NOTATION): value, and the metric formula
follows the tag; the trailing "KEYWORD gap" is identical at all levels:

```
6.151: Net   OUTCOME_GAP (B = BEST_UTIL_ARR - SEL_UTIL_ARR) 's1' [c3.1] SELECTED: time(t_arr): 6.151 server(SEL_ID): s1 load: 0.0 latency: 0.4 utility(SEL_UTIL_ARR): 0.71429 BEST: time(t_arr): 6.151 server(BEST_ID_ARR): s1 load: 0.0 latency: 0.4 utility(BEST_UTIL_ARR): 0.71429 SAME 0.0
3131.183: Net   STALENESS_ERR (C = SEL_UTIL_SEL - SEL_UTIL_EST) 's5' [c3.128] SELECTED: time(t_update): 2871.037 server(SEL_ID): s5 load: 0.14 latency: 0.1 utility(SEL_UTIL_EST): 0.85857 ACTUAL: time(t_sel): 3131.083 server(SEL_ID): s5 load: 0.2 latency: 0.1 utility(SEL_UTIL_SEL): 0.75857 SAME -0.1
```

##### End-of-run summaries

Printed once, after the simulation ends (`Network.print_metrics_summary`),
at every level from -1 up. They are the totals the analysis scripts would
otherwise count from the per-update lines of levels 0 and 1:

1. SUMMARY_SERVER_METRICS - network totals: ServerMetric updates created
by servers (the count of `PACKET_CREATED ... ServerMetric` lines), and
ServerMetric announcements and withdrawals received by routers (the count
of `RECV_PACKET ... ServerMetric` A / W lines, including updates that are
then dropped as off the unicast path).

1. SUMMARY_FIB_ROUTER - one line per router that took any FIB action:
the counts of its SET / KEEP / CHANGED / REMOVED decisions (the
`SET_BEST_REPLICA`, `KEEP_BEST_REPLICA`, `CHANGED_BEST_REPLICA` and
`REMOVED_BEST_REPLICA_FROM_FIB` lines of level 1).

1. INVALID_ROUTE_DROPS - printed just before the summaries: the number of
ServerMetric updates routers dropped because they arrived off the unicast
path to their replica, and the `forward_to_tree_children_only` setting.
With that setting on, routers don't send those updates, so the count is 0.

```
360.000: INVALID_ROUTE_DROPS 0 (forward_to_tree_children_only = True)
360.000: Net   SUMMARY_SERVER_METRICS created: 1890 announce: 102571 withdraw: 16092
360.000: AAC   SUMMARY_FIB_ROUTER SET: 16 KEEP: 1103 CHANGED: 104 REMOVED: 2
```

When a log also has the per-update lines (level 0 and up), `quick_stats.py`
checks the summaries against its own counts and prints a warning on stderr
if they disagree: the server totals from level 0, and the FIB counts
router by router from level 1.

### Level 0

Verbose level 0 (follows every update message; small networks or short
runs only):

1. PACKET_CREATED.*ServerMetric (to count ServerMetric messages) -  A
count of these will be the number of server updates

1. RECV_PACKET.*ServerMetric  ServerMetric - A count of these should be
the total number of update packets 


### Level 1

Verbose level 1 (basic following of update message propagation,
routing decisions)

##### FIB stability

1. SET_BEST_REPLICA / KEEP_BEST_REPLICA / CHANGED_BEST_REPLICA /
REMOVED_BEST_REPLICA_FROM_FIB - one per FIB decision (counted in
SUMMARY_FIB_ROUTER)

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


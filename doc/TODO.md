# Technical notes for open to-do items

Background for open items: code locations, measurements and options.
Status, owners and priorities are tracked in the team's master to-do
list; each heading carries that list's ID. Delete a section when its
item is resolved (git keeps the history).

## Protocol behaviour

#### T-12: Entries freed by a withdrawal are not announced until the next decision

When an announcement arrives, the router reruns `decide_announcements`
and announces its non-dominated set. When a withdrawal arrives
(`incoming_server_metrics_packet_withdraw`), it deletes the entry and
passes the withdrawal on, but does not decide again. An entry that was
dominated only by the withdrawn one is now non-dominated, yet it is not
announced until the next announcement reaches that router. Until then
routers downstream do not see that server. Measured on the 1K-router,
100-server topology at full load (100 s): 545 of 1,000 routers held one
such entry at the end of the run.

Proposal: announce freed entries straight after a withdrawal. With the
default comparators (transitive dominance) only a little work is
needed:

- if the withdrawn entry was not in the router's decided set, or the
  router has no dominated entries, nothing can change (most
  withdrawals);
- otherwise check only the dominated entries against the remaining
  decided set and announce those no longer beaten.

Expected cost about 1-3% of run time (a full re-decision on every
withdrawal would cost about 25-35%). Messages: mostly the same ones,
sent earlier, since the next decision would announce them anyway; a few
extra when the freed entry is dominated or changes again before that
next decision. Margin comparators (e.g. "same within 5%") are not
strictly transitive, so they would need a full re-decision. The change
alters results, so measure run time, message counts and accuracy
against the current code before adopting it.

#### T-13: Count the messages `TREE_CHILDREN_ONLY` does not send

`TREE_CHILDREN_ONLY` is mainly a simulator speed-up. As a protocol
option it would need each router to know its neighbours' routing
tables. With it on, a router skips a neighbour whose next hop to the
replica is not this router (`NOT_TREE_CHILD`, logged at Verbose 2
only). Those messages are never sent, so they are missing from
`SUMMARY_SERVER_METRICS` and from the "total update messages" line in
`quick_stats.py`. With it off, they are sent, counted on arrival and
then dropped (`INVALID_ROUTE_DROPS`, which `quick_stats.py` does not
read). Message counts from runs with the flag on and off are therefore
not comparable.

Add an end-of-run count of the messages that would have been sent,
split into announcements and withdrawals, and report it in
`quick_stats.py` next to the totals. Also report `INVALID_ROUTE_DROPS`
for runs with the flag off. Getting this exact is not simple: with the
flag off, these messages also go through the sent table (an
announcement already sent to that neighbour is not sent again, and
withdrawals follow the sent table). Counting the skips alone would
over-count. Matching the flag-off count means keeping sent-table
entries for the skipped neighbours too, which costs some of the time
and memory the flag saves. The receiver drops these messages without
acting on them, so they have no further effect. With the sent-table
entries kept, the count would match the flag-off runs exactly.

#### T-38: Announcement radius (blast radius)

The prototype in `Router.incoming_server_metrics_packet` is commented
out (Oct 2026). It computed an `announcement_distance` for every
announcement at every router but only printed it (verbose >= 2):
nothing limited propagation. It was costly because
`Network.average_normalised_load()` loops over every server, so the
cost grew with servers x messages: about 21% of simulation time on
CAIDA with 1000 servers and 50 clients. It also used global state
(average load, total capacity, network diameter) that a router would
not have. A real version should be O(1) per message and use only
local information. Options:
- the origin server computes the radius from its own load and
  capacity and puts it in the announcement (a budget in ms or hops,
  like a TTL); each router only compares the propagation time so far
  with it;
- routers estimate the "average load" and "available capacity"
  terms from their own RIB entries, kept as running totals updated
  when an entry is added, changed or removed;
- the diameter term: the origin's or the router's own largest delay
  (its eccentricity), computed once at start-up.

#### T-44: Client request forwarding

Currently we have hop-by-hop forwarding,
so each Router will check which is the best for the service name.

An alternative is to change the service name to an address
at the first Router.

## Configuration and defaults

#### T-17: Default link delay is hard-coded and inconsistent

A link touching an `Internal 0` node (every server and client
attachment) now uses its GML `delayMs` when given and not 0, else
`Graph.default_server_attachment_delay_ms` (1 ms) or
`Graph.default_client_attachment_delay_ms` (10 ms); delays are ms
throughout. The routing tables are computed in the simulator from the
network's own link weights, so the route adders' copy of the rule is no
longer needed. `Network.from_graph` still replaces any 0 weight with
`Graph.default_propagation_delay`. The points below about the default
value remain open.

Before that change, links touching an `Internal 0` node (every server
and client attachment) never used the GML `delayMs`: `Gml.py` checked
for external nodes before it read `delayMs`, so these links got
`Graph.default_propagation_delay`.
The default value is set in several places that must agree but are not
linked to each other:

- `src/Graph.py`: class default `default_propagation_delay = 1000`
- Experiment scripts: 7 set it to `100`, 1 sets it to `1000`, others take
  it from a parameter (`knobs["prop_delay"]`, `GRAPH_DELAY` via
  `Importer.py`)
- `scripts/setup/constants_*.py`: `GRAPH_DELAY = 1000` (dfn_2),
  `100` (dfn_equiv), `GRAPH_DELAYS = [100 ... 4000]` (v1 sweep)
- (resolved) `scripts/add_routing_tables.py` and
  `scripts/add_routing_tables_valley_free.py` hard-coded the default, so
  precomputed tables silently went wrong if an experiment used any other
  value (the delay-utility < 0 crash on 2026-10-08). Both scripts are
  removed: the simulator computes the tables from its own link weights.
- `Host.add_neighbour` / `Router.add_neighbour`: `propdelay=1000` defaults

To do:
- Make the default link delay a single configured parameter, as the
  older experiment scripts did. Nothing should hard-code it.
- The route adders should read the same value (a command-line option,
  or a value recorded in the GML), not a constant.
- Choose a sensible default in milliseconds: about `5` for an access
  link. 100 ms is far longer than the core links (median 6 ms
  on the 1K topology, 16.5 ms on CAIDA).
- Decide whether access links should use the GML `delayMs` when it is
  present, rather than always using the default.

For the next meeting (checked Oct 2026, after the ms change; the list
above is partly out of date). Proposal: 10 ms for links with no delay,
1 ms for servers and 10 ms for clients everywhere. Places that depend on
the default and would change:
- `src/Graph.py`: `default_propagation_delay = 1000` (ms); used for GML
  edges with no delay, hyperedges, 0 weights in `Network.from_graph`,
  and edges built in code without a weight.
- `src/Network.py`: `add_server(..., weight=1)` and
  `add_client(..., weight=1)`: 1 ms defaults, not the agreed 10 ms for
  clients (relevant for clients added at run time).
- Experiments that set `Graph.default_propagation_delay = 100` and
  pass it to `add_server` / `add_client` as the access-link delay:
  `main_dfn`, `main_dfn_equiv`, `main_dfn_2`, `main_cog`; the same
  setting only as a fallback in `main_precomputed_t1`, `main_mig_t1`.
- `Importer` experiments (`main_importer`, `main_dfn_2_import`,
  `main_dfn_equiv_import`) attach hosts with the default, from
  `GRAPH_DELAY` in milliseconds: 100 in `constants_dfn_2_importer`,
  `constants_cog_importer`, `constants_dfn_equiv`; 1000 in
  `constants_dfn_2`.
- Tests: `tests/bench_rib_store.py` (100), `tests/test_routing.py` (100).
- Sweeps vary the delay on purpose (`constants_scaling.py` 100-4000 ms,
  `constants_v1.py` `GRAPH_DELAYS`): keep as an experiment parameter.
- The old toy experiments (`main_e1` etc.) rely on the defaults: their
  unweighted links get `default_propagation_delay` (now 1000 ms) while
  links with a weight in code (e.g. `('c', 4)`) are now 4 ms.
Changing these changes results of the DFN, COG and toy experiments.
- Check consistency across the simulator, the topology generator and
  the route adders:
  - units: the simulator and the CAIDA GMLs use milliseconds
  - which edges count as links: client-server `demand` edges were
    loaded as links and silenced 51 servers on CAIDA. The loader now
    ignores them (2026-10-14); the generator should stop writing them
  - the same link-weight rule everywhere

#### T-08: Damping uses an absolute load change

`Server.change_factor` (default 0.01) is compared with the change in
load (used slots / slots). With more than 100 slots per server one
session moves load by less than 0.01, so most changes are never
announced (with 500 slots, about every 5th). This dominated the
damped curves in the server-count sweep. Consider damping in units of
slots, or scaling `change_factor` with `Server.slots`, or at least
documenting it.

#### T-32: Scripts still use verbose -1 to mean "no logging"

Verbose level -1 is now the metrics level (per-request lines plus
end-of-run SUMMARY_ counts); silent is -2. Scripts written before
the change pass -1 to mean "no logging" and now get the metrics
level instead: about 2% slower, and per-request lines printed to
stdout. Results are unchanged. To fix (switch to -2, or decide that
-1 is what they want):

- `scripts/run_simulation_sweep.py`: sets `Verbose.level = -1` for its
  in-process runs, so it will now print every request's gap lines to
  the console.
- `scripts/run_simulation_sweep_log.py`: its comment refers to "the
  probe path's silent -1".
- `scripts/measure_one.py`: "null" log mode runs at -1 and says event
  counters are unavailable there. They are now available from the
  SUMMARY_ lines (or directly from `Router.recv_server_metric`,
  `Router.fib_actions` and `Server.server_metrics_created`).
- `scripts/run_scaling_benchmark.py` and
  `scripts/setup/constants_scaling.py`: pair each run with a
  "verbose -1 / null" run to measure compute cost, and sweep
  `(-1, 0, 1, 2, 3)`; add -2 for the compute-only baseline.
- Any local benchmark harness that passes -1 for timing.
- Older logs: a log made at -1 before the change contains no
  per-request lines; at 0 it lacks DECISION_GAP / STALENESS_ERR.
  `quick_stats.py` handles both.

#### T-16: One global seed for every random choice

There is no single seed setting. The `Importer` scripts take `SEED`
from their constants file (`scripts/setup/constants_*.py`), but the
older `experiments/main_*.py` scripts, including
`main_precomputed_t1.py`, hard-code `seed=15112022` in each generator
call, so running another seed needs an edited copy. Add one global
seed (a `SEED` environment variable or command-line option, with the
constants file as the default) that reaches everything random: server
and client placement, server load generators, client request
generation (arrival times, sizes and which client sends each request)
and any other draws (`gen2` in `multi_client_event_generator` uses
seed + 1). Nothing should use numpy's unseeded global generator;
`multi_client_event_generator` did until its client choice was moved
to `gen`.

#### T-16: Set the routing policy through `Importer`

To do with the `Importer` work. `Routing.policy` (`"valley_free"`, the
default, or `"shortest"`) can only be set in Python before
`calculate_forwarding_tables()`. Add `("Routing.policy",
"ROUTING_POLICY")` to the `Importer` mappings, and a `ROUTING_POLICY`
environment variable to `main_precomputed_t1.py` (like `TAU`). Also
reject unknown values in `src/Routing.py`: today only `"shortest"` is
checked, so a typo silently gives valley-free routing
(`c2p_orientation` already raises). The start-up message prints
`valley_free` even when the topology has no `c2p`/`p2p` links, where
the routes are plain shortest-delay paths; say so in the message. Also
warn when a topology has `p2p` links but no `c2p` links: valley-free
routing then leaves many router-server pairs unreachable (a route
learned from a peer is never passed to another peer).

#### T-16: Set utility functions through `Importer`

`Importer` cannot set
`MetricUtility.metric_utility_fn['load']` / `['delay']` or
`MetricUtility.metric_scale['load']`, because they are dict entries
(see the comment in `src/Importer.py`). `main_dfn_2.py` uses a
logarithmic load utility and a geometric user utility; configs run
through `Importer` get the linear defaults. Also decide which
functions are canonical.

#### T-16: `Utility.alpha` is hard-coded in `main_precomputed_t1.py`

It is fixed at 0.5, with no environment variable like `TAU` or
`SERVER_SLOTS`, so testing another alpha needs an edited copy. Add an
`ALPHA` variable. Note that at alpha 0.5 a router only removes a FIB
entry when a server is both full and at the network's maximum delay,
so normal runs never exercise `REMOVED`; validating the FIB counters
needed alpha 1.0, `TAU=0.1`, `SERVER_SLOTS=1`.

#### T-16: `TREE_CHILDREN_ONLY` through `Importer` is untested

The flag is mapped in `src/Importer.py`, but only the
`main_precomputed_t1.py` environment variable (`TREE_CHILDREN_ONLY=1`)
has been tested. Other experiment scripts have no switch for it.

#### T-16: Scripts can silently run another checkout's code

The experiment and analysis scripts import from whatever `src/` is on
`PYTHONPATH`. If the shell profile points at one checkout (e.g. the
main `ServiceCast`), running a script in another (a worktree such as
`ServiceCast-refactor`) silently mixes that checkout's experiment
script with the other's simulator. Either have scripts put their own
repository's `src/` (and `scripts/`) first on `sys.path`, or document
running with `PYTHONPATH=src:scripts` from the repository root.

#### T-16: Free the parsed graph once the network is built

To do in the new `main.py`. After `Network.from_graph()` nothing uses
the parsed `Graph` again (the `Network` keeps its own copies of node
types, tiers, external flags and link types), but the experiment
scripts keep it alive in a local variable for the whole run. Only the
caller can drop that reference (`Network` cannot delete the caller's
variable, and emptying the graph inside `from_graph` would be a
surprising side effect). Best: the new `main.py` loads the network
with one builder call, so the graph never reaches the script and is
freed when the builder returns. `Network.from_gml_file()` exists but
needs extending first: use `Graph.from_gml_file` (as
`main_precomputed_t1.py` does), pass through `drop_external` (CAIDA
runs need `False`), and report the parse and build times. Scripts
that build the graph themselves can add `del graph` straight after
`Network.from_graph()`. Either way the routing tables and the run then
reuse its memory. Tested (24 Oct 2026) on
`main_precomputed_t1.py`: output identical at verbose -2 to 3, with
and without clients. Saving: about 0.5-0.85 GiB per CAIDA x 1000 run
with a stripped GML (the graph is ~0.9 GiB, and only part of freed
memory is reused); 1.8 GiB (7.9 -> 6.1 GiB peak) at 100 servers with
a GML that still carries routing tables, where the graph is larger.

#### T-20: Change the utility function

Change utilty fn from:

    return 1 / (1 + alpha * load + (1-alpha) * delay) 

to

    return 1 - (alpha * load + (1-alpha) * delay)

#### T-33: Move the old experiments still in use

Some of the hand-built
experiments (`main_e1`, `main_e2`, `main_ls_lc`, `main_sa`, `main_sm`,
`main_small`, `main_sm_cm`, `main_dfn`, `main_mig_t1`) are still used:
move them to a separate directory rather than deleting them.

Note for the move: the experiments that build their topology in code
(`main_e1`, `main_e2`, `main_sa`, `main_sm`, `main_sm_cm`,
`main_ls_lc`, `main_s1_c5`, `main_small`, `tests/multi_*_test1.py`)
give different output from run to run. Their topologies are Python
sets (e.g. `'a': {'b', ('c', 4)}`), and `Graph.from_dict` adds the
edges in set order, which Python randomises per process (string hash
randomisation). Edge order can decide equal-cost ties, so routes may
differ between runs. This has always been so; the GML-based
experiments and the simulator code are not affected. To make them
repeatable, iterate `sorted(nextLinks, key=str)` in `Graph.from_dict`
(one line), or run them with `PYTHONHASHSEED=0`.

## Performance and memory

#### T-15: Client and server latency rows duplicate the router rows

`Network.install_host_rows` gives every client a latency row to every
server (its access router's row plus the access-link delay), then
gives every server a row to every client by copying those values
(`latency_table[server][client]` is the same float as
`latency_table[client][server]`). Only the ground truth reads them
(`best_replica_utility`, plus the network diameter); requests take
their delay from the links they cross. Cost at CAIDA x 1000
(measured on the tables alone, Oct 2026): 0.42 GiB with 5,000 clients,
3.1 GiB with 33K (1.9 GiB client rows, 1.2 GiB server rows), growing
with clients x servers.

Neither table is needed: compute the latency when it is read, as
`stub[client] + latency_table[access_router[client]][server]`, with
one small entry per client (access router, access-link delay), and the
diameter as the largest stub plus the largest router-row value over
the access routers. Same arithmetic as today, so results should be
identical (check with identical logs on DFN, the 1K topology and a
short CAIDA run); saves almost all of the memory above. The mirror
would only matter with asymmetric latencies, and even then a copy of
the client->server value would be wrong; requests are one-way, so
nothing uses the server->client direction.

Readers to update first: `scripts/run_simulation_sweep.py` reads
`latency_table[server][client]` (agree the change with the script's
owner), and several old experiments print
`latency_table['s1']['c1']` at start-up (`main_e1`, `main_sa`,
`main_s1_c5`, `main_sm_cm`, `main_ls_lc`; `main_sm` reads the client
direction). An accessor such as `network.latency(client, server)`
would keep them working.

#### T-83: Further speed-ups (optional)

Optional; some of these are being tried (Nov 2026). From a profile of
CAIDA with 1000 servers, 50 clients, 60 s simulated,
`TREE_CHILDREN_ONLY=1` (Oct 2026): 35.5M load messages, simulation
19,700 s under the profiler. The announcement-distance prototype (21%)
has already been commented out (see T-38).

Since then (Nov 2026) the simulator is about 2.5-3x faster: arrival
times as plain floats, sort-and-scan in `decide_announcements`, a
cached neighbour list in `announce_metrics`, and packet delivery with
one simpy timeout per hop instead of a process and queue per link.
The shares below are from before these changes; profile again before
acting on them.
- `announce_metrics`: each router now caches its
  `(neighbour, port, destination, is_host)` list. Still possible:
  precompute each router's tree children per server (routing is
  fixed), so the loop only visits them; one entry per router-server
  pair (~1-1.5 GiB as Python lists at CAIDA x 1000, ~0.4 GiB as numpy,
  so best done with the routing-table arrays). A trial with a children
  cache for routers with 32 or more ports (plus two smaller changes)
  gave only about 5% on CAIDA x 1000, for about 0.8 GiB more memory.
  A later trial on the faster code (Nov 2026), caching tree children
  for every router, gave about 15% on the 1K and 10K subsets with
  identical output; full CAIDA memory and speed not yet checked.
- Utility evaluation code (`MetricUtility.evaluate`, `check_in_range`)
  is generic: a dict comprehension per call, `min(max())`, and an error
  message string built on every call though only needed on failure.
  Small now that RIB utilities are stored (most evaluations are gone).
- Per-request ground-truth records (`Network.py`, the three dicts of
  utilities, loads and latencies per request) grow memory slowly, about
  1 MiB per simulated second at CAIDA x 1000 with 50 clients; watch it
  in very long runs.
- GML parsing (~26-63 s for full CAIDA, depending on the machine):
  the tokenizer does ~10 `match.group()` calls, an enum and a namedtuple
  per token; `match.lastindex` and plain tuples would make it 2-3x
  faster. Or cache the built network in a binary file per topology.
  Only worth it for many short runs.

#### T-83: `decide_announcements` with other comparison functions

Every received ServerMetric runs `decide_announcements` over the whole
RIB. With the default comparisons (load and delay, `same_as` and
`less_than`) it sorts and scans, O(R log R). With any other comparison
function, such as an equivalence margin, which need not be transitive,
it falls back to comparing every pair, O(R^2), as before; the guard is
`uses_default_comparisons()` and `tests/test_speedups.py` checks both
paths against the pairwise rule. If margins become the norm, an
incremental version (update the non-dominated set for the one changed
entry) would be the next step; ties, removals and entries that stop
being dominated must come out exactly as now.

#### T-47: Memory per router

About 100 KB per router: 7.9 GB at 91K routers, about 35 GB projected
at 400K. A large share at 91K is the ~9M precomputed routing-table
entries held as Python dicts. A more compact store (arrays indexed by
server, or nextHop only with delays computed on demand) would let
more 100K runs share the Stanford server (196 GB allows about 20
today).

#### T-47: Profile memory on a large run

Nobody has profiled what grows during a run. The 91K run kept growing
to 7.8 GB. Candidates: per-router RIB / FIB / sent tables, packets
queued in the simulation, per-request records kept for metrics.

#### Remaining setup time

After the `Graph.py` lookup fix, loading the full CAIDA GML takes
147 s (was 834 s), but `Network.from_graph` still takes about 120 s
at 91K. The routing tables are now computed with scipy in about 10 s
at 91K with 100 servers (the old pure-Python Dijkstra took 2-5 minutes
on the 16-server, 1.2K-node sweep topology).

#### T-49: Python 3.9 support (only if a machine needs it)

The simulator needs Python 3.10+ only because of the two `match`
statements in `ServerMetricMessageType.to_val` / `from_val`
(`src/Server.py`, added Jan 2023); every other file parses as Python
3.9. Rewriting them as `if`/`elif` (`is` for the enum members, `==`
for the strings) behaves identically and costs nothing (about 10 ns per
call faster). Worth doing only if a machine we want to use has nothing
newer than 3.9 (on some servers the default `python3` is 3.9, with a
newer version installed alongside).

## Metrics and experiments

#### T-04: New metrics: which summaries, and how often

The
long CAIDA runs need statistics during the run as well as at the end,
because a run takes hours or days and steady state comes only after a
warm-up of a few mean session times. At present the simulator prints
only end-of-run totals (`SUMMARY_SERVER_METRICS`, `SUMMARY_FIB_ROUTER`).

Candidates:

- a network-wide progress line every 1000 simulated ms (or a set
  interval): wall time and memory; requests, blocked and not forwarded;
  server load mean, spread and maximum; load changes, announcements and
  withdrawals; FIB changes; RIB size mean, 99th percentile and maximum;
  decided-set size;
- a per-router line (RIB size, decided-set size, degree, messages
  received) at set intervals and at the end, for RIB distributions over
  time; about 15 MB of log per snapshot on CAIDA x 1000;
- per-server lines (announcements sent and suppressed by damping);
- run statistics (set-up and run time, peak memory).

To decide: which of these, the interval for each (simulated milliseconds,
or wall time), the verbose level that enables them, and the line
formats, so that `log_syntax.py` and `quick_stats.py` can read them.
Any per-call timing (e.g. of `decide_announcements`) should stay
optional, since it adds overhead to every decision.

#### T-23: Does RIB size settle at about log(number of servers)?

Hypothesis: Pareto dominance limits each router's RIB to roughly
c * ln(servers) once loads spread out. A 30 s probe showed RIBs about
twice H_n at 10-50 servers, probably because loads are still near zero
early in a run. Test: run 10, 25, 50, 100 and 500 servers to 200000 ms,
snapshotting each router's RIB and non-dominated set size every 10000 ms,
and compare the median and 90th percentile with H_n. The per-router RIB
summary lines proposed under "New metrics" would provide the data.

#### T-22: Compare with anycast

Run the same scenarios with anycast as a baseline for accuracy and
blocking. In "ideal anycast", each router has a fixed entry for its
lowest-delay server over the policy paths, and no load information is
used. This is the best case for anycast. It needs a flag in
`Server.send_load_packet` to stop announcements. A "BGP-like" variant
(class, then fewest AS hops, then delay) would be a second
baseline. Provision server slots with Erlang-B at nominal demand, so that both schemes are
compared at the same blocking target. Claim that ServiceCast adapts
automatically and within seconds, not that anycast cannot adapt: real
anycast does adapt, slowly.

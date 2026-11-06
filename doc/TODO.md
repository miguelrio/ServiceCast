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

**Implemented, off by default (Nov 2026):** `Router.announce_freed_after_withdraw`
(`ANNOUNCE_FREED=1` in `main_precomputed_t1.py`). After a withdrawal,
`announce_freed_entries` announces the entries that are no longer
dominated. With the default comparators it does little work: nothing if
the withdrawn entry was not announced (it frees nothing) or every other
entry is announced; otherwise one pass for a candidate (an unannounced
entry the withdrawn one was at least as good as), and only if there is
one, the sort-and-scan decision. Other comparators decide again in full.
`tests/test_announce_freed.py` checks it against a full decision.

Measured (200-300 s runs, tree-children forwarding on, fix on vs off):

- Topology Zoo DFN and Cogentco, 5 placements each: 0-4% more messages;
  accuracy the same or up to 0.7 points better on 9 of 10, 0.2 points
  worse on one.
- 1K CAIDA subset, one placement: 7.9% more messages, about 12% more
  run time (two thirds of it processing the extra messages, which cost
  the same per message as the others), accuracy 61.8% vs 62.9%.
- 1K CAIDA subset, 5 server placements (seeds 1-5; ms code, 200 s,
  TAU 20 ms): 5-10% more messages (mean 7.2%); accuracy up on 4
  placements (+0.2 to +0.65 points) and down on the first (-0.9), mean
  +0.2 points (62.5% to 62.7%); mean utility gap slightly worse on
  average (0.451% to 0.458%: better on 2, worse on 3); FIB churn about
  0.6-1 point lower on every placement. A small, mixed effect on accuracy
  for the extra messages.
- Each freed entry starts a chain of messages downstream: about 10 on
  Cogentco, about 5 on the 1K subset. Part of it would be sent anyway at
  the next decision; the rest is the extra traffic above.
- Where the extra time goes on the 1K subset (86 s on top of 707 s):
  of 14.4M withdrawals, 6.7M are of announced entries and 5.1M pass the
  pre-checks; 1.2M of those free an entry. The checks take about 26 s
  (about 3% of run time), sending the freed announcements about 22 s,
  and the rest is routers downstream processing the extra messages.
  Skipping withdrawals of unannounced entries halved the checks and
  saved about 12 s; the sort-and-scan decision saved nothing over a
  direct check (the direct check usually stopped early).

- Full CAIDA x 1000 (1,000 servers, 5,000 clients, 100% load, TAU 2 ms,
  to 30 s simulated, one placement; washington, run alongside 3 others):
  16.5% more messages on path (182.9M to 213.1M), 18% more run time
  (12,537 s to 14,792 s), the same peak memory (10.9 GB). Accuracy 44.1%
  to 46.3% (+2.2 points) and mean utility gap 0.731% to 0.691% on 15,014
  requests. The gain shrinks during the run: +3.2, +2.4 and +0.8 points
  in the three 10 s windows, so it is mostly the warm-up, where servers
  first become known; 30 s is well short of settling. FIB churn 32.6% to
  29.8%, but only because there are more FIB decisions (114M to 130M):
  the number of replica changes went up by 4% (16.0M to 16.7M).

Summary: the fix costs messages and run time in proportion to the
network's size (0-4% on the Topology Zoo, about 7% and 12% on the 1K
subset, about 17% and 18% on x 1000). It improves accuracy while
servers are first being learned, but after settling (the 200 s 1K runs)
the effect is within the placement-to-placement variation. Not yet
measured: a settled x 1000 run.

Still to decide: on or off for the paper runs. On measures the
protocol's overhead more honestly (a router would announce an entry
that nothing beats any more) and gains some accuracy; off saves run
time (about 18% at full CAIDA scale). Off until then.

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

- `legacy/run_simulation_sweep.py`: sets `Verbose.level = -1` for its
  in-process runs, so it will now print every request's gap lines to
  the console.
- `legacy/run_simulation_sweep_log.py`: its comment refers to "the
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

#### T-16: `main.py` follow-ups

`experiments/main.py` (e4b39d7, 5 Nov 2026) is the one run entry point:
code defaults, then a config file, then `--set` overrides (see
`doc/Workflow.md`). It covers the earlier T-16 entries here: one `SEED`
for the run, `ROUTING_POLICY` (unknown values refused), utility and
comparison functions and `ALPHA` as settings, the tree-children flag as a
setting, the parsed graph freed after the network is built, and its own
checkout's `src/` and `scripts/` first on the path. Still open:

- **Server load generator seed.** `Generator.server_load_event_generator`
  draws from `gen2 = np.random.RandomState(seed=0)` whatever the run's
  `SEED` (it drives the background load, off by default). Derive it from
  the run seed, as `multi_client_event_generator` does (`seed + 1`).
  This changes results for runs with background load.
- **Which utility functions are canonical.** The functions can now be
  chosen by name (`METRIC_LOAD_FN`, `METRIC_DELAY_FN`, `USER_UTILITY_FN`;
  linear by default), but which ones the paper runs use is still to be
  decided (with T-20). `main_dfn_2.py` used a logarithmic load utility
  and a geometric user utility.
- **Other scripts can run another checkout's code.** `main.py` puts its
  own repository's `src/` and `scripts/` first on `sys.path`, but the
  analysis scripts in `scripts/` and the older experiment scripts still
  import from whatever `src/` is on `PYTHONPATH`. With the shell profile
  pointing at one checkout, running them in another (a worktree, or a
  `git archive` copy) silently mixes the two. Either give them the same
  path set-up, or document running them with `PYTHONPATH=src:scripts`
  from the repository root.

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

#### T-85: Move remaining old scripts and other leftovers out of the way

The old change-factor collectors and `constants_v1.py` moved to `legacy/` on
6 Nov 2026. The active matrix path is `experiments/sweep.py` plus
`scripts/log_metrics.py`, `scripts/sweep_metrics.py` and
`scripts/plot_change_factor_matrix.py`; these are not move candidates.

Remaining candidates:
- the scaling benchmark's own run path: `scripts/run_scaling_benchmark.py`,
  `scripts/measure_one.py`, `scripts/placement.py` and
  `scripts/setup/constants_scaling.py`; migrate it to `main.py` or move it;
- `scripts/quick_look.py`, which reads scaling-benchmark CSV output;
- old Importer-era settings and experiments not used by the active path;
- old documentation after its active content has been separated;
- `results/`, and the ad hoc tests in `tests/` that are not `test_*.py`.

The legacy probe is not a current cross-check: it counts messages by wrapping
`LinkEnd.put`, which packets no longer pass through since the Nov 2026 speed-ups,
so its message counts are 0. `log_metrics.py` remains active and intentionally
counts per-event lines at verbose level 1 rather than reading `SUMMARY_` lines.

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

Readers to update first: `legacy/run_simulation_sweep.py` reads
`latency_table[server][client]` (agree the change with the script's
owner), and several old experiments print
`latency_table['s1']['c1']` at start-up (`main_e1`, `main_sa`,
`main_s1_c5`, `main_sm_cm`, `main_ls_lc`; `main_sm` reads the client
direction). An accessor such as `network.latency(client, server)`
would keep them working.

#### T-83: Further speed-ups (done; options left for later)

Closed 6 Nov 2026. In Nov 2026 the simulator became about 2.5-3x
faster (79abb0e: arrival times as plain floats, sort-and-scan in
`decide_announcements`, a cached neighbour list in `announce_metrics`,
one simpy timeout per hop), then about 15% faster again at full scale
with slower garbage collection (8e3e9f7). What was tried on full CAIDA
(about 97K routers, 1000 servers, 5000 clients, full load):

- **Raised garbage-collector thresholds: committed (8e3e9f7).** Python's
  cycle collector took about 17% of the run time, mostly in full
  collections rescanning ~8M objects. `src/Network.py` now sets
  `gc.set_threshold(100_000, 50, 1000)` on import: about 15% less run
  time, identical output, memory +0.2%.
- **`gc.freeze()` after set-up: slower.** The collector's share rose to
  about 22%: with the set-up objects frozen, Python 3.11 starts full
  collections more often.
- **Tree-children cache in `announce_metrics`: not committed.** Caching
  each router's tree children per server gave about 15% on the 1K and
  10K subsets with identical output, but only 2.6% on full CAIDA, for
  13% more memory (about 1.4 GB). An earlier variant (routers with 32 or
  more ports) gave about 5% for 0.8 GB.

Subset timings overstated both cache trials, so any further change
should be timed on full CAIDA before it is adopted.

Options left, optional and for later (shares from a full-CAIDA profile,
Nov 2026):
- Reuse the result of `uses_default_comparisons()` instead of working
  it out for every received message: about 2% at full scale (3.5% on
  the 1K subset), same output.
- Small changes, together about 3-4%, same output: `Router.id()` (about
  3.5% of samples on its own) replaced by the stored id in hot paths,
  fewer `round()` and `str()` calls outside printing, `Server.to_val`
  as a lookup instead of a `match`, and the generic utility evaluation
  (`MetricUtility.evaluate`, `check_in_range`: a dict comprehension and
  an error message built on every call).
- An incremental FIB choice, or an incremental decided-set choice (see
  the next entry): update the result for the one changed entry instead
  of rescanning the RIB. More code, and ties must come out exactly as
  now.
- Faster GML parsing (~26-63 s for full CAIDA, depending on the
  machine): the tokenizer does ~10 `match.group()` calls, an enum and a
  namedtuple per token; `match.lastindex` and plain tuples would make it
  2-3x faster. Or cache the built network in a binary file per
  topology. Only worth it for many short runs.

Memory to watch: the per-request ground-truth records (`Network.py`,
three dicts of utilities, loads and latencies per request) grow about
1 MiB per simulated second at CAIDA x 1000 with 50 clients.

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

# Bugs

#### GML loader ignores `clientCount`

The topology generator writes one `client_<City>` node per city with
a `clientCount` attribute. `Network.from_graph` makes one `Client` per
node and ignores the count. On
`dg-1000as-100servers-100clients-with-routes` there are 49 client
nodes, and their counts add up to 91, not the 100 requested, so the
generator is short too. Total load is unaffected (`TAU` sets the
network-wide request rate), but the number of request sources is.
Decide whether the loader should create `clientCount` clients, or the
generator should write one node per client, and fix the generator's
total.

Postponed (2026-10-14) until we have aligned with Miguel on the next
version of the topology generator.

#### `run_simulation_sweep_log.py` has no `import subprocess`

So the sweep results always record the git commit as "unknown". A
one-line fix, left for Wes (his script).


# Issues

#### Scripts still use verbose -1 to mean "no logging"

Verbose level -1 is now the metrics level (per-request lines plus
end-of-run SUMMARY_ counts); silent is -2. Scripts written before
the change pass -1 to mean "no logging" and now get the metrics
level instead: about 2% slower, and per-request lines printed to
stdout. Results are unchanged. Wes is looking at these (2026-10-13),
and the experiment workflow proposal will cover the sweep scripts. To
fix (switch to -2, or decide that -1 is what they want):

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

#### Unreachable servers with valley-free routing

Owner: Miguel (2026-10-13). Investigate why valley-free routing makes
servers unreachable, then decide between relaxing the rules and
constraining server placement.

Valley-free (Gao-Rexford) routing leaves some router/server pairs with
no valid path. On the CAIDA topology
(`caida_routing_valley_free-v2-seconds-nodemand.gml`) there are 37,710
such pairs, and one client access router (`10133-p0`, `client_Istanbul`)
cannot reach 20 of the 100 servers.

Routing copes with this: a router only chooses among servers it has a
route to, and a request arriving at a router with no FIB entry for the
service is dropped (`Router.client_request_packet` logs
`REQUEST_NOT_FORWARDED`, at every verbose level). The ground-truth "best server"
calculations in `Network.py` (`inject_snapshot_optimal_utility` and the
arrival-time `OUTCOME_GAP` calculation) looked up the latency to *every*
server and crashed with a `KeyError` on the first unreachable one.

**Workaround (2026-10-08):** both calculations skip servers with no
latency-table entry, so "best" means the best *reachable* server, the
same set the router chooses from.

Still to decide:
- Rethink the valley-free restrictions: are they too strict for this
  use, e.g. should a router fall back to a non-valley-free path?
- Only place servers (and clients) where every client can reach every
  server, or report unreachable pairs when a topology is generated.
- Should results report how many requests had a reduced server set?

#### Default link delay is hard-coded and inconsistent

Owner: Miguel (2026-10-13). A plan is agreed for the default delay and
for ms vs s; Miguel fixes them in the next version of the topology
generator, after further discussion with the group.

Links touching an `Internal 0` node (every server and client attachment)
never use the GML `delayMs`: `Gml.py` checks for external nodes before
it reads `delayMs`, so these links get `Graph.default_propagation_delay`.
`Network.from_graph` also replaces any 0 weight with the default.
The default value is set in several places that must agree but are not
linked to each other:

- `src/Graph.py`: class default `default_propagation_delay = 1`
- Experiment scripts: 7 set it to `0.1`, 1 sets it to `1`, others take
  it from a parameter (`knobs["prop_delay"]`, `GRAPH_DELAY` via
  `Importer.py`)
- `scripts/setup/constants_*.py`: `GRAPH_DELAY = 1` (dfn_2),
  `0.1` (dfn_equiv), `GRAPH_DELAYS = [0.1 ... 4.0]` (v1 sweep)
- `scripts/add_routing_tables.py` and
  `scripts/add_routing_tables_valley_free.py`: hard-coded
  `ENGINE_DEFAULT_PROPAGATION_DELAY = 0.1`, so precomputed tables
  silently go wrong if an experiment uses any other value
  (this caused the delay-utility < 0 crash on 2026-10-08)
- `Host.add_neighbour` / `Router.add_neighbour`: `propdelay=1` defaults

To do:
- Make the default link delay a single configured parameter, as the
  older experiment scripts did. Nothing should hard-code it.
- The route adders should read the same value (a command-line option,
  or a value recorded in the GML), not a constant.
- Choose a sensible default for seconds: about `0.005` (5 ms) for an
  access link. 0.1 s is far longer than the core links (median 6 ms
  on the 1K topology, 16.5 ms on CAIDA).
- Decide whether access links should use the GML `delayMs` when it is
  present, rather than always using the default.
- Check consistency across the simulator, the topology generator and
  the route adders:
  - units: the simulator reads seconds, but the CAIDA GMLs were written
    in milliseconds
  - which edges count as links: client-server `demand` edges were
    loaded as links and silenced 51 servers on CAIDA. The loader now
    ignores them (2026-10-14); the generator should stop writing them
  - the same link-weight rule everywhere

#### Engine-built latency tables leave out server access links

`Router.weight_edge(dest)` only handles `str` and `Router`, so it
returns 0 when `dest` is a `Host` (Server or Client). Latency-table
paths from a router to a server therefore leave out the server's
access link, the network diameter comes out short (by about 0.1 s with
the usual default), and announced delays, which do include that link,
can exceed it. The run then crashes with `MetricUtility: metric utility
for 'delay' ... not in range 0 -> 1`. Reproduce with Cogentco, 20
servers, 10 clients. Precomputed tables avoid this only because the
route adders apply the engine's link rule themselves.

Decided (2026-10-14): client and server links to routers must never
have weight / latency 0; they take the default delay unless the GML
gives one. Kept as a TODO until the experiment workflow and the
config / `Importer` logic are resolved, since the fix
(`isinstance(dest, (Router, Host))`, and the same rule in the route
adders) changes the results of every engine-routed experiment.
`Router-old.py` / `Router-dict.py` would need the same change.

#### Change the utility function

Change utilty fn from:

    return 1 / (1 + alpha * load + (1-alpha) * delay) 

to

    return 1 - (alpha * load + (1-alpha) * delay)

#### Announcement Radius

Still to be refined.
Draft formula not correct.


#### Client Request Forwarding

Currently we have hop-by-hop forwarding,
so each Router will check which is the best for the service name.

An alternative is to change the service name to an address
at the first Router.

#### Load values

**DONE**
- Load values are not in range 0 -> 1.
- Currently based on slot.

#### Delay values

**DONE**
- Map delay from actual values into range 0 -> 1.

- Added to `Network.py`  `get_delay_utility()` function
  which calculates: delay / network_diameter()


#### Utility function value

**DONE**
- Ensure Utility is in range 0 -> 1.
- Check before returning from Utility.forwarding_utility_fn


**DONE**  
The Utility function has been changed so that:
- 0 is the worst value
- 1 is the best value
- Output is always in range (0, 1]

Changes made:
- `Utility.py`: Changed `forwarding_utility1` to return `1 / (1 + alpha * load + (1-alpha) * delay)`
- `Router.py`: Changed comparison from `<` to `>`, initial `best_utility` from `-inf` to `-1`, and added initialization of `best_neighbour` and `servicename`
- `Network.py`: Added `reverse=True` to sort for maximum utility
- `main_ls_lc.py`, `main_sm_cm.py`, `main.py`: Updated custom utility functions
- `Variables.md`: Updated documentation examples



####  Server metrics update

**DONE**
- Servers should have load_utilty in range 0 -> 1.
- We can divide load by total slots 

- Adjust load_up_fn and load_down_fn to be slots_up_fn and slots_down_fn 
- Make load derived from slots.

Changes made:
- Server keeps track of slots used in self.used_slots
- The calculate load function = used_slots / slots
- Changed calculate_load_difference()

**DONE**
Fixed issue when there are no more slots in the whole system.

# TODO

## Performance

Figures from the October 2026 scaling runs
(`results/precomputed-scaling-20261008/`).

Accepted (2026-10-13): the limits are understood and no optimisation is
planned for now. Long runs go in parallel on other machines, including
the two testbed servers once they are installed.

#### Memory per router

About 100 KB per router: 7.9 GB at 91K routers, about 35 GB projected
at 400K. A large share at 91K is the ~9M precomputed routing-table
entries held as Python dicts. A more compact store (arrays indexed by
server, or nextHop only with delays computed on demand) would let
more 100K runs share the Stanford server (196 GB allows about 20
today).

#### Profile memory on a large run

Nobody has profiled what grows during a run. The 91K run kept growing
to 7.8 GB. Candidates: per-router RIB / FIB / sent tables, packets
queued in the simulation, per-request records kept for metrics.

#### Remaining setup time

After the `Graph.py` lookup fix, loading the full CAIDA GML takes
147 s (was 834 s), but `Network.from_graph` still takes about 120 s
at 91K. When the simulator builds its own routing tables (no
precomputed tables), the 16-server, 1.2K-node sweep topology spends
2-5 minutes in that before the simulation starts.

#### `decide_announcements` is quadratic in RIB size

Every received ServerMetric runs `decide_announcements`, which
compares each RIB entry with every other one (O(R^2)), then the FIB
utility loop. This is the main cost per update, and why cost per
update varies with the number of servers. An incremental version
(update the non-dominated set for the one changed entry) would cut it.

## Enhancements

#### Scripts can silently run another checkout's code

The experiment and analysis scripts import from whatever `src/` is on
`PYTHONPATH`. If the shell profile points at one checkout (e.g. the
main `ServiceCast`), running a script in another (a worktree such as
`ServiceCast-refactor`) silently mixes that checkout's experiment
script with the other's simulator. Either have scripts put their own
repository's `src/` (and `scripts/`) first on `sys.path`, or document
running with `PYTHONPATH=src:scripts` from the repository root.

#### `Utility.alpha` is hard-coded in `main_precomputed_t1.py`

It is fixed at 0.5, with no environment variable like `TAU` or
`SERVER_SLOTS`, so testing another alpha needs an edited copy. Add an
`ALPHA` variable. Note that at alpha 0.5 a router only removes a FIB
entry when a server is both full and at the network's maximum delay,
so normal runs never exercise `REMOVED`; validating the FIB counters
needed alpha 1.0, `TAU=0.1`, `SERVER_SLOTS=1`.

#### `TREE_CHILDREN_ONLY` through `Importer` is untested

The flag is mapped in `src/Importer.py`, but only the
`main_precomputed_t1.py` environment variable (`TREE_CHILDREN_ONLY=1`)
has been tested. Other experiment scripts have no switch for it.

#### Damping uses an absolute load change

`Server.change_factor` (default 0.01) is compared with the change in
load (used slots / slots). With more than 100 slots per server one
session moves load by less than 0.01, so most changes are never
announced (with 500 slots, about every 5th). This dominated the
damped curves in the server-count sweep. Consider damping in units of
slots, or scaling `change_factor` with `Server.slots`, or at least
documenting it. To be handled by the planned review of the default
thresholds (2026-10-13).

#### Experiment workflow proposal

Owner: David (2026-10-13). A concrete proposal for creating and running
experiments, single runs and sweeps alike, to share with the group. It
should settle: one config format (extended `Importer` constants files
or something else); per-run `--set` overrides or config files only;
where configs live and how results directories are named; the
provenance kept with every run (config copy, git commit, seeds); how
many parallel runs per machine and who manages the queue; the sweep
scripts; and what happens to the existing scripts once the new
workflow is validated.

#### Set utility functions through `Importer`

Agreed (2026-10-13), to do in the near future. `Importer` cannot set
`MetricUtility.metric_utility_fn['load']` / `['delay']` or
`MetricUtility.metric_scale['load']`, because they are dict entries
(see the comment in `src/Importer.py`). `main_dfn_2.py` uses a
logarithmic load utility and a geometric user utility; configs run
through `Importer` get the linear defaults. Also decide which
functions are canonical.

#### Move the old experiments still in use

Agreed (2026-10-13, Stuart's suggestion). Some of the hand-built
experiments (`main_e1`, `main_e2`, `main_ls_lc`, `main_sa`, `main_sm`,
`main_small`, `main_sm_cm`, `main_dfn`, `main_mig_t1`) are still used:
move them to a separate directory rather than deleting them.

#### Topology generator improvements

Owner: Miguel (2026-10-13); proposals discussed, work continues
alongside the rest. Questions raised about `scenario-explorer-12.html`:
real AS locations for CAIDA (PeeringDB, CAIDA AS-to-organisation, IP
geolocation) instead of random geography; a larger city list than the
82 hard-coded `CITIES`; PoP counts and tiers from real data, and the
8-PoP cap and full internal mesh; client rounding (see the
`clientCount` bug); one copy of the generator, with the seed recorded
in each GML.

#### New metrics

Postponed (2026-10-13). Proposed so far: per-router summary lines
(RIB size at the end of the run and its peak, non-dominated set size),
per-server summary lines (announcements sent and suppressed by
damping), periodic progress lines, and run statistics.

## Experiments to run

#### Does RIB size settle at about log(number of servers)?

Hypothesis: Pareto dominance limits each router's RIB to roughly
c * ln(servers) once loads spread out. A 30 s probe showed RIBs about
twice H_n at 10-50 servers, probably because loads are still near zero
early in a run. Test: run 10, 25, 50, 100 and 500 servers to 200 s,
snapshotting each router's RIB and non-dominated set size every 10 s,
and compare the median and 90th percentile with H_n. The per-router RIB
summary lines proposed under "New metrics" would provide the data. Part of
the evaluation plan, to be refined (2026-10-13).


# Experiments


## 2021

1 - Generate demand
  we will have two windows, one for sampling the demand (ground truth) and one for sending the updates
Updates can be sent:
  - synchronously (every fixed interval): interval
  - asynchronously (after a threshold crossing, compared with the last value sent): threshold
  - combination of both
2 - fix hardcoding of individual router2s
  - e.g. some kind of adjacency list
        constructs the routers on the fly
        creates links on the fly
3 - write forwarding algorithm
4 - put metrics in packets

have load generater (LG) of load from a normal distribution
  - configured with a mean and a stddev
have another distribution that can update the mean of LG
  - this can be poisson, always up, always down,
  - from a time-series, or other we device
  - have a knob to adjust stddev in LG so that that range of values will be closer to mean or further away

# Algorithm

1  LOAD TOPOLOGY
2  ALLOCATE REPLICAS
3  ALLOCATE CLIENTS
4  REPLICAS SEND LOAD
5  LOAD GETS PROPAGATED
6  FORWARDING TABLE UPDATED
7  GENERATE DEMANDS - INCLUDING DURATION
8  REQUESTS GET PROPAGATED TOWARDS REPLICA
9  REPLICAS UPDATE INTERNAL LOAD INFO
10 REPLICAS SEND UPDATES
11 LOAD UPDATES GET PROPAGATED
12 ROUTERS UPDATE FORWARDING TABLE


# Network topologies

Potential networks to look at from topology zoo

- abilene
- BICS
- BT Europe
- Cogent
- Colt Telecom
- GEANT

WorldWide
- AboveNet
- Cogent
- Deutsche Telecom *
- EasyNet
- Hibernia Atlantic
- Hostway International
- Hurricane Electric
- Internode
- NTT *
- Tinet *

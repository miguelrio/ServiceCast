# Changes to the simulator

Changes to simulator behaviour, defaults and outputs, newest first,
especially those that **change results**. Each entry gives the date, the
to-do ID where there is one (T-nn), and what a run will show differently.
Started in Nov 2026; the entries before that are summarised from the
commit messages.

## Not yet committed

- **New run entry point `experiments/main.py` and a rewritten `Importer`
  (T-16).** `python3 experiments/main.py [CONFIG] [--set NAME=VALUE ...]`:
  each setting comes from `--set`, else the config file (`.py` or `.json`),
  else its default in the code; no environment variables. One table of 35
  settings in `src/Importer.py`; run settings (topology, run length, seed,
  workload, clients used) are attributes of the new `src/Run.py`. Unknown
  names and invalid values (routing policy, function names) are errors.
  Utility and comparison functions are chosen by name; the metric utility
  functions can now be set. All times in ms, as in the simulator. The log
  header keeps the old lines and adds `config_file`, `git_commit` and every
  resolved setting. `Routing.policy` now rejects unknown values (a typo
  used to mean valley-free) and warns on stderr when a topology has p2p but
  no c2p links. **Breaks** the old Importer interface (`import_from_path`),
  used by `scripts/run_simulation_sweep_log.py` and the three
  `experiments/*import*.py` scripts. Output is unchanged:
  `configs/precomputed_t1.py` gives logs identical to
  `main_precomputed_t1.py` apart from the header.
- **Tree-children forwarding on by default (T-13).**
  `Router.forward_to_tree_children_only` is now True: a router sends a
  ServerMetric update only to neighbours whose unicast next hop to the
  replica is this router; the others would drop it as off the unicast
  route. Far fewer messages are sent and runs are faster: on the 1K CAIDA
  subset (200 s), 33M instead of 532M messages and about 8x faster (710 s
  vs 5,700 s CPU). A new end-of-run line, `SUMMARY_TREE_CHILDREN`, counts
  the updates not sent (announcements and withdrawals), and
  `quick_stats.py` prints on-path, off-path and total messages the same
  way for both settings. Counting costs no measurable time.
  **Changes results slightly on busy networks:** with the flag off, the
  off-path messages take transmission time on the outgoing port
  (`SwitchPort`) and delay the on-path messages queued behind them. On a
  lightly loaded network (Topology Zoo DFN, Cogentco) the two settings
  give the same decisions and outcomes, and the not-sent counts equal the
  flag-off drops exactly (repo test `tests/test_tree_children.py`). On
  the 1K subset the runs diverge after about 20 s, so the counts agree
  only to about 0.3% (off path 497.7M not sent vs 499.2M dropped).
  `TREE_CHILDREN_ONLY=0` turns it off in `main_precomputed_t1.py`.
- **Option to announce entries freed by a withdrawal at once (T-12), off
  by default.** With `Router.announce_freed_after_withdraw = True`
  (`ANNOUNCE_FREED=1` in `main_precomputed_t1.py`), after a withdrawal a
  router announces the entries that only the withdrawn one was
  dominating; otherwise they wait for the next announcement to reach that
  router. Off, results are unchanged. On, it changes results: on the 1K
  CAIDA subset 7.9% more messages and about 12% more run time, accuracy
  61.8% vs 62.9% (one placement); on Topology Zoo DFN and Cogentco 0-4%
  more messages and accuracy mostly the same or slightly better. Left off
  until it is checked on more placements and full CAIDA.
  `main_precomputed_t1.py` now prints the setting in its parameter header.
- **Default link delays (T-17).** Core links given no delay now get 10 ms
  (`Graph.default_propagation_delay`, was 1000 ms); server links 1 ms and
  client links 10 ms as before. A `delayMs` of 0, or a weight of 0, counts
  as not given (a delay of 0 is not physical) and gets the default for its
  kind of link, as before. Links built in code without a weight get these
  class defaults (they got 1 ms). **Changes results** for networks with
  core links that have no `delayMs` and no location, or a `delayMs` of 0,
  and for networks built in code without weights (the older toy
  experiments). CAIDA builder GMLs and the placed Topology Zoo GMLs
  carry a delay on every link and are not affected; scripts that set
  `Graph.default_propagation_delay` themselves keep their value.

## 4 Nov 2026

- **Milliseconds everywhere (T-30, fd7e12f).** Config values, the
  command line, environment overrides, log lines and reports are now in
  ms, like the clock; nothing converts from seconds any more. The `until`
  argument, `TAU`/`ARRIVAL_LAMBDA`, `GRAPH_DELAY`, `size_lambda` and the
  `Network.start(until=...)` bound must be given in ms: the defaults went
  from 360 to 360000, 0.4 to 400, size_lambda 10 to 10000. A launch
  command written for seconds still runs, silently 1000 times too short
  or too busy (`... 300` is now 300 ms; `TAU=0.1` is now 0.1 ms).
  A client request now carries its session duration (ms) apart from its
  packet size (bytes). **Changes results slightly:** session lengths were
  whole seconds and are now whole ms, from the same random draws, so they
  average about 0.5 s (0.5%) longer and end at different times. Rounding
  down to a whole second lost 0.5 s on average, and the 1% of sessions
  drawn shorter than 1 s lasted 0 s; they now last their drawn length,
  rounded down to the ms. Packet
  sizes are unchanged. `log_syntax.py` still reads older logs.
- `Router.weight_edge` looks up router and host neighbours the same way
  (728db45).

## 3 Nov 2026

- Speed-ups (79abb0e, about 2.5-2.8x): sort-and-scan choice of entries
  to announce, single announce loop, direct packet delivery, float
  arrival times. Same results apart from the order of events at the same
  time, which can change which of two equal-utility servers is picked.

## 1 Nov 2026

- Routing for the new CAIDA topologies (e0a084e): observed customer cones,
  a crossing delay (`internalDelayMs`) for single-router ASes, and
  embedded-server scope. Changes routes on GMLs that carry these.

## 26 Oct 2026

- The announcement-radius prototype is commented out (it only printed);
  RIB entry utilities are cached (5fd44d1).

## 23 Oct 2026

- Routing tables are computed in the simulator at start-up (scipy);
  precomputed `nextHop` lines in GMLs are ignored (87894a3).

## 22 Oct 2026

- Server and client attachment links use the GML `delayMs`, with
  defaults of 1 ms (server) and 10 ms (client) when unset (be9d8da).

## 21 Oct 2026

- The simulator clock is in milliseconds; GML `delayMs` means ms, config
  and command-line times stay in seconds (ac47ee4, fixes in 9e9195f).

## 14 Oct 2026

- Bug fixes: utility rounding, hosts forced single-homed, client-server
  demand edges and access/demand link types ignored when loading GMLs
  (aa08184, 3983e37).

## 13 Oct 2026

- Verbose level -1: per-request metric lines and end-of-run summaries for
  large runs (bc8c788).

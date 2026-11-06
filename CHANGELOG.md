# Changes to the simulator

Changes to simulator behaviour, defaults and outputs, newest first,
especially those that **change results**. Each entry gives the date, the
to-do ID where there is one (T-nn), and what a run will show differently.
Each entry is committed together with the change it describes; its
commit hash is added in a later update.
Started in Nov 2026; the entries before that are summarised from the
commit messages.

## Not yet committed

(nothing yet)

## 6 Nov 2026

- New `experiments/sweep.py`: runs the change-factor matrix as independent
  `main.py` subprocesses, validates each final `DONE`, keeps per-cell logs and a
  manifest, and writes the existing matrix JSON format. The 3 x 3 DFN definition
  is `experiments/sweeps/dfn_thresholds.py`; shared aggregation is in
  `scripts/sweep_metrics.py`. The obsolete change-factor collectors and their
  old `constants_v1.py` configuration are now in `legacy/`; they are historical
  references, not supported entry points.

## 5 Nov 2026

- New `experiments/sweep_simple.py` (158e594): an example sweep, two nested loops of
  `main.py` calls (server change factor x FIB update threshold on the DFN
  example, 360 s runs), with no options or checks. Referenced from
  `doc/Workflow.md`.
- **New code defaults (T-16, e4b39d7).** `Server.slots` 50 (was 10),
  `Server.change_factor` 0.0001 (was 0.1) and
  `Router.fib_utility_update_threshold` 0.0001 (was 0.1). By default a
  server now announces every load change and a router's FIB follows any
  real improvement in utility (0.0001 rather than 0, so float rounding
  never flips a FIB). **Changes results** for any script that relied on
  the old defaults; scripts that set these values themselves, such as
  `main_precomputed_t1.py` (50, 0.01, 0.001), are unaffected. Against the
  0.001 FIB threshold used so far, routers may also switch on improvements
  between 0.0001 and 0.001. The change factor of 0.0001 and the 0.01 used
  so far behave the same at 50 slots (one slot is 0.02).
- **New run entry point `experiments/main.py` and a rewritten `Importer`
  (T-16, e4b39d7).**
  `python3 experiments/main.py [CONFIG] [--set NAME=VALUE ...] [--dump-config]`.
  Each setting comes from `--set`, else the config file (a Python file of
  `NAME = value` lines), else its default in the code. One table of 36
  settings in `src/Importer.py`; run settings (topology, run length, seed,
  workload, clients) are attributes of the new `src/Run.py`. All times in
  ms. Unknown names and invalid values (routing policy, function names) are
  errors; utility and comparison functions are chosen by name; the metric
  utility functions can now be set. The topology must be given
  (`GML_FILE`; no default). `CLIENTS` (None: all of the file's clients; 0:
  none; N: the first N) replaces `NOCLIENTS`/`NCLIENTS_USE`. Runs default
  to `VERBOSE_LEVEL` -1 (the class default stays 1) and to `UNTIL` 500000.
  The log goes to stdout and ends with a `DONE` line only if the run
  completed; `log_syntax.py` (and so `quick_stats.py`, `window_stats.py`,
  `plot_load.py`) prints a note when a `main.py` log has no `DONE`. The log
  header lists the command line, config file, git commit, GML and sidecar
  checksums (16 hex characters), then every setting in config form with
  its source (`SERVER_CF = 0.05   # command line`); `--dump-config` prints
  the same block as a config file. The header also ends at the `RUN ---`
  line, so 0-client runs parse. The header is printed before anything else, including
  warnings, so a log that merges stderr (`memprobe.py`) still starts with
  it; GML progress lines go to stderr. `window_stats.py` counts a `main.py`
  log as complete only with its `DONE` line. The GML
  should be simulator-ready, in `topologies/ready/` (new, with a README):
  provenance, servers placed and the mark `simulatorReady 1`; for now a
  file without these gets a warning (they will become errors). A missing
  or mismatched sidecar, a file with no servers, or no clients (unless
  `CLIENTS = 0`) stops the run. `Routing.policy` now rejects unknown values
  (a typo used to mean valley-free) and warns on stderr when a topology has
  p2p but no c2p links. Output is unchanged: `configs/precomputed_t1.py`
  gives logs identical to `main_precomputed_t1.py` apart from the header.
  **No longer accepted (for anyone with their own scripts):**
    - the old Importer interface (`Importer(globals()).import_from_path`,
      `configure_system_variables`): `scripts/run_simulation_sweep_log.py`
      and `experiments/main_importer.py`, `main_dfn_2_import.py`,
      `main_dfn_equiv_import.py` no longer run;
    - environment variables (`SERVER_CF`, `SERVER_SLOTS`,
      `TREE_CHILDREN_ONLY`, `TAU`/`ARRIVAL_LAMBDA`, `NOCLIENTS`,
      `NCLIENTS_USE`) in `main.py`: use `--set`;
    - JSON configs;
    - the old header rows (`Server.slots = 50`, `until = ...`):
      `main.py` logs name settings as in a config (`SERVER_SLOTS = 50`,
      `UNTIL = ...`). `window_stats.py` and `quick_stats.py` read both;
      other readers of header names need the new ones;
    - GMLs without provenance or `simulatorReady` (the
      `scenario-explorer` and `topology_sweep_*` files, the older CAIDA
      and zoo files) will be refused once the warnings become errors.

- **Slower garbage collection (T-83, 8e3e9f7).** `src/Network.py` sets
  `gc.set_threshold(100_000, 50, 1000)` when it is imported (Python's
  default is `(700, 10, 10)`). Same output; on full CAIDA x 1000 about
  15% less run time (the collector took 17% of it, now 1%) for 0.2% more
  memory; about 9% less on the 1K subset. To get Python's defaults back,
  call `gc.set_threshold(700, 10, 10)` after importing `Network`.
- **Tree-children forwarding on by default (T-13, 8ca4c42).**
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
- **Option to announce entries freed by a withdrawal at once (T-12, 8ca4c42),
  off by default.** With `Router.announce_freed_after_withdraw = True`
  (`ANNOUNCE_FREED=1` in `main_precomputed_t1.py`), after a withdrawal a
  router announces the entries that only the withdrawn one was
  dominating; otherwise they wait for the next announcement to reach that
  router. Off, results are unchanged. On, it changes results: on the 1K
  CAIDA subset 7.9% more messages and about 12% more run time, accuracy
  61.8% vs 62.9% (one placement); on Topology Zoo DFN and Cogentco 0-4%
  more messages and accuracy mostly the same or slightly better. Left off
  for now; whether the paper runs use it is still to be decided (results
  on 5 placements and full CAIDA x 1000 in `doc/TODO.md` T-12).
  `main_precomputed_t1.py` now prints the setting in its parameter header.
- **Default link delays (T-17, 8ca4c42).** Core links given no delay now get 10 ms
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
  rounded down to the ms. Packet sizes are unchanged. `log_syntax.py` still reads older logs.
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

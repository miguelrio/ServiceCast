# How the 12 Matrix-Plot Metrics Are Counted — **Monkey-Patch Mode (legacy)**

> **This is the legacy collector.** The default build is now **pure-log mode**
> (`plot_change_factor_matrix.py` defaults to `--source log`): metrics are derived
> from the simulation's own log text — the `OUTCOME_GAP` / `DECISION_GAP` /
> `STALENESS_ERR` notation — see
> [`matrix_metrics_log_mode_explained.md`](matrix_metrics_log_mode_explained.md).
> The probe build described here is kept as the independent cross-check
> ([`validate_log_vs_probe.py`](validate_log_vs_probe.py)); both produce the same
> metrics from the same runs.

In this mode, all metrics shown in the change-factor matrix plots come from **one
place**: the simulation is instrumented by *monkey patching* three functions during
each run (plus one counter read off the routers afterwards). Nothing is read from
logs or files.

- **Where collection happens:** [`run_single_experiment`](run_simulation_sweep.py#L241) — runs one simulation, returns an `ExperimentResult`
- **Where the 3 wrappers live:** [`SimulationProbes`](run_simulation_sweep.py#L115) — installs all three together, restores them on exit
- **Where 4 metrics are derived:** [`summarise_records`](run_simulation_sweep.py#L99)
- **Where every cell is filled:** [`run_sweep`](run_simulation_sweep.py#L295-L308)
- **Where they are plotted:** [`plot_change_factor_matrix.py`](plot_change_factor_matrix.py)

Each plot cell `[k, i, j]` is one full 3600s simulation run for a single
`(propagation_delay, router_cf, server_cf)` triple. The sweep now spans **three
axes** — `Server.change_factor` (columns), `Router.fib_utility_update_threshold`
(rows), and `Graph.default_propagation_delay` (the faceted panels) — so each metric
is stored as a 3D array indexed `[delay][router_cf][server_cf]`.

---

## The 3 monkey-patched functions

Each patch saves the original method, wraps it to record a measurement, then
delegates to the original (so simulation behaviour is unchanged). They are bundled
in the [`SimulationProbes`](run_simulation_sweep.py#L115) context manager, installed
together via `ExitStack` and restored automatically after the run
([lines 154-156](run_simulation_sweep.py#L154-L156)):

```python
with SimulationProbes() as probes:        # run_single_experiment, L254
    network.start(until=SIM_DURATION)
# -> probes.created, probes.hops, probes.records
```

| Patch | Wrapper (file) | Type | Raw value collected |
|-------|----------------|------|---------------------|
| #1 | [`LinkEnd.put`](Link.py) → `counting_put` | counter | `probes.hops`, split by `packet.operation` into `hops_announce` (`A`) / `hops_withdraw` (`W`) |
| #2 | [`Server.send_load_packet`](Server.py#L310) → `counting_send_load_packet` | counter | `probes.created` |
| #3 | [`Network.best_replica_utility`](Network.py) → `recording_best_replica_utility` | recorder | `probes.records` = list of `(selected_sel, best_sel, selected_arr, best_arr)`; `probes.blocked` counts dropped requests |

A value `fib_updates` is **not** a patch: it is read straight off the routers
after the run (see metric 7).

> **Note on the probe signature.** `best_replica_utility` takes a 4th
> `status=None` argument; the simulator passes `{'msg':'BLOCKED'}` when a request
> reaches a full replica. The wrapper accepts and forwards it. Blocked requests
> increment `probes.blocked` and are **excluded** from `records`, so they do not
> skew the accuracy/error statistics (metrics 3–6, 9, 10).

---

## The 7 metrics

### 1. `created` — Unique Control Messages Created
- **Source:** Patch #2
- **How:** `+1` every time a server *originates* a new `ServerMetric` packet.
  `send_load_packet` is the single birthplace of a control message (it builds the
  `Packet` and bumps `pkt_no`), so call-count = messages that entered the network.
- **Counts origination, not propagation.**

### 2. `messages` — Control Message Hops Transmitted
- **Source:** Patch #1
- **How:** `+1` every time *any* `ServerMetric` packet crosses *any* link end.
- **Counts propagation:** one created message flooding across N hops adds 1 to
  `created` but N to `messages`.

### 3-6. Selection-time utility metrics — all derived from Patch #3

Patch #3 records one `(selected_sel, best_sel, selected_arr, best_arr)` tuple per
**served** client request — the selected and best replica utilities at *selection
time* (from the `optimal_snapshot`) and at *arrival time* (live state). In the
log's notation (Logging.md / `GAP_NOTATIONS`) these are exactly
`(SEL_UTIL_SEL, BEST_UTIL_SEL, SEL_UTIL_ARR, BEST_UTIL_ARR)` — ground truth at
`t_sel` (deciding router's vantage) and at `t_arr`, never the FIB estimate
`SEL_UTIL_EST`. Metrics 3–6 use the selection-time pair; the per-request error
`BEST_UTIL_SEL - SEL_UTIL_SEL` equals `A - C` (DECISION_GAP minus STALENESS_ERR).
After the run, [`summarise_records`](run_simulation_sweep.py#L101) computes the
errors once:

```python
errors  = [abs(best - sel) for sel, best, _, _ in records]
subopt  = [e for e in errors if e >= 1e-9]    # only "wrong" picks
correct = sum(1 for e in errors if e < 1e-9)
```

| # | Metric | Formula | Meaning (log notation) |
|---|--------|---------|------------------------|
| 3 | `accuracy`    | `correct / total * 100` | % of requests with `SEL_ID = BEST_ID_SEL` at `t_sel` (within 1e-9) |
| 4 | `mean_all`    | `mean(errors)`          | Mean `\|BEST_UTIL_SEL - SEL_UTIL_SEL\|` over **all** requests |
| 5 | `mean_subopt` | `mean(subopt)`          | Mean `\|BEST_UTIL_SEL - SEL_UTIL_SEL\|` over **suboptimal** requests only |
| 6 | `max_error`   | `max(errors)`           | Max `\|BEST_UTIL_SEL - SEL_UTIL_SEL\|` (worst single request) |

(An empty `records` list yields `accuracy = 100%` and zero error, the same
convention as before. `total` here is *served* requests — blocked ones are
already excluded, so this matches `quick_stats`' `(equal+same)/(total−blocked)`.)

### 7. `fib_updates` — SERVICE_FIB Updates (Routing Churn)
- **Source:** each router's own `service_fib_updates` counter, summed after the run
  ([L257](run_simulation_sweep.py#L257)):
  ```python
  fib_updates = sum(getattr(r, 'service_fib_updates', 0) for r in network.routers.values())
  ```
- **How:** every time a router commits a genuine change to its SERVICE_FIB it bumps
  this counter; summing across all routers gives total routing churn for the run.
- **Not a monkey patch** — it reads state the routers already maintain.

### 8. `blocked_rate` — Blocked Request Rate (%)
- **Source:** Patch #3 (`probes.blocked`)
- **How:** a request that reaches a replica with no free capacity
  (`Server.can_increase_load` is false) is dropped, and `best_replica_utility` is
  called with `status={'msg':'BLOCKED'}`. The wrapper counts these and skips the
  record. `blocked_rate = blocked / (blocked + served) * 100`.
- Surfaces where the routing policy keeps steering load onto saturated servers —
  previously invisible (and silently folded into accuracy).

### 9-10. Arrival-time (outcome) metrics — derived from Patch #3

Same records, using the *arrival-time* pair `(selected_arr, best_arr)` =
`(SEL_UTIL_ARR, BEST_UTIL_ARR)` — the selected and best replica utilities
recomputed from **live** state when the packet arrives, rather than from the
selection-time snapshot. The per-request error is exactly the log's
`OUTCOME_GAP` line: `B = BEST_UTIL_ARR - SEL_UTIL_ARR`, both at `t_arr`.

```python
arrival_errors = [abs(best - sel) for _, _, sel, best in records]   # |B|
```

| # | Metric | Formula | Meaning (log notation) |
|---|--------|---------|------------------------|
| 9  | `accuracy_arrival` | `correct_arrival / total * 100` | % of requests with `OUTCOME_GAP (B) = 0` at `t_arr` (within 1e-9) |
| 10 | `mean_arrival`     | `mean(arrival_errors)`          | Mean `\|OUTCOME_GAP\|` = mean `\|BEST_UTIL_ARR - SEL_UTIL_ARR\|` |

These measure **decision staleness**: how much the picture decayed in the time
between the routing decision and arrival. They should grow along the
propagation-delay facet axis while the selection-time metrics stay flat.

### 11-12. `hops_announce` / `hops_withdraw` — Control Traffic by Type
- **Source:** Patch #1, split by `packet.operation`
  ([`ServerMetricMessageType`](Server.py#L23): `A` announce / `W` withdraw).
- **How:** every `ServerMetric` hop adds 1 to `hops`, and additionally to
  `hops_announce` or `hops_withdraw`. Announcements originate at servers
  ([Server.py:316](Server.py#L316)); withdrawals are generated router-side
  ([Router.py:910](Router.py#L910)).
- Breaks the total hop traffic into genuine load announcements vs. churn-driven
  withdrawals (`hops_announce + hops_withdraw == hops`).

---

## Summary

| Metric             | Source | Method |
|--------------------|--------|--------|
| `created`          | Patch #2 | `+1` counter |
| `messages`         | Patch #1 | `+1` counter |
| `accuracy`         | Patch #3 | derived from records (selection time) |
| `mean_all`         | Patch #3 | derived from records (selection time) |
| `mean_subopt`      | Patch #3 | derived from records (selection time) |
| `max_error`        | Patch #3 | derived from records (selection time) |
| `fib_updates`      | router counter | summed after the run |
| `blocked_rate`     | Patch #3 | `probes.blocked` / served+blocked |
| `accuracy_arrival` | Patch #3 | derived from records (arrival time) |
| `mean_arrival`     | Patch #3 | derived from records (arrival time) |
| `hops_announce`    | Patch #1 | `+1` counter, `operation == 'A'` |
| `hops_withdraw`    | Patch #1 | `+1` counter, `operation == 'W'` |

**Key points:**
- 11 of the 12 metrics trace back to just **3 monkey patches** (bundled in
  `SimulationProbes`); `fib_updates` is read off the routers post-run.
- Patch #1 now yields three counters (`messages`, `hops_announce`,
  `hops_withdraw`); Patch #2 yields one (`created`).
- **7 share Patch #3**: per-request utility records drive the selection-time and
  arrival-time accuracy/error metrics, and the blocked-request counter; all are
  computed arithmetically in `summarise_records`, not counted live. Blocked
  requests are excluded from the records.
- The metric set is named in exactly one place — `METRIC_FIELDS`
  ([L60](run_simulation_sweep.py#L60)) — which drives both the per-cell
  accumulation and the JSON `matrix_<field>` keys.
- Every metric is a 3D array over `(delay, router_cf, server_cf)`; see the
  faceted plots for the delay axis.

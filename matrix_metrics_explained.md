# How the 6 Matrix-Plot Metrics Are Counted

All metrics shown in the change-factor matrix plots come from **one place**: the
simulation is instrumented by *monkey patching* three functions during each run.
Nothing is read from logs or files.

- **Where collection happens:** [`run_single_experiment`](run_simulation_sweep.py#L58)
- **Where 4 metrics are derived:** [`run_sweep`](run_simulation_sweep.py#L207-L222)
- **Where they are plotted:** [`plot_change_factor_matrix.py`](plot_change_factor_matrix.py)

Each plot cell `[i, j]` is one full 3600s simulation run for a single
`(router_cf, server_cf)` pair.

---

## The 3 monkey-patched functions

Each patch saves the original method, wraps it to record a measurement, then
delegates to the original (so simulation behaviour is unchanged). All three are
installed together and restored after the run
([lines 166-169](run_simulation_sweep.py#L166-L169)).

| Patch | Function (file) | Type | Raw value collected |
|-------|-----------------|------|---------------------|
| #1 | [`LinkEnd.put`](Link.py) (Link.py) | counter | `server_metric_count` |
| #2 | [`Server.send_load_packet`](Server.py#L299) (Server.py) | counter | `unique_metric_created` |
| #3 | [`Network.best_replica_utility`](Network.py) (Network.py) | recorder | `utility_records` = list of `(selected_utility, best_utility)` |

---

## The 6 metrics

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

### 3-6. Utility metrics — all derived from Patch #3

Patch #3 records one `(selected_utility, best_utility)` tuple per client request.
After the run, errors are computed once and reused for four metrics
([`run_sweep`](run_simulation_sweep.py#L207-L222)):

```python
errors        = [abs(best - sel) for sel, best in records]
subopt_errors = [err for err in errors if err >= 1e-9]   # only "wrong" picks
```

| # | Metric | Formula | Meaning |
|---|--------|---------|---------|
| 3 | `accuracy`    | `correct / total * 100`, where `correct = count(err < 1e-9)` | % of requests routed to the optimal replica |
| 4 | `mean_all`    | `mean(errors)`        | Avg utility error over **all** requests |
| 5 | `mean_subopt` | `mean(subopt_errors)` | Avg utility error over **suboptimal** requests only |
| 6 | `max_error`   | `max(errors)`         | Worst single-request utility error |

---

## Summary

| Metric        | Patch | Method |
|---------------|-------|--------|
| `created`     | #2 | `+1` counter |
| `messages`    | #1 | `+1` counter |
| `accuracy`    | #3 | derived from records |
| `mean_all`    | #3 | derived from records |
| `mean_subopt` | #3 | derived from records |
| `max_error`   | #3 | derived from records |

**Key points:**
- All 6 metrics trace back to just **3 monkey patches**.
- Only **2** are simple `+= 1` counters (`created`, `messages`).
- The other **4 share a single patch** that records per-request utility data;
  they are computed arithmetically afterward, not counted live.

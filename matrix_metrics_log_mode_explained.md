# How the Matrix Metrics Are Collected in **Pure-Log Mode** (the default)

There are two ways to build the change-factor matrix:

| Mode | How it reads metrics | Code |
|------|----------------------|------|
| **Pure-log** (default, this doc) | Runs the simulation with logging **on**, then derives every metric from the **log text** only — the same three gap lines per request the log notation defines. Touches nothing inside the simulation. | [`run_simulation_sweep_log.py`](run_simulation_sweep_log.py) |
| **Monkey-patch** (legacy) | Wraps 3 simulation functions and reads in-memory state. Silent (`Verbose.level=-1`). Kept as the independent cross-check. | [`run_simulation_sweep.py`](run_simulation_sweep.py) — see [`matrix_metrics_explained.md`](matrix_metrics_explained.md) |

Both run the *identical* simulation (same topology, seed, parameters) and produce the
same JSON shape, so the heatmaps are directly comparable. The only difference is
**where the numbers come from** — which is exactly what
[`validate_log_vs_probe.py`](validate_log_vs_probe.py) checks.

---

## The idea in one picture

```
for each grid cell (server_cf, router_cf, delay):
    1. run the simulation with Verbose.level = 1   (logging ON)
    2. capture its printed log into a temp .log file
    3. parse the log text  -> counts + per-request records
    4. delete the .log file
    5. reduce records -> the same metrics the monkey-patch build produces
```

- Nothing in the simulation or any log line is changed — the collector is a pure **reader**.
- `Verbose.level = 1` is the lowest level that prints every line we need (the FIB line
  and the `DECISION_GAP` / `STALENESS_ERR` lines all need `>=1`).
- By default each cell's `.log` is written, parsed, then **deleted** (`--log-mode file`), so disk
  stays bounded. `--log-mode stream` keeps it in memory instead.

---

## Which log line feeds which metric

All parsing lives in one file, [`log_metrics.py`](log_metrics.py). Each log line is matched by a
cheap keyword check, then a regex.

Per served request the simulation prints up to **three gap lines** (see
`GAP_NOTATIONS` in [Network.py](Network.py) and [Logging.md](Logging.md)), all in
one shared shape, at the same timestamp, keyed by `[client.pkt]`:

| Line | Level | SELECTED utility | compared utility | keyword compares |
|------|-------|------------------|------------------|------------------|
| `OUTCOME_GAP` (B)   | >=0 | `SEL_UTIL_ARR` | `BEST` = `BEST_UTIL_ARR` | the arrival pair itself |
| `DECISION_GAP` (A)  | >=1 | `SEL_UTIL_EST` | `BEST` = `BEST_UTIL_SEL` | estimate vs best-at-sel |
| `STALENESS_ERR` (C) | >=1 | `SEL_UTIL_EST` | `ACTUAL` = `SEL_UTIL_SEL` | estimate vs truth-at-sel |

| Metric | Log line(s) it reads | Meaning (log notation) |
|--------|----------------------|------------------------|
| `created` | `PACKET_CREATED … ServerMetric` ([Server.py:331](Server.py#L331)) | how many load updates servers originated |
| `accuracy` | `DECISION_GAP` + `STALENESS_ERR` compared sections | % of requests with `SEL_ID = BEST_ID_SEL` at `t_sel` |
| `mean_err_all` / `mean_err_subopt` / `max_err` | same two lines | mean/max `\|BEST_UTIL_SEL - SEL_UTIL_SEL\|` |
| `blocked_rate` | `OUTCOME_GAP … BLOCKED` | % of requests dropped at a full replica |
| `accuracy_arrival` / `mean_err_arrival` | `OUTCOME_GAP` (B) | share of `B = 0` / mean `\|B\|`, judged at `t_arr` |
| `fib_updates` | `SERVICE_FIB update_count: N` ([Router.py](Router.py)) | routing-table churn (last `N` per router, summed) |
| `recv_total` | every `RECV_PACKET ServerMetric` ([Router.py](Router.py)) | control packets **received** by routers |
| `recv_announce` / `recv_withdraw` | `RECV_PACKET ServerMetric A` / `… W` | received announcements / withdrawals |

The shared line reader is `parse_gap_line` in [`log_metrics.py`](log_metrics.py) —
the gap-line shape is parsed in exactly one place. (The old one-line
`BEST_REPLICA_UTILITY` reader `parse_best_replica_line` is gone with the old
format; `log_to_csv.py` / `plot_log.py` still expect it and fail loudly until
they are migrated.)

---

## How the per-request records are assembled

The parser groups a request's gap lines by `[client.pkt]` and reads the probe's
4-tuple `(selected_sel, best_sel, selected_arr, best_arr)` **directly** — each
element is one section of one line, always ground truth, never the FIB estimate:

```
selected_sel = STALENESS_ERR.ACTUAL.utility   (SEL_UTIL_SEL)
best_sel     = DECISION_GAP.BEST.utility      (BEST_UTIL_SEL)
selected_arr = OUTCOME_GAP.SELECTED.utility   (SEL_UTIL_ARR)
best_arr     = OUTCOME_GAP.BEST.utility       (BEST_UTIL_ARR)
```

The keywords keep accuracy exact despite the 5-dp rounding of printed utilities:

- `OUTCOME_GAP … SAME/EQUAL` → the model's own unrounded `<1e-9` verdict on exactly
  the arrival pair → forced equal.
- `DECISION_GAP … SAME` → `SEL_ID = BEST_ID_SEL`, so the selection pair is exactly
  equal. (Its `EQUAL` is estimate-based and deliberately ignored;
  `STALENESS_ERR`'s keyword is always `SAME` by construction and never consulted.)
- `OUTCOME_GAP … BLOCKED` → request dropped at a full replica → counted
  separately; its whole line trio is excluded from the records.
- A request with only an `OUTCOME_GAP` line (no FIB decision recorded) falls back
  to the arrival pair for its selection pair, mirroring the probe.

The records then feed the **shared** `summarise_records`
([run_simulation_sweep.py](run_simulation_sweep.py)), so the accuracy/error math
is defined in one place for both modes.

> **Precision note:** the log rounds utilities to 5 decimals, so `mean/max` errors match
> the monkey-patch build to ~1e-5. Counts (`created`, `accuracy`, `blocked_rate`, `fib_updates`)
> match **exactly**.

---

## Two honesty notes

**1. `recv_*` ≠ "hops".** The monkey-patch build counts control traffic at the moment a packet is
*sent* onto a link (`LinkEnd.put`). The log has **no line at send time** — only `RECV_PACKET` when a
router *receives* one. So the log build names these `recv_total` / `recv_announce` /
`recv_withdraw` — what the log actually measures (receptions), not transmissions. In practice they
match the send-based count almost exactly (identical at small propagation delay; off by ~0.1% at
`delay=4.0`, due to packets still in flight when the run ends).

**2. Selection vs arrival metrics differ in both routing modes.** The deciding router
(`record_forwarding_decision`) snapshots ground truth at `t_sel` — the **first** router under
first-decide, the **last** under hop-by-hop — so the selection-time metrics (from the
`DECISION_GAP` / `STALENESS_ERR` lines) and the arrival-time metrics (from `OUTCOME_GAP`) are
genuinely different evaluations. They converge only as the propagation delay approaches zero.

---

## How to run it

Log mode is the default — no `--source` flag needed:

```bash
# Full log-based sweep + heatmaps, parallelised (0 = auto, cores-2):
python plot_change_factor_matrix.py --jobs 0

# Just the data (no plots):
python run_simulation_sweep_log.py --jobs 0

# Legacy monkey-patch build (cross-check only):
python plot_change_factor_matrix.py --source probe
```

- `--jobs N`: one worker per CPU core (each cell is an independent, ~1-core simulation). Use `0`
  for auto. More than your core count gives nothing.
- The output JSON is tagged `"source": "log"`, and every plot's **title and filename** say
  `Collected: Pure Log` vs `Monkey-Patch (legacy)`, so the two builds never get mixed up.

## How we know it's correct

[`validate_log_vs_probe.py`](validate_log_vs_probe.py) runs both builds on the same cells and checks
them: counts must match exactly, errors within `1e-5`, and it reports the `recv_*` vs send-based
difference. Run it any time:

```bash
python validate_log_vs_probe.py            # small smoke grid
```

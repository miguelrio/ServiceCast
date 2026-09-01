#!/usr/bin/env python3
"""Pure log parser for the change-factor matrix metrics.

This module is the single source of truth for reading the simulation's *log text*
(the same `print()` output `main_dfn.py` produces). It is a pure consumer: it never
touches model state and never changes a log line. Two entry points:

- `parse_gap_line(line)` -> `GapLine | None`
  Extracts every field of one per-request metric line (OUTCOME_GAP / DECISION_GAP /
  STALENESS_ERR, all printed by Network._log_request_gap in one shared shape).

- `parse_log_lines(lines)` -> `LogMetrics`
  Single streaming pass over an iterable of lines (an open file *or* a captured
  stdout stream). Assembles the up-to-three gap lines of each request into one
  record shaped exactly like the in-memory probe's, so it feeds
  `run_simulation_sweep.summarise_records` unchanged.

Which log lines feed which metric (all emitted at `Verbose.level >= 1`):
  created                      <- `PACKET_CREATED ... ServerMetric`   (Server.py)
  recv_total/announce/withdraw <- `RECV_PACKET ServerMetric A|W`      (Router.py)  [receptions, not transmissions]
  fib_updates                  <- `SERVICE_FIB update_count: N`       (Router.py)  [last N per router, summed]
  records, blocked             <- the three per-request gap lines     (Network.py)

The per-request lines (see GAP_NOTATIONS in Network.py). One request
`[client.pkt]` prints, in order, at the same timestamp:

  tag           lvl  SELECTED utility  compared utility        keyword compares
  OUTCOME_GAP   >=0  SEL_UTIL_ARR      BEST   = BEST_UTIL_ARR  the arrival pair itself
  DECISION_GAP  >=1  SEL_UTIL_EST      BEST   = BEST_UTIL_SEL  estimate vs best-at-sel
  STALENESS_ERR >=1  SEL_UTIL_EST      ACTUAL = SEL_UTIL_SEL   estimate vs truth-at-sel

The probe's 4-tuple (selected_sel, best_sel, selected_arr, best_arr) is ground
truth, never the FIB estimate, and each element appears directly in one section:

  selected_sel = STALENESS_ERR.ACTUAL.utility   (SEL_UTIL_SEL)
  best_sel     = DECISION_GAP.BEST.utility      (BEST_UTIL_SEL)
  selected_arr = OUTCOME_GAP.SELECTED.utility   (SEL_UTIL_ARR)
  best_arr     = OUTCOME_GAP.BEST.utility       (BEST_UTIL_ARR)

Keyword semantics (computed unrounded in the model, epsilon 1e-9):
  - OUTCOME_GAP's keyword compares exactly the arrival pair, so SAME/EQUAL there
    means "correct within 1e-9" and we force the pair equal -> arrival accuracy is
    exact despite the 5 dp rounding of printed utilities.
  - DECISION_GAP's SAME means SEL_ID == BEST_ID_SEL, hence BEST_UTIL_SEL ==
    SEL_UTIL_SEL exactly -> force the selection pair equal. Its EQUAL is about the
    *estimate* and implies nothing about the selection pair: ignored.
  - STALENESS_ERR's keyword is always SAME by construction (both sections carry
    SEL_ID): never consulted.
  - BLOCKED (or any future status word) appears only on the OUTCOME_GAP line; the
    request still prints DECISION_GAP/STALENESS_ERR lines, all of which must be
    excluded from `records` and counted in `blocked`.

A request whose packet never got a FIB decision has only the OUTCOME_GAP line; like
the probe's fallback, its selection pair is then taken from the arrival pair.
"""

import warnings
from typing import Iterable, NamedTuple

from log_syntax import (
    GapLine,
    parse_event_header,
    parse_fib_update_count,
    parse_gap_line,
    parse_log_header,
    parse_server_metric_event,
)

# Keywords meaning "the request was served" (anything else is a status like BLOCKED).
_SERVED_KEYWORDS = frozenset({"SAME", "EQUAL", "DIFFERENT"})


# --- Assembling one request from its gap lines ----------------------------------

_warned = set()   # one warning per kind per process; drift is loud but not spammy


def _warn_once(kind, detail):
    if kind not in _warned:
        _warned.add(kind)
        warnings.warn(f"log_metrics: {kind} ({detail}); further occurrences suppressed")


def _finish_request(parts):
    """Reduce the collected gap lines of one request to a probe record.

    Returns "blocked", a (selected_sel, best_sel, selected_arr, best_arr) tuple,
    or None when the lines are unusable. `parts` maps tag -> GapLine.
    """
    b = parts.get("OUTCOME_GAP")
    if b is None:
        _warn_once("request without OUTCOME_GAP line",
                   f"tags={sorted(parts)} pkt={next(iter(parts.values())).client}.{next(iter(parts.values())).pkt}")
        return None
    if b.keyword not in _SERVED_KEYWORDS:
        return "blocked"    # BLOCKED today; treat any future status word the same way

    # Arrival pair, straight off the B line. SAME/EQUAL is the model's own unrounded
    # <1e-9 verdict on exactly this pair: force equality so accuracy stays exact.
    selected_arr = b.sel_utility                                    # SEL_UTIL_ARR
    best_arr = selected_arr if b.keyword in ("SAME", "EQUAL") else b.cmp_utility  # BEST_UTIL_ARR

    a = parts.get("DECISION_GAP")
    c = parts.get("STALENESS_ERR")
    if a is None or c is None:
        if a is not None or c is not None:
            _warn_once("request with only one of DECISION_GAP/STALENESS_ERR",
                       f"pkt={b.client}.{b.pkt}")
        # No FIB decision recorded (or Verbose 0 log): the probe's fallback is to
        # read the selection pair from the same live state as the arrival pair.
        return (selected_arr, best_arr, selected_arr, best_arr)

    # Producer drift tripwires: A and C carry the same estimate
    # section, and C's ACTUAL server is the arrival server (SEL_ID == arrival).
    if (a.sel_server, a.sel_utility) != (c.sel_server, c.sel_utility):
        _warn_once("DECISION_GAP/STALENESS_ERR estimate sections differ", f"pkt={b.client}.{b.pkt}")
    if c.cmp_server != b.sel_server:
        _warn_once("STALENESS_ERR ACTUAL server != arrival server", f"pkt={b.client}.{b.pkt}")
    if not (a.ts == b.ts == c.ts):
        _warn_once("gap lines of one request differ in timestamp", f"pkt={b.client}.{b.pkt}")

    # Selection pair: ground truth at t_sel. A's SAME means the selected replica IS
    # the best at t_sel, so the pair is exactly equal; its EQUAL is estimate-based
    # and deliberately ignored.
    selected_sel = c.cmp_utility                                    # SEL_UTIL_SEL
    best_sel = selected_sel if a.keyword == "SAME" else a.cmp_utility  # BEST_UTIL_SEL

    return (selected_sel, best_sel, selected_arr, best_arr)


class LogMetrics(NamedTuple):
    """Raw measurements read from one run's log, mirroring the probe's ExperimentResult."""
    created: int            # ServerMetric originations (PACKET_CREATED)
    recv_total: int         # ServerMetric receptions (RECV_PACKET) - NOT LinkEnd.put transmissions
    recv_announce: int      # RECV_PACKET ServerMetric A
    recv_withdraw: int      # RECV_PACKET ServerMetric W
    fib_updates: int        # sum of last SERVICE_FIB update_count per router
    blocked: int            # BLOCKED client requests (excluded from records)
    records: list           # (selected_sel, best_sel, selected_arr, best_arr) per served request
    per_server_served: dict # server_id -> count of served requests (from OUTCOME_GAP.sel_server)


def parse_log_lines(lines: Iterable[str]) -> LogMetrics:
    """Single streaming pass over `lines`; returns the raw metrics for one run.

    Gap lines are grouped by [client.pkt] and a request is finalized as soon as its
    STALENESS_ERR line (always printed last) arrives, so memory stays bounded by the
    handful of in-flight requests, not the log length.
    """
    created = 0
    recv_total = 0
    recv_announce = 0
    recv_withdraw = 0
    blocked = 0
    fib_last = {}          # router id -> last update_count seen
    records = []
    per_server_served = {} # server_id -> count of served requests
    pending = {}           # (client, pkt) -> {tag: GapLine}, insertion-ordered

    def finalize(parts):
        nonlocal blocked
        outcome = _finish_request(parts)
        if outcome == "blocked":
            blocked += 1
        elif outcome is not None:
            records.append(outcome)
            # track which server handled this served request
            b = parts.get("OUTCOME_GAP")
            if b is not None and b.sel_server:
                per_server_served[b.sel_server] = per_server_served.get(b.sel_server, 0) + 1

    _, event_lines = parse_log_header(lines)
    for line in event_lines:
        header = parse_event_header(line)
        if header is None:
            continue
        if header.keyword in {"PACKET_CREATED", "RECV_PACKET"}:
            event = parse_server_metric_event(line, header)
            if event is not None:
                if event.kind == "created":
                    created += 1
                else:
                    recv_total += 1
                    if event.operation == "A":
                        recv_announce += 1
                    elif event.operation == "W":
                        recv_withdraw += 1
            continue
        if header.keyword == "SERVICE_FIB":
            update = parse_fib_update_count(line, header)
            if update is not None:
                fib_last[update.router] = update.count
            continue
        gl = parse_gap_line(line, header)
        if gl is None:
            continue
        key = (gl.client, gl.pkt)
        parts = pending.setdefault(key, {})
        if gl.tag in parts:    # duplicate tag: a new request reusing the key; close the old one
            _warn_once("duplicate gap line for one request key", f"pkt={gl.client}.{gl.pkt} tag={gl.tag}")
            finalize(pending.pop(key))
            parts = pending.setdefault(key, {})
        parts[gl.tag] = gl
        if gl.tag == "STALENESS_ERR":       # last line of the trio: finalize eagerly
            finalize(pending.pop(key))

    for parts in pending.values():          # OUTCOME_GAP-only requests (no FIB decision)
        finalize(parts)

    return LogMetrics(
        created=created, recv_total=recv_total, recv_announce=recv_announce,
        recv_withdraw=recv_withdraw, fib_updates=sum(fib_last.values()),
        blocked=blocked, records=records, per_server_served=per_server_served,
    )


def parse_log_file(path) -> LogMetrics:
    """Convenience wrapper: stream a log file from disk (bounded memory)."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return parse_log_lines(fh)

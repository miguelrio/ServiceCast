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

The per-request lines (see Logging.md and GAP_NOTATIONS in Network.py). One request
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

import re
import warnings
from typing import Iterable, NamedTuple


# --- The shared gap-line shape --------------------------------------------------
# Mirrors Network._log_request_gap / _gap_section:
#   "{ts}: Net   {TAG}[ (formula)] '{arrival_server}' [{client}.{pkt}]
#    SELECTED: time[(note)]: T server[(note)]: S load: L latency: LAT utility[(note)]: U
#    {BEST|ACTUAL}: time[(note)]: T server[(note)]: S load: L latency: LAT utility[(note)]: U
#    [MINLOAD: time[(note)]: T server[(note)]: S load: L latency: LAT utility[(note)]: U]
#    {KEYWORD} {gap}"
# The MINLOAD section (lowest-loaded replica at t_arr) appears only on BLOCKED
# OUTCOME_GAP lines; old logs simply don't have it.
# The (note) annotations are the PDF notation, printed only at Verbose >= 1; every
# annotation is optional here so both verbosity levels parse. load is printed via
# str() and utility/gap via round(,5), so numbers may use scientific notation.
_NUM = r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?"
_NOTE = r"(?:\([^)]*\))?"


def _side(prefix, label_pattern):
    """Regex fragment for one `LABEL: time: .. server: .. load: .. latency: .. utility: ..` section."""
    return (rf"(?P<{prefix}_label>{label_pattern}):\s+"
            rf"time{_NOTE}:\s+(?P<{prefix}_t>{_NUM})\s+"
            rf"server{_NOTE}:\s+(?P<{prefix}_s>\S+)\s+"
            rf"load:\s+(?P<{prefix}_load>{_NUM})\s+"
            rf"latency:\s+(?P<{prefix}_lat>{_NUM})\s+"
            rf"utility{_NOTE}:\s+(?P<{prefix}_u>{_NUM})")


GAP_LINE_RE = re.compile(
    rf"(?P<ts>{_NUM}):\s+\S+\s+"
    rf"(?P<tag>OUTCOME_GAP|DECISION_GAP|STALENESS_ERR)(?:\s+\([^)]*\))?\s+"
    rf"'(?P<arrival>[^']+)'\s+\[(?P<client>[^.\]]+)\.(?P<pkt>\d+)\]\s+"
    + _side("sel", "SELECTED") + r"\s+"
    + _side("cmp", "BEST|ACTUAL") + r"\s+"
    + rf"(?:{_side('min', 'MINLOAD')}\s+)?"
    + rf"(?P<keyword>\S+)\s+(?P<gap>{_NUM})\s*$"
)

# Lighter patterns for the counter lines (substring-prefiltered before use).
RECV_SERVER_METRIC_RE = re.compile(r"RECV_PACKET\s+ServerMetric\s+(?P<op>\S+)")
FIB_UPDATE_RE = re.compile(rf"(?P<ts>{_NUM}):\s+(?P<rid>\S+)\s+SERVICE_FIB\s+update_count:\s+(?P<count>\d+)")

# Keywords meaning "the request was served" (anything else is a status like BLOCKED).
_SERVED_KEYWORDS = frozenset({"SAME", "EQUAL", "DIFFERENT"})


class GapLine(NamedTuple):
    """Every field of one OUTCOME_GAP / DECISION_GAP / STALENESS_ERR line."""
    ts: float
    tag: str                # OUTCOME_GAP | DECISION_GAP | STALENESS_ERR
    arrival: str            # server the request arrived at
    client: str
    pkt: int
    sel_time: float         # SELECTED section (SEL_UTIL_ARR on B, SEL_UTIL_EST on A/C)
    sel_server: str
    sel_load: float
    sel_latency: float
    sel_utility: float
    cmp_label: str          # BEST (B, A) | ACTUAL (C)
    cmp_time: float         # compared section (BEST_UTIL_ARR / BEST_UTIL_SEL / SEL_UTIL_SEL)
    cmp_server: str
    cmp_load: float
    cmp_latency: float
    cmp_utility: float
    keyword: str            # SAME | EQUAL | DIFFERENT | BLOCKED (B only) | future status words
    gap: float              # signed, compared - selected, rounded to 5 dp


def parse_gap_line(line):
    """Parse one per-request metric line into a GapLine, or None."""
    if "_GAP" not in line and "STALENESS_ERR" not in line:
        return None
    m = GAP_LINE_RE.search(line)
    if not m:
        return None
    g = m.group
    return GapLine(
        ts=float(g("ts")), tag=g("tag"), arrival=g("arrival"),
        client=g("client"), pkt=int(g("pkt")),
        sel_time=float(g("sel_t")), sel_server=g("sel_s"), sel_load=float(g("sel_load")),
        sel_latency=float(g("sel_lat")), sel_utility=float(g("sel_u")),
        cmp_label=g("cmp_label"),
        cmp_time=float(g("cmp_t")), cmp_server=g("cmp_s"), cmp_load=float(g("cmp_load")),
        cmp_latency=float(g("cmp_lat")), cmp_utility=float(g("cmp_u")),
        keyword=g("keyword"), gap=float(g("gap")),
    )


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

    # Producer drift tripwires (see plan §4): A and C carry the same estimate
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
    pending = {}           # (client, pkt) -> {tag: GapLine}, insertion-ordered

    def finalize(parts):
        nonlocal blocked
        outcome = _finish_request(parts)
        if outcome == "blocked":
            blocked += 1
        elif outcome is not None:
            records.append(outcome)

    for line in lines:
        if "PACKET_CREATED" in line:
            if "ServerMetric" in line:
                created += 1
            continue
        if "RECV_PACKET" in line:
            if "ServerMetric" in line:
                m = RECV_SERVER_METRIC_RE.search(line)
                if m:
                    recv_total += 1
                    op = m.group("op")
                    if op == "A":
                        recv_announce += 1
                    elif op == "W":
                        recv_withdraw += 1
            continue
        if "SERVICE_FIB" in line and "update_count" in line:
            m = FIB_UPDATE_RE.search(line)
            if m:
                fib_last[m.group("rid")] = int(m.group("count"))
            continue
        gl = parse_gap_line(line)
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
        blocked=blocked, records=records,
    )


def parse_log_file(path) -> LogMetrics:
    """Convenience wrapper: stream a log file from disk (bounded memory)."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return parse_log_lines(fh)

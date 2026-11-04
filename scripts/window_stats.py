#!/usr/bin/env python3
"""Request accuracy and server load per window of simulated time.

Reads the per-request lines (OUTCOME_GAP, DECISION_GAP, STALENESS_ERR,
REQUEST_NOT_FORWARDED) that logs carry at verbose -1 and up, and prints
one row per window: requests, blocking, accuracy, the mean gaps and an
estimate of server load. Use it to see when a run reaches steady state
and to report results for the steady-state part only. Works on runs
still in progress and on memprobe logs.

Usage:
    python3 window_stats.py [--from MS] [--to MS] [--every MS] <log> [<log> ...]

    --from, --to   window in simulated milliseconds (default: the whole run)
    --every        split the window into rows of this many milliseconds

Examples:
    python3 window_stats.py --every 25000 run.log       # how things vary
    python3 window_stats.py --from 300000 run.log       # steady state only

Requests are counted in the window of their arrival time. Accuracy and
the gaps use the same definitions as quick_stats.py, so a window covering
the whole run gives the same values.

Server load is estimated from the loads the gap lines record. Every
OUTCOME_GAP line gives the true load of the selected server and of the
best server at the request's arrival (the selected server's load before
the request is added). Each server's load is held at its last reading
(plus one slot when the request was accepted) until the next one. Load
only rises when a request is accepted, and every accepted request gives
a reading, so between readings the true load can only fall: the
estimate is an upper bound, short by the departures since each server's
last reading. A server with no reading yet is at 0. The update counts
and FIB changes are only in the end-of-run summary, so they cannot be
split by time; quick_stats.py reports them for the whole run.
"""

import argparse
import bisect
import math
import re
import sys

import numpy as np

from log_syntax import (
    SUMMARY_KEYWORDS,
    parse_event_header,
    parse_gap_line,
    parse_log_header,
    parse_not_forwarded_event,
)
from quick_stats import _consume_gap

_SERVERS_RE = re.compile(r"\((\d+) servers")
_RUN_DONE_RE = re.compile(r"^run: ")


def _new_window_stats():
    return {
        "total": 0, "equal": 0, "same": 0, "blocked": 0, "not_forwarded": 0,
        "blocked_unavoidable": 0, "blocked_avoidable": 0, "different": 0,
        "diffs": [], "different_diffs": [],
        "decision_gap_values": [], "staleness_err_values": [],
    }


def _server_count(path):
    """The server count from the start-up line ("... (1000 servers, ...)"),
    which comes before the end of the parameter header."""
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            match = _SERVERS_RE.search(line)
            if match:
                return int(match.group(1))
            if "RUN ---" in line:
                return None
    return None


def read_log(path, time_unit=None):
    """Parse one log: the run settings, the per-request lines by arrival
    time, and each server's load readings. Returned times are ms. Current logs
    already carry ms timestamps; explicitly seconds-unit old logs are converted
    to ms, and ms is assumed when older headers do not specify a unit."""
    n_servers = _server_count(path)
    with open(path, "r", encoding="utf-8") as fh:
        parameters, lines = parse_log_header(fh, path, warn=True)
        parameters = parameters or {}
        unit = time_unit or parameters.get("time_unit") or "ms"
        scale = 1000.0 if unit == "s" else 1.0

        requests = []      # (arrival ms, kind, parsed line)
        readings = {}      # server -> [(t ms, load after t)]
        finished = False
        summary_t = None   # the end-of-run SUMMARY_ lines carry the end time
        last_t = 0.0
        slot = 1.0 / parameters.get("Server.slots", 1)

        for line in lines:
            header = parse_event_header(line)
            if header is None:
                if _RUN_DONE_RE.match(line):
                    finished = True
                continue
            t = header.timestamp * scale
            last_t = max(last_t, t)
            if header.keyword in SUMMARY_KEYWORDS:
                finished = True
                summary_t = t
                continue

            if parse_not_forwarded_event(line, header) is not None:
                requests.append((t, "nofwd", None))
                continue
            gap = parse_gap_line(line, header)
            if gap is None:
                continue
            requests.append((t, gap.tag, gap))
            if gap.tag != "OUTCOME_GAP":
                continue

            accepted = gap.keyword != "BLOCKED"
            readings.setdefault(gap.sel_server, []).append(
                (gap.sel_time * scale, gap.sel_load + (slot if accepted else 0.0)))
            if gap.cmp_server != gap.sel_server:
                readings.setdefault(gap.cmp_server, []).append(
                    (gap.cmp_time * scale, gap.cmp_load))
            if gap.minload is not None and gap.minload[1] != gap.sel_server:
                readings.setdefault(gap.minload[1], []).append(
                    (gap.minload[0] * scale, gap.minload[2]))

    until = parameters.get("until")
    if until is not None:
        until *= scale
    if summary_t is not None:
        end = summary_t
    elif finished and until is not None:
        end = until
    else:
        end = last_t
    if n_servers is None:
        n_servers = len(readings)
        print(f"Warning: {path}: server count not in the log; using the "
              f"{n_servers} servers seen in the gap lines", file=sys.stderr)
    return requests, readings, n_servers, end, finished


def make_windows(start, stop, every):
    if every is None:
        return [(start, stop)]
    edges = [start]
    while edges[-1] + every < stop - 1e-9:
        edges.append(edges[-1] + every)
    edges.append(stop)
    return list(zip(edges[:-1], edges[1:]))


def load_by_window(readings, n_servers, windows):
    """Time-weighted load per window: mean over servers, standard deviation
    of the servers' window means, and the mean number of full servers."""
    starts = [a for a, _ in windows]
    lengths = [b - a for a, b in windows]
    stop = windows[-1][1]
    per_server = np.zeros((n_servers, len(windows)))
    full_time = np.zeros(len(windows))

    for index, events in enumerate(readings.values()):
        if index >= n_servers:
            break
        events.sort(key=lambda e: e[0])   # stable: log order breaks ties
        for k, (t0, value) in enumerate(events):
            t1 = events[k + 1][0] if k + 1 < len(events) else stop
            if t1 <= t0 or value <= 0:
                continue
            w = max(0, bisect.bisect_right(starts, t0) - 1)
            while w < len(windows) and windows[w][0] < t1:
                a, b = windows[w]
                overlap = min(b, t1) - max(a, t0)
                if overlap > 0:
                    per_server[index, w] += value * overlap
                    if value >= 1.0 - 1e-9:
                        full_time[w] += overlap
                w += 1

    means = per_server / np.array(lengths)
    return [(means[:, w].mean(), means[:, w].std(), full_time[w] / lengths[w])
            for w in range(len(windows))]


def request_stats_by_window(requests, windows):
    starts = [a for a, _ in windows]
    stats = [_new_window_stats() for _ in windows]
    for t, kind, gap in requests:
        # the last window includes its end, so a window over the whole run
        # counts every request
        if t < windows[0][0] or t > windows[-1][1]:
            continue
        w = bisect.bisect_right(starts, t) - 1
        if kind == "nofwd":
            stats[w]["not_forwarded"] += 1
            stats[w]["total"] += 1
        else:
            _consume_gap(gap, stats[w])
    return stats


def _mean_pct(values):
    return f"{np.mean(values) * 100:.3g}" if values else "-"


def format_row(window, s, load, partial):
    a, b = window
    total = s["total"]
    served = total - s["blocked"] - s["not_forwarded"]
    accuracy = (s["equal"] + s["same"]) / served * 100 if served else math.nan
    blocked = s["blocked"] / total * 100 if total else math.nan
    load_mean, load_sd, full = load
    return (f"{a:>7.0f} {b:>7.0f}{'*' if partial else ' '} {total:>9,} {blocked:>8.3g} "
            f"{s['not_forwarded']:>6,} {accuracy:>9.4g} {_mean_pct(s['diffs']):>8} "
            f"{_mean_pct(s['decision_gap_values']):>8} {_mean_pct(s['staleness_err_values']):>8} "
            f"{load_mean:>9.3f} {load_sd:>8.3f} {full:>8.1f}")


HEADER = (f"{'from_ms':>7} {'to_ms':>7}  {'requests':>9} {'blocked%':>8} {'nofwd':>6} "
          f"{'accuracy%':>9} {'gap_out%':>8} {'gap_dec%':>8} {'stale%':>8} "
          f"{'load_mean':>9} {'load_sd':>8} {'full_srv':>8}")


def main():
    parser = argparse.ArgumentParser(
        description="Request accuracy and server load per window of simulated time.")
    parser.add_argument("paths", nargs="+", help="log file(s)")
    parser.add_argument("--from", dest="start", type=float, default=0.0,
                        help="start of the window, simulated milliseconds (default 0)")
    parser.add_argument("--to", dest="stop", type=float, default=None,
                        help="end of the window, simulated milliseconds (default: end of the run)")
    parser.add_argument("--every", type=float, default=None,
                        help="split the window into rows of this many milliseconds")
    parser.add_argument("--time-unit", choices=("ms", "s"), default=None,
                        help="clock unit of the log's times, if the header does "
                             "not give it (default ms)")
    args = parser.parse_args()
    if args.every is not None and args.every <= 0:
        parser.error("--every must be positive")

    for index, path in enumerate(args.paths):
        requests, readings, n_servers, end, finished = read_log(path, args.time_unit)
        stop = end if args.stop is None else min(args.stop, end)
        if stop <= args.start:
            print(f"{path}: no data in the window ({args.start:g}-{stop:g} ms)")
            continue
        windows = make_windows(args.start, stop, args.every)
        loads = load_by_window(readings, n_servers, windows)
        stats = request_stats_by_window(requests, windows)

        if len(args.paths) > 1:
            print(path)
        state = "complete" if finished else f"in progress or stopped: data to {end:.1f} ms"
        print(f"{n_servers} servers; run {state}")
        print(HEADER)
        partial = not finished and windows[-1][1] >= end
        for w, (window, s, load) in enumerate(zip(windows, stats, loads)):
            print(format_row(window, s, load, partial and w == len(windows) - 1))
        if partial:
            print("* the last window ends where the log does (run in progress or stopped)")
        print("gaps are means over requests (0 when the best server was chosen); "
              "load is an upper-bound estimate (see --help)")
        if index != len(args.paths) - 1:
            print()


if __name__ == "__main__":
    main()

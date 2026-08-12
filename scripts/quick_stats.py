#!/usr/bin/env python3
"""Parse log files and summarise request accuracy from OUTCOME_GAP lines.

Usage:
    python quick_stats.py -v <log file> [<log file> ...]
"""

import argparse
from collections import defaultdict
import numpy as np

from log_syntax import (
    parse_event_header,
    parse_fib_stability_action,
    parse_gap_line,
    parse_log_header,
    parse_not_forwarded_event,
    parse_server_metric_event,
)


def _consume_gap(gap_line, stats):
    entry_type = gap_line.tag
    status = gap_line.keyword

    if entry_type == "OUTCOME_GAP":
        stats["total"] += 1
        if status == "SAME":
            stats["same"] += 1
            stats["diffs"].append(0.0)
        elif status == "EQUAL":
            stats["equal"] += 1
            stats["diffs"].append(0.0)
        elif status == "BLOCKED":
            stats["blocked"] += 1
            if gap_line.minload is not None and gap_line.minload[2] < 1.0:
                stats["blocked_avoidable"] += 1
            else:
                # Treat missing MINLOAD as unavoidable to keep counters additive.
                stats["blocked_unavoidable"] += 1
        elif status == "DIFFERENT":
            stats["different"] += 1
            diff_value = abs(gap_line.gap)
            stats["diffs"].append(diff_value)
            stats["different_diffs"].append(diff_value)
        return

    # DECISION_GAP and STALENESS_ERR statistics are separate and exclude BLOCKED.
    # We do not strictly need to exclude BLOCKED here as DECISION_GAP and STALENESS_ERR should always be reported even if the request is blocked
    if status == "BLOCKED":
        return

    abs_value = abs(gap_line.gap)
    if entry_type == "DECISION_GAP":
        stats["decision_gap_values"].append(abs_value)
    elif entry_type == "STALENESS_ERR":
        stats["staleness_err_values"].append(abs_value)


def parse_log_lines(lines, filename=None, warn_header=False):
    stats = {
        "log_verbose_level": None,
        "total": 0,
        "equal": 0,
        "same": 0,
        "blocked": 0,
        "not_forwarded": 0,
        "blocked_unavoidable": 0,
        "blocked_avoidable": 0,
        "different": 0,
        "diffs": [],
        "different_diffs": [],
        "decision_gap_values": [],
        "staleness_err_values": [],
        "server_updates_created": 0,
        "server_metrics_announce": 0,
        "server_metrics_withdraw": 0,
        "fib_totals": {"SET": 0, "KEEP": 0, "CHANGED": 0, "REMOVED": 0},
        "fib_router_counts": defaultdict(lambda: {"SET": 0, "KEEP": 0, "CHANGED": 0, "REMOVED": 0}),
        "fib_router_server_counts": defaultdict(lambda: defaultdict(lambda: {"SET": 0, "KEEP": 0, "CHANGED": 0, "REMOVED": 0})),
    }

    parameters, event_lines = parse_log_header(
        lines, filename, warn=warn_header
    )
    if parameters is not None:
        verbose_level = parameters.get("Verbose.level")
        if isinstance(verbose_level, int):
            stats["log_verbose_level"] = verbose_level

    for line in event_lines:
        header = parse_event_header(line)
        if header is None:
            continue

        if header.keyword in {"PACKET_CREATED", "RECV_PACKET"}:
            event = parse_server_metric_event(line, header)
            if event is not None:
                if event.kind == "created":
                    stats["server_updates_created"] += 1
                elif event.operation == "A":
                    stats["server_metrics_announce"] += 1
                elif event.operation == "W":
                    stats["server_metrics_withdraw"] += 1
            continue

        not_forwarded = parse_not_forwarded_event(line, header)
        if not_forwarded is not None:
            stats["not_forwarded"] += 1
            stats["total"] += 1
            continue

        action = parse_fib_stability_action(line, header)
        if action is not None:
            action_key = action.action.split("_", 1)[0]
            stats["fib_totals"][action_key] += 1
            stats["fib_router_counts"][action.router][action_key] += 1
            stats["fib_router_server_counts"][action.router][action.server][action_key] += 1
            continue

        gap_line = parse_gap_line(line, header)
        if gap_line is not None:
            _consume_gap(gap_line, stats)

    return stats


def _format_fib_stability_summary(stats):
    fib_totals = stats.get("fib_totals", {})
    set_count = fib_totals.get("SET", 0)
    changed_count = fib_totals.get("CHANGED", 0)
    keep_count = fib_totals.get("KEEP", 0)
    removed_count = fib_totals.get("REMOVED", 0)
    updates_count = set_count + changed_count
    total_count = updates_count + keep_count + removed_count
    updated_pct = (updates_count / total_count * 100) if total_count else 0.0
    return (
        f"FIB stability: updates: {updates_count:,} "
        f"(set: {set_count:,}, changed: {changed_count:,}), "
        f"kept: {keep_count:,}, removed: {removed_count:,}, "
        f"total: {total_count:,} (churn: {updated_pct:.4g}%)\n"
    )


def format_stats(stats, include_fib_stability=True):
    total = stats["total"]
    equal = stats["equal"]
    same = stats["same"]
    blocked = stats["blocked"]
    not_forwarded = stats["not_forwarded"]
    blocked_unavoidable = stats["blocked_unavoidable"]
    blocked_avoidable = stats["blocked_avoidable"]
    different = stats["different"]
    diffs = stats["diffs"]
    updates = stats["server_updates_created"]
    announces = stats["server_metrics_announce"]
    withdraws = stats["server_metrics_withdraw"]

    if total == 0:
        accuracy = 0.0
        blocked_rate = 0.0
        blocked_unavoidable_rate = 0.0
        blocked_avoidable_rate = 0.0
        mean_diff = 0.0
        mean_diff_including_zero = 0.0
        max_diff = 0.0
    else:
        denom = total - blocked - not_forwarded
        accuracy = (equal + same) / denom if denom else 0.0
        blocked_rate = blocked / total
        blocked_unavoidable_rate = blocked_unavoidable / total
        blocked_avoidable_rate = blocked_avoidable / total
        different_diffs = stats["different_diffs"]
        max_diff = max(different_diffs) if different_diffs else 0.0
        mean_diff = float(np.mean(different_diffs)) if different_diffs else 0.0
        mean_diff_including_zero = float(np.mean(diffs)) if diffs else 0.0

    fib_stability_line = _format_fib_stability_summary(stats) if include_fib_stability else ""

    return (
        f"requests: {total:,}; SAME: {same:,}; EQUAL: {equal:,}; DIFFERENT: {different:,}; BLOCKED: {blocked:,}; NOT_FORWARDED: {not_forwarded:,}\n"
        f"accuracy: {accuracy * 100:.4g}%; blocked: {blocked_rate * 100:.4g}% (unavoidable: {blocked_unavoidable_rate * 100:.4g}%, avoidable: {blocked_avoidable_rate * 100:.4g}%); utility gap: max: {max_diff * 100:.4g}%; mean: {mean_diff_including_zero * 100:.4g}%; mean conditional: {mean_diff * 100:.4g}%\n"
        f"server update events: {updates:,}; "
        f"total update messages: {(announces + withdraws):,} ({announces:,} [{(announces/(announces + withdraws) * 100):.3g}%] announcements, {withdraws:,} [{(withdraws/(announces + withdraws) * 100):.3g}%] withdrawals)\n"
        f"{fib_stability_line}"
    )


def _fmt_row(name, data):
    arr = np.array(data, dtype=float)
    mean_v = arr.mean()
    std_v = arr.std(ddof=0)
    pcts = np.percentile(arr, [0, 10, 25, 50, 75, 90, 100])
    return (
        f"{name}: mean: {mean_v * 100:.4g}%; std: {std_v * 100:.4g}%; "
        f"min: {pcts[0] * 100:.4g}%; 10%: {pcts[1] * 100:.4g}%; 25%: {pcts[2] * 100:.4g}%; "
        f"50%: {pcts[3] * 100:.4g}%; 75%: {pcts[4] * 100:.4g}%; 90%: {pcts[5] * 100:.4g}%; max: {pcts[6] * 100:.4g}%\n"
    )


def _fmt_metric_section(title, values):
    print(title)
    if values:
        print(_fmt_row(f"overall [{len(values):,}]", values), end="")
    else:
        print("overall [0]: N/A")

    non_zero = [v for v in values if v > 0]
    if non_zero:
        print(_fmt_row(f"non-zero [{len(non_zero):,}]", non_zero), end="")
    else:
        print("non-zero [0]: N/A")


def _print_fib_router_table(stats):
    fib_router_counts = stats.get("fib_router_counts", {})
    print("FIB stability by router:")
    router_width = max(
        len("router"),
        len("TOTAL"),
        *(len(router) for router in fib_router_counts),
    ) if fib_router_counts else len("router")
    header = (
        f"{'router':<{router_width}} {'updates':>10} {'set':>10} {'changed':>10} "
        f"{'kept':>10} {'removed':>10} {'total':>10} {'churn':>10}"
    )
    print(header)
    if not fib_router_counts:
        print("(none)")
        return

    total_set = 0
    total_changed = 0
    total_kept = 0
    total_removed = 0
    for router in sorted(fib_router_counts):
        counts = fib_router_counts[router]
        set_count = counts["SET"]
        changed_count = counts["CHANGED"]
        kept_count = counts["KEEP"]
        removed_count = counts["REMOVED"]
        updates_count = set_count + changed_count
        total_count = updates_count + kept_count + removed_count
        updated_pct = (updates_count / total_count * 100) if total_count else 0.0
        total_set += set_count
        total_changed += changed_count
        total_kept += kept_count
        total_removed += removed_count
        print(
            f"{router:<{router_width}} {updates_count:>10,} {set_count:>10,} {changed_count:>10,} "
            f"{kept_count:>10,} {removed_count:>10,} {total_count:>10,} {updated_pct:>9.2f}%"
        )

    grand_updates = total_set + total_changed
    grand_total = grand_updates + total_kept + total_removed
    grand_updated_pct = (grand_updates / grand_total * 100) if grand_total else 0.0
    print(
        f"{'TOTAL':<{router_width}} {grand_updates:>10,} {total_set:>10,} {total_changed:>10,} "
        f"{total_kept:>10,} {total_removed:>10,} {grand_total:>10,} {grand_updated_pct:>9.2f}%"
    )

    
def main():
    parser = argparse.ArgumentParser(description="Summarise OUTCOME_GAP lines in one or more log files.")
    parser.add_argument("paths", nargs="+", help="Path(s) to the log file(s) to parse")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print detailed utility-gap statistics")
    args = parser.parse_args()

    show_filename = len(args.paths) > 1
    for index, path in enumerate(args.paths):
        with open(path, "r", encoding="utf-8") as fh:
            stats = parse_log_lines(fh, filename=path, warn_header=True)

        log_verbose_level = stats.get("log_verbose_level")
        log_is_low_verbosity = log_verbose_level is not None and log_verbose_level < 1
        include_fib_stability = not (not args.verbose and log_is_low_verbosity)

        if show_filename:
            print(path)
        if args.verbose and log_is_low_verbosity:
            print(
                f"The verbose level for {path} is less than 1 so FIB stability, "
                "Decision gap, and Staleness error stats will not be calculated correctly."
            )
        print(format_stats(stats, include_fib_stability=include_fib_stability), end="")
        if args.verbose:
            gaps_all = stats.get("diffs", [])
            gaps_worse = [g for g in stats.get("different_diffs", []) if g > 0]
            print()
            print("Utility gap stats (abs, BLOCKED excluded):")
            if gaps_all:
                print(_fmt_row(f"overall [{len(gaps_all):,}]", gaps_all), end="")
            else:
                print("overall [0]: N/A")

            if gaps_worse:
                print(_fmt_row(f"worse-than-optimal [{len(gaps_worse):,}]", gaps_worse), end="")
            else:
                print("worse-than-optimal [0]: N/A")
            print()
            _fmt_metric_section("Decision gap stats (abs):", stats.get("decision_gap_values", []))
            print()
            _fmt_metric_section("Staleness error stats (abs):", stats.get("staleness_err_values", []))
            print()
            _print_fib_router_table(stats)
        if show_filename and index != len(args.paths) - 1:
            print()


if __name__ == "__main__":
    main()
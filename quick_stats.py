#!/usr/bin/env python3
"""Parse log files and summarise request accuracy from OUTCOME_GAP lines.

Usage:
    python quick_stats.py -v <log file> [<log file> ...]
"""

import argparse
import re
import numpy as np

LOG_LINE_RE = re.compile(r"\b(?P<status>SAME|EQUAL|DIFFERENT|BLOCKED)(?:\s+(?P<diff>-?\d+(?:\.\d+)?))?\s*$")
ENTRY_TYPE_RE = re.compile(r"\b(?P<entry_type>OUTCOME_GAP|DECISION_GAP|STALENESS_ERR)\b")
ENTRY_LINE_START_RE = re.compile(r"^\s*\d+(?:\.\d+)?:\s+\S+\s+(?:OUTCOME_GAP|DECISION_GAP|STALENESS_ERR)\b")
CREATE_SERVER_METRIC_RE = re.compile(r"PACKET_CREATED.*ServerMetric")
RECV_SERVER_METRIC_ANNOUNCEMENT_RE = re.compile(r"RECV_PACKET\s+ServerMetric A")
RECV_SERVER_METRIC_WITHDRAWAL_RE = re.compile(r"RECV_PACKET\s+ServerMetric W")


def _consume_entry(entry, stats):
    type_match = ENTRY_TYPE_RE.search(entry)
    if not type_match:
        return

    entry_type = type_match.group("entry_type")
    match = LOG_LINE_RE.search(entry)
    if not match:
        return

    status = match.group("status")
    diff_text = match.group("diff")

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
        elif status == "DIFFERENT":
            stats["different"] += 1
            diff_value = abs(float(diff_text)) if diff_text is not None else 0.0
            stats["diffs"].append(diff_value)
            stats["different_diffs"].append(diff_value)
        return

    # DECISION_GAP and STALENESS_ERR statistics are separate and exclude BLOCKED.
    if status == "BLOCKED":
        return

    abs_value = abs(float(diff_text)) if diff_text is not None else 0.0
    if entry_type == "DECISION_GAP":
        stats["decision_gap_values"].append(abs_value)
    elif entry_type == "STALENESS_ERR":
        stats["staleness_err_values"].append(abs_value)


def parse_log_lines(lines):
    stats = {
        "total": 0,
        "equal": 0,
        "same": 0,
        "blocked": 0,
        "different": 0,
        "diffs": [],
        "different_diffs": [],
        "decision_gap_values": [],
        "staleness_err_values": [],
        "server_updates_created": 0,
        "server_metrics_announce": 0,
        "server_metrics_withdraw": 0,
    }

    pending_entry = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if CREATE_SERVER_METRIC_RE.search(line):
            stats["server_updates_created"] += 1
        if RECV_SERVER_METRIC_ANNOUNCEMENT_RE.search(line):
            stats["server_metrics_announce"] += 1
        elif RECV_SERVER_METRIC_WITHDRAWAL_RE.search(line):
            stats["server_metrics_withdraw"] += 1

        is_entry_start = bool(ENTRY_LINE_START_RE.search(line))

        if pending_entry is not None:
            if is_entry_start:
                _consume_entry(pending_entry, stats)
                pending_entry = line
            else:
                pending_entry = f"{pending_entry} {line}"

            if LOG_LINE_RE.search(pending_entry):
                _consume_entry(pending_entry, stats)
                pending_entry = None
            continue

        if is_entry_start:
            pending_entry = line
            if LOG_LINE_RE.search(pending_entry):
                _consume_entry(pending_entry, stats)
                pending_entry = None

    if pending_entry is not None:
        _consume_entry(pending_entry, stats)

    return stats


def format_stats(stats):
    total = stats["total"]
    equal = stats["equal"]
    same = stats["same"]
    blocked = stats["blocked"]
    different = stats["different"]
    diffs = stats["diffs"]
    updates = stats["server_updates_created"]
    announces = stats["server_metrics_announce"]
    withdraws = stats["server_metrics_withdraw"]

    if total == 0:
        accuracy = 0.0
        blocked_rate = 0.0
        mean_diff = 0.0
        mean_diff_including_zero = 0.0
        max_diff = 0.0
    else:
        denom = total - blocked
        accuracy = (equal + same) / denom if denom else 0.0
        blocked_rate = blocked / total
        different_diffs = stats["different_diffs"]
        max_diff = max(different_diffs) if different_diffs else 0.0
        mean_diff = float(np.mean(different_diffs)) if different_diffs else 0.0
        mean_diff_including_zero = float(np.mean(diffs)) if diffs else 0.0

    return (
        f"requests: {total:,}; SAME: {same:,}; EQUAL: {equal:,}; DIFFERENT: {different:,}; BLOCKED: {blocked:,}\n"
        f"accuracy: {accuracy * 100:.4g}%; blocked: {blocked_rate * 100:.4g}%; utility gap: max: {max_diff * 100:.4g}%; mean: {mean_diff_including_zero * 100:.4g}%; mean conditional: {mean_diff * 100:.4g}%\n"
        f"server update events: {updates:,}; "
        f"total update messages: {(announces + withdraws):,} ({announces:,} [{(announces/(announces + withdraws) * 100):.3g}%] announcements, {withdraws:,} [{(withdraws/(announces + withdraws) * 100):.3g}%] withdrawals)\n"
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
        print(_fmt_row("overall", values), end="")
    else:
        print("overall: N/A")

    non_zero = [v for v in values if v > 0]
    if non_zero:
        print(_fmt_row("non-zero", non_zero), end="")
    else:
        print("non-zero: N/A")


def main():
    parser = argparse.ArgumentParser(description="Summarise OUTCOME_GAP lines in one or more log files.")
    parser.add_argument("paths", nargs="+", help="Path(s) to the log file(s) to parse")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print detailed utility-gap statistics")
    args = parser.parse_args()

    show_filename = len(args.paths) > 1
    for index, path in enumerate(args.paths):
        with open(path, "r", encoding="utf-8") as fh:
            stats = parse_log_lines(fh)

        if show_filename:
            print(path)
        print(format_stats(stats), end="")
        if args.verbose:
            gaps_all = stats.get("diffs", [])
            gaps_worse = [g for g in stats.get("different_diffs", []) if g > 0]
            print()
            print("Utility gap stats (abs, BLOCKED excluded):")
            if gaps_all:
                print(_fmt_row("overall", gaps_all), end="")
            else:
                print("overall: N/A")

            if gaps_worse:
                print(_fmt_row("worse-than-optimal", gaps_worse), end="")
            else:
                print("worse-than-optimal: N/A")

            print()
            _fmt_metric_section("Decision gap stats (abs, BLOCKED excluded):", stats.get("decision_gap_values", []))
            print()
            _fmt_metric_section("Staleness error stats (abs, BLOCKED excluded):", stats.get("staleness_err_values", []))
        if show_filename and index != len(args.paths) - 1:
            print()


if __name__ == "__main__":
    main()
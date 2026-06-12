#!/usr/bin/env python3
"""Parse BEST_REPLICA_UTILITY log files and summarize request accuracy.

Usage:
    python parse_best_replica_utility_log.py logs/current-first_decide-replica
"""

import argparse
import re
from statistics import mean

LOG_LINE_RE = re.compile(r"\b(?P<status>SAME|EQUAL|DIFFERENT)(?:\s+(?P<diff>-?\d+(?:\.\d+)?))?\s*$")


def parse_log_lines(lines):
    total = 0
    equal = 0
    same = 0
    different = 0
    diffs = []
    different_diffs = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        match = LOG_LINE_RE.search(line)
        if not match:
            continue

        total += 1
        status = match.group("status")
        diff_text = match.group("diff")

        if status == "SAME":
            same += 1
            diffs.append(0.0)
        elif status == "EQUAL":
            equal += 1
            diffs.append(0.0)
        elif status == "DIFFERENT":
            different += 1
            diff_value = float(diff_text) if diff_text is not None else 0.0
            diffs.append(diff_value)
            different_diffs.append(diff_value)

    return {
        "total": total,
        "equal": equal,
        "same": same,
        "different": different,
        "diffs": diffs,
        "different_diffs": different_diffs,
    }


def format_stats(stats):
    total = stats["total"]
    equal = stats["equal"]
    same = stats["same"]
    different = stats["different"]
    diffs = stats["diffs"]

    if total == 0:
        accuracy = 0.0
        mean_diff = 0.0
        mean_diff_including_zero = 0.0
        max_diff = 0.0
    else:
        accuracy = (equal + same) / total
        different_diffs = stats["different_diffs"]
        max_diff = max(different_diffs) if different_diffs else 0.0
        mean_diff = mean(different_diffs) if different_diffs else 0.0
        mean_diff_including_zero = mean(diffs) if diffs else 0.0

    return (
        f"Requests: {total}; "
        f"SAME: {same}; "
        f"EQUAL: {equal}; "
        f"DIFFERENT: {different}\n"
        f"accuracy: {accuracy * 100:.4g}%; "
        f"utility gap: max: {max_diff * 100:.4g}%; "
        f"mean: {mean_diff_including_zero * 100:.4g}%; "
        f"mean conditional: {mean_diff * 100:.4g}%\n"
    )


def main():
    parser = argparse.ArgumentParser(description="Summarize BEST_REPLICA_UTILITY lines in one or more log files.")
    parser.add_argument("paths", nargs="+", help="Path(s) to the log file(s) to parse")
    args = parser.parse_args()

    show_filename = len(args.paths) > 1
    for index, path in enumerate(args.paths):
        with open(path, "r", encoding="utf-8") as fh:
            stats = parse_log_lines(fh)

        if show_filename:
            print(path)
        print(format_stats(stats), end="")
        if show_filename and index != len(args.paths) - 1:
            print()


if __name__ == "__main__":
    main()

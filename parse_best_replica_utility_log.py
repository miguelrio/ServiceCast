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
        f"total requests: {total}\n"
        f"EQUAL: {equal}\n"
        f"SAME: {same}\n"
        f"DIFFERENT: {different}\n"
        f"accuracy: {accuracy * 100:.4g}%\n"
        f"max utility gap: {max_diff * 100:.4g}%\n"
        f"mean utility gap: {mean_diff_including_zero * 100:.4g}%\n"
        f"mean conditional utility gap: {mean_diff * 100:.4g}%\n"
    )


def main():
    parser = argparse.ArgumentParser(description="Summarize BEST_REPLICA_UTILITY lines in a log file.")
    parser.add_argument("path", help="Path to the log file to parse")
    args = parser.parse_args()

    with open(args.path, "r", encoding="utf-8") as fh:
        stats = parse_log_lines(fh)

    print(format_stats(stats))


if __name__ == "__main__":
    main()

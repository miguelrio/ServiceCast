#!/usr/bin/env python3
"""Parse BEST_REPLICA_UTILITY log files and summarize request accuracy.

Usage:
    python parse_best_replica_utility_log.py logs/current-first_decide-replica
"""

import argparse
import re
import numpy as np

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
        mean_diff = float(np.mean(different_diffs)) if different_diffs else 0.0
        mean_diff_including_zero = float(np.mean(diffs)) if diffs else 0.0

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


def main():
    parser = argparse.ArgumentParser(description="Summarise BEST_REPLICA_UTILITY lines in one or more log files.")
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
            # compute overall and conditional gaps
            gaps_all = stats.get("diffs", [])
            gaps_worse = [g for g in stats.get("different_diffs", []) if g > 0]
            print()
            print("Utility gap stats:")
            if gaps_all:
                print(_fmt_row("overall", gaps_all), end="")
            else:
                print("overall: N/A")

            if gaps_worse:
                print(_fmt_row("worse-than-optimal", gaps_worse), end="")
            else:
                print("worse-than-optimal: N/A")
        if show_filename and index != len(args.paths) - 1:
            print()


if __name__ == "__main__":
    main()

import argparse
import sys
from pathlib import Path
import matplotlib.pyplot as plt

from log_syntax import parse_event_header, parse_gap_line, parse_log_header

# plot_load.py parses one or more ServiceCast log files and extracts server
# load values from OUTCOME_GAP entries. For each input file it prints a small
# per-server summary table, then generates two plots: a load-over-time view
# and a time-weighted CDF of load values.
#
# By default, the plots are shown on screen first. After they appear, the
# script asks whether you want to save them. If you answer y, both plots for
# that input file are saved to the output directory. If you answer anything
# else, the plots are closed and not saved.
#
# If you pass --save, the plots are saved directly and are not shown first.
# Use --output-dir to choose where saved plots go; it defaults to plots/.
# Use -v or --verbose to print duplicate and overwrite details to stderr.
#
# Usage:
#   python plot_load.py [options] <log_file1> [<log_file2> ...]
#
# Positional arguments:
#   log_files
#     One or more ServiceCast log files to process.
#
# Options:
#   --save
#     Save the plots instead of showing them on screen first.
#
#   --output-dir OUTPUT_DIR
#     Directory for generated plot images. Defaults to plots/.
#
#   --detail-limit DETAIL_LIMIT
#     Maximum number of duplicate or overwrite detail lines to print when
#     verbose output is enabled. Defaults to 5. Use 0 to disable details.
#
#   -v, --verbose
#     Print duplicate and overwrite detail lines to stderr.


def almost_equal(a, b, eps=1e-9):
    return abs(a - b) <= eps


def weighted_percentile(values, weights, percentile):
    if not values:
        return None

    if len(values) == 1:
        return values[0]

    pairs = sorted(zip(values, weights), key=lambda p: p[0])
    total_weight = sum(w for _, w in pairs)
    if almost_equal(total_weight, 0.0):
        return pairs[-1][0]

    target = percentile * total_weight
    cumulative = 0.0
    for value, weight in pairs:
        cumulative += weight
        if cumulative + 1e-15 >= target:
            return value
    return pairs[-1][0]


def build_weighted_distribution(events, end_time):
    if not events:
        return [], []

    sorted_events = sorted(events, key=lambda x: x[0])
    values = []
    weights = []

    for i, (time_value, load_value) in enumerate(sorted_events):
        if i + 1 < len(sorted_events):
            next_time = sorted_events[i + 1][0]
        else:
            next_time = end_time

        duration = max(0.0, next_time - time_value)
        values.append(load_value)
        weights.append(duration)

    if almost_equal(sum(weights), 0.0):
        # Fallback for degenerate traces where all events have identical time.
        values = [load for _, load in sorted_events]
        weights = [1.0] * len(values)

    return values, weights


def parse_file(file_path, eps=1e-9, verbose=False, detail_limit=20):
    server_events = {}
    file_max_time = None
    parse_errors = 0
    duplicate_skips = 0
    timestamp_overwrites = 0
    duplicate_detail_emitted = 0
    duplicate_detail_suppressed = False
    overwrite_detail_emitted = 0
    overwrite_detail_suppressed = False

    with open(file_path, "r", encoding="utf-8") as handle:
        _, event_lines = parse_log_header(handle, file_path, warn=True)
        for line_num, line in enumerate(event_lines, 1):
            header = parse_event_header(line)
            if header is None or header.keyword != "OUTCOME_GAP":
                continue

            gap_line = parse_gap_line(line, header)
            if gap_line is None:
                parse_errors += 1
                print(
                    f"[parse-warning] {file_path}:{line_num}: could not parse OUTCOME_GAP line",
                    file=sys.stderr,
                )
                continue

            for time_value, server_id, load_value in (
                (gap_line.sel_time, gap_line.sel_server, gap_line.sel_load),
                (gap_line.cmp_time, gap_line.cmp_server, gap_line.cmp_load),
            ):

                if file_max_time is None or time_value > file_max_time:
                    file_max_time = time_value

                events = server_events.setdefault(server_id, [])

                # For same (server, timestamp), keep the latest load value.
                matching_index = None
                for idx, (prior_time, prior_load) in enumerate(events):
                    if almost_equal(prior_time, time_value, eps=eps):
                        matching_index = idx
                        if almost_equal(prior_load, load_value, eps=eps):
                            duplicate_skips += 1
                            if verbose and detail_limit > 0 and duplicate_detail_emitted < detail_limit:
                                print(
                                    f"[duplicate-skip] {file_path}:{line_num}: "
                                    f"server={server_id} time={time_value} load={load_value}",
                                    file=sys.stderr,
                                )
                                duplicate_detail_emitted += 1
                            elif verbose and detail_limit > 0 and not duplicate_detail_suppressed:
                                print(
                                    f"[duplicate-skip] further messages suppressed after {detail_limit} entries",
                                    file=sys.stderr,
                                )
                                duplicate_detail_suppressed = True
                        else:
                            events[idx] = (prior_time, load_value)
                            timestamp_overwrites += 1
                            if verbose and detail_limit > 0 and overwrite_detail_emitted < detail_limit:
                                print(
                                    f"[timestamp-overwrite] {file_path}:{line_num}: "
                                    f"server={server_id} time={time_value} "
                                    f"old_load={prior_load} new_load={load_value}",
                                    file=sys.stderr,
                                )
                                overwrite_detail_emitted += 1
                            elif verbose and detail_limit > 0 and not overwrite_detail_suppressed:
                                print(
                                    f"[timestamp-overwrite] further messages suppressed after {detail_limit} entries",
                                    file=sys.stderr,
                                )
                                overwrite_detail_suppressed = True
                        break

                if matching_index is None:
                    events.append((time_value, load_value))

    normalized = {
        server_id: sorted(events, key=lambda p: p[0])
        for server_id, events in server_events.items()
    }
    return (
        normalized,
        file_max_time,
        parse_errors,
        duplicate_skips,
        timestamp_overwrites,
    )


def make_time_series_plot(server_to_events):
    fig, ax = plt.subplots(figsize=(11, 6))

    for server_id in sorted(server_to_events):
        events = server_to_events[server_id]
        if not events:
            continue
        times = [t for t, _ in events]
        loads = [l for _, l in events]
        ax.step(times, loads, where="post", label=server_id)

    ax.set_title("Server Load Over Time")
    ax.set_xlabel("Time")
    ax.set_ylabel("Load")
    ax.grid(True, alpha=0.3)
    ax.legend(title="Server", fontsize=8)
    fig.tight_layout()
    return fig


def make_cdf_plot(server_to_events, end_time):
    fig, ax = plt.subplots(figsize=(11, 6))

    for server_id in sorted(server_to_events):
        values, weights = build_weighted_distribution(server_to_events[server_id], end_time)
        if not values:
            continue

        pairs = sorted(zip(values, weights), key=lambda p: p[0])
        total = sum(w for _, w in pairs)
        if almost_equal(total, 0.0):
            continue

        x_vals = []
        y_vals = []
        cumulative = 0.0
        for load_value, weight in pairs:
            cumulative += weight
            x_vals.append(load_value)
            y_vals.append(cumulative / total)

        ax.step(x_vals, y_vals, where="post", label=server_id)

    ax.set_title("Server Load CDF (Time-Weighted)")
    ax.set_xlabel("Load")
    ax.set_ylabel("CDF")
    ax.set_ylim(0, 1.0)
    ax.grid(True, alpha=0.3)
    ax.legend(title="Server", fontsize=8)
    fig.tight_layout()
    return fig


def set_figure_window_metadata(fig, title):
    manager = getattr(fig.canvas, "manager", None)
    set_title = getattr(manager, "set_window_title", None)
    if callable(set_title):
        set_title(title)


def print_summary_table(server_to_events, end_time):
    headers = ["server", "count", "min", "p10", "p25", "p50", "p75", "p90", "max"]
    rows = []

    for server_id in sorted(server_to_events):
        events = server_to_events[server_id]
        values, weights = build_weighted_distribution(events, end_time)
        if not values:
            continue

        row = {
            "server": server_id,
            "count": len(events),
            "min": weighted_percentile(values, weights, 0.00),
            "p10": weighted_percentile(values, weights, 0.10),
            "p25": weighted_percentile(values, weights, 0.25),
            "p50": weighted_percentile(values, weights, 0.50),
            "p75": weighted_percentile(values, weights, 0.75),
            "p90": weighted_percentile(values, weights, 0.90),
            "max": weighted_percentile(values, weights, 1.00),
        }
        rows.append(row)

    if not rows:
        print("No server load data found.")
        return

    server_width = max(len("server"), max(len(r["server"]) for r in rows))
    count_width = max(len("count"), max(len(str(r["count"])) for r in rows))
    value_width = 7

    header_line = (
        f"{'server':<{server_width}} | {'count':>{count_width}} | "
        + " | ".join(f"{h:>{value_width}}" for h in headers[2:])
    )
    print(header_line)
    print("-" * len(header_line))

    for row in rows:
        metric_text = " | ".join(f"{row[h]:>{value_width}.3f}" for h in headers[2:])
        print(f"{row['server']:<{server_width}} | {row['count']:>{count_width}} | {metric_text}")


def finalize_plots(file_path, fig_specs, output_dir, save_plots):
    stem = Path(file_path).stem
    log_name = Path(file_path).name
    time_plot_name = f"{stem}_load_vs_time.png"
    cdf_plot_name = f"{stem}_load_cdf_time_weighted.png"

    if save_plots:
        output_dir.mkdir(parents=True, exist_ok=True)
        for fig, filename in fig_specs:
            fig.savefig(output_dir / filename, dpi=150)
        for fig, _ in fig_specs:
            plt.close(fig)
        print(f"Saved: {output_dir / time_plot_name}")
        print(f"Saved: {output_dir / cdf_plot_name}")
        return

    plt.show(block=False)
    plt.pause(0.1)
    for fig, filename in fig_specs:
        if "load_vs_time" in filename:
            label = f"Timeseries of {log_name}"
        else:
            label = f"CDF of {log_name}"
        set_figure_window_metadata(fig, label)

    prompt = f"save {time_plot_name}, {cdf_plot_name} to {output_dir} (y/n)? "
    response = input(prompt).strip().lower()
    if response == "y":
        output_dir.mkdir(parents=True, exist_ok=True)
        for fig, filename in fig_specs:
            fig.savefig(output_dir / filename, dpi=150)
        print(f"Saved: {output_dir / time_plot_name}")
        print(f"Saved: {output_dir / cdf_plot_name}")

    for fig, _ in fig_specs:
        plt.close(fig)


def process_one_file(file_path, output_dir, verbose, detail_limit, save_plots):
    server_to_events, max_time, parse_errors, duplicate_skips, timestamp_overwrites = parse_file(
        file_path,
        verbose=verbose,
        detail_limit=detail_limit,
    )

    print(f"\nFile: {file_path}")
    if not server_to_events:
        print("No server load data found.")
        return

    if max_time is None:
        print("No valid timestamps found.")
        return

    print_summary_table(server_to_events, max_time)

    if parse_errors or duplicate_skips or timestamp_overwrites:
        warning_text = (
            f"Warnings: parse={parse_errors}, duplicate_skips={duplicate_skips}, "
            f"timestamp_overwrites={timestamp_overwrites}"
        )
        if not verbose:
            warning_text += " (use -v or --verbose flag to print details to stderr)"
        print(warning_text)

    stem = Path(file_path).stem
    fig_specs = [
        (make_cdf_plot(server_to_events, max_time), f"{stem}_load_cdf_time_weighted.png"),
        (make_time_series_plot(server_to_events), f"{stem}_load_vs_time.png"),
    ]
    if not save_plots:
        # Show the figures on screen before the save prompt so the user can inspect them.
        for fig, _ in fig_specs:
            fig.canvas.draw_idle()

    finalize_plots(file_path, fig_specs, output_dir, save_plots)


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Parse server load logs and generate per-file summaries and plots."
    )
    parser.add_argument("log_files", nargs="+", help="Input log files")
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save plots instead of showing them on screen",
    )
    parser.add_argument(
        "--output-dir",
        default="plots",
        help="Directory for generated plot images (default: plots)",
    )
    parser.add_argument(
        "--detail-limit",
        type=int,
        default=5,
        help="Max duplicate/overwrite warning details per file when -v is set (default: 5, 0 disables)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print duplicate/overwrite detail lines to stderr",
    )
    return parser


def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for file_path in args.log_files:
        if not Path(file_path).exists():
            print(f"[error] file not found: {file_path}", file=sys.stderr)
            continue
        process_one_file(file_path, output_dir, args.verbose, args.detail_limit, args.save)


if __name__ == "__main__":
    main()
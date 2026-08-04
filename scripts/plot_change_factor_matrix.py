import os
import sys
import argparse
import json
import subprocess
from typing import NamedTuple
import numpy as np
import matplotlib.pyplot as plt

# Ensure project path is in sys.path
script_path = os.path.dirname(os.path.abspath(__file__))
project_path = os.path.dirname(script_path)

# Import defaults from Router and Network for CLI auto-detection
from Router import Router

# Shared text colours for a consistent, muted look across every plot.
INK = "#1e293b"      # titles, axis labels
MUTED = "#475569"    # tick labels, colorbar ticks


def current_git_commit():
    """Short hash of the current code, to validate sweep cache provenance."""
    try:
        result = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                cwd=project_path, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except Exception:
        return "unknown"


class MetricSpec(NamedTuple):
    """Everything needed to render one metric's heatmap."""
    data_key: str        # key into the sweep JSON (e.g. "matrix_accuracy")
    file_tag: str        # filename fragment
    title: str           # plot title
    cbar_label: str      # colorbar label
    cmap: str            # matplotlib colormap name
    cell_format: str     # per-cell number format string
    is_percentage: bool  # append "%" to cell labels


# CLI metric name -> how to render it.
METRIC_SPECS = {
    "created":     MetricSpec("matrix_created", "created",
                              "Unique Control Messages Created vs. Damping Factors",
                              "Unique ServerMetric Packets Created", "YlGnBu", "{:,.0f}", False),
    "messages":    MetricSpec("matrix_hops", "messages",
                              "Control Message Hops Transmitted vs. Damping Factors",
                              "Total ServerMetric Hops Transmitted", "YlGnBu", "{:,.0f}", False),
    # Selection-time quality: ground truth at t_sel from the deciding router's
    # vantage (log notation: SEL_UTIL_SEL from STALENESS_ERR's ACTUAL section,
    # BEST_UTIL_SEL from DECISION_GAP's BEST section).
    "accuracy":    MetricSpec("matrix_accuracy", "accuracy",
                              "Selection-Time Accuracy (%) vs. Damping Factors",
                              "SEL_ID = BEST_ID_SEL at t_sel (%)", "YlGn", "{:.1f}", True),
    "mean_all":    MetricSpec("matrix_mean_err_all", "mean_error_all",
                              "Mean Selection-Time Utility Error (All Requests) vs. Damping Factors",
                              "Mean |BEST_UTIL_SEL - SEL_UTIL_SEL|", "Reds", "{:.4f}", False),
    "mean_subopt": MetricSpec("matrix_mean_err_subopt", "mean_error_subopt",
                              "Mean Selection-Time Utility Error (Suboptimal Requests Only) vs. Damping Factors",
                              "Mean |BEST_UTIL_SEL - SEL_UTIL_SEL| (Suboptimal Only)", "Reds", "{:.4f}", False),
    "max_error":   MetricSpec("matrix_max_err", "max_error",
                              "Max Selection-Time Utility Error vs. Damping Factors",
                              "Max |BEST_UTIL_SEL - SEL_UTIL_SEL|", "Reds", "{:.4f}", False),
    "fib_updates": MetricSpec("matrix_fib_updates", "fib_updates",
                              "SERVICE_FIB Updates (Routing Churn) vs. Damping Factors",
                              "Total SERVICE_FIB Updates", "OrRd", "{:,.0f}", False),
    "blocked":     MetricSpec("matrix_blocked_rate", "blocked_rate",
                              "Blocked Request Rate (%) vs. Damping Factors",
                              "Requests Dropped at Full Replica (%)", "OrRd", "{:.1f}", True),
    # Arrival-time (outcome) quality: exactly the OUTCOME_GAP line
    # (B = BEST_UTIL_ARR - SEL_UTIL_ARR, both at t_arr).
    "accuracy_arrival": MetricSpec("matrix_accuracy_arrival", "accuracy_arrival",
                              "Arrival-Time (Outcome) Accuracy (%) vs. Damping Factors",
                              "OUTCOME_GAP (B) = 0 at t_arr (%)", "YlGn", "{:.1f}", True),
    "mean_arrival": MetricSpec("matrix_mean_err_arrival", "mean_error_arrival",
                              "Mean Outcome Gap vs. Damping Factors",
                              "Mean |OUTCOME_GAP| (B = BEST_UTIL_ARR - SEL_UTIL_ARR)", "Reds", "{:.4f}", False),
    "announce":    MetricSpec("matrix_hops_announce", "hops_announce",
                              "Announcement Hops Transmitted vs. Damping Factors",
                              "ServerMetric Announcement Hops", "YlGnBu", "{:,.0f}", False),
    "withdraw":    MetricSpec("matrix_hops_withdraw", "hops_withdraw",
                              "Withdrawal Hops Transmitted vs. Damping Factors",
                              "ServerMetric Withdrawal Hops", "PuRd", "{:,.0f}", False),
    # Log-build only: router-side ServerMetric *receptions* (RECV_PACKET), named for
    # what the log actually measures rather than the probe's LinkEnd.put transmissions.
    "recv_total":  MetricSpec("matrix_recv_total", "recv_total",
                              "ServerMetric Packets Received (Total) vs. Damping Factors",
                              "Total ServerMetric Packets Received", "YlGnBu", "{:,.0f}", False),
    "recv_announce": MetricSpec("matrix_recv_announce", "recv_announce",
                              "ServerMetric Announcements Received vs. Damping Factors",
                              "ServerMetric Announcements Received", "YlGnBu", "{:,.0f}", False),
    "recv_withdraw": MetricSpec("matrix_recv_withdraw", "recv_withdraw",
                              "ServerMetric Withdrawals Received vs. Damping Factors",
                              "ServerMetric Withdrawals Received", "PuRd", "{:,.0f}", False),
}

# Derived from METRIC_SPECS so the metric set is defined in exactly one place.
ALL_METRICS = list(METRIC_SPECS)
META_KEYS = ["hop_by_hop", "delays", "server_cfs", "router_cfs"]
# A valid file only needs the structural meta keys; the metric arrays themselves
# differ between the probe build (hops*) and the log build (recv*), so each metric's
# presence is validated per-metric at plot time (see generate_matrix_plots).
REQUIRED_KEYS = META_KEYS


def _cell_labels(data, format_str, is_percentage):
    """Pre-render every cell's text; the widest one drives cell sizing/font."""
    n_rows, n_cols = data.shape
    labels = np.empty((n_rows, n_cols), dtype=object)
    for i in range(n_rows):
        for j in range(n_cols):
            text = format_str.format(data[i, j])
            if is_percentage:
                text += "%"
            labels[i, j] = text
    max_chars = max(len(labels[i, j]) for i in range(n_rows) for j in range(n_cols))
    return labels, max_chars


def _cell_inches(max_chars):
    """Inches per heatmap cell so the widest label fits with breathing room."""
    return max(0.5, max_chars * 0.11)


def _label_font_size(cell_in, max_chars, floor=4.0):
    """Per-cell number font size, scaled to the cell so numbers stay readable
    on large grids instead of collapsing into mush."""
    return max(floor, min(9.0, cell_in * 72 / (max_chars * 0.95)))


def _save_figure(filename, kind="Plot"):
    """Write the current figure into matrix_plots/ at publication DPI and close it."""
    plots_dir = os.path.join(project_path, "matrix_plots")
    os.makedirs(plots_dir, exist_ok=True)
    output_path = os.path.join(plots_dir, filename)
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"{kind} saved successfully to: {output_path}")


def _draw_heatmap(ax, data, server_cfs, router_cfs, cmap, format_str, is_percentage,
                  vmin, vmax, cell_label_fs, labels=None,
                  show_xlabel=True, show_ylabel=True):
    """Render one heatmap (imshow + per-cell numbers + ticks) into the given axes.

    `vmin`/`vmax` let several panels share a common colour scale. Returns the image
    so the caller can attach a colorbar. Pure drawing - no figure or file handling.
    """
    n_rows, n_cols = data.shape
    if labels is None:
        labels, _ = _cell_labels(data, format_str, is_percentage)

    im = ax.imshow(data, cmap=cmap, aspect="auto", origin="upper", vmin=vmin, vmax=vmax)

    # Label every row and column, unrotated, as in the original small matrix.
    ax.set_xticks(np.arange(n_cols))
    ax.set_yticks(np.arange(n_rows))
    ax.set_xticklabels([f"{val:.2f}" for val in server_cfs], fontsize=10, color=MUTED)
    ax.set_yticklabels([f"{val:.3f}" for val in router_cfs], fontsize=10, color=MUTED)

    ax.xaxis.tick_top()
    ax.xaxis.set_label_position('top')

    if show_xlabel:
        ax.set_xlabel("Server.change_factor", fontsize=13, fontweight='bold', color=INK, labelpad=15)
    if show_ylabel:
        ax.set_ylabel("Router.fib_utility_update_threshold", fontsize=13, fontweight='bold', color=INK, labelpad=15)

    for edge in ['top', 'bottom', 'left', 'right']:
        ax.spines[edge].set_visible(False)

    # Numeric label in every cell, coloured for contrast against its background.
    threshold = (vmax + vmin) / 2.0
    for i in range(n_rows):
        for j in range(n_cols):
            color = "white" if data[i, j] > threshold else "black"
            ax.text(j, i, labels[i, j], ha="center", va="center",
                    color=color, fontsize=cell_label_fs, fontweight='medium')
    return im


def plot_heatmap(data, title, ylabel_cbar, filename, server_cfs, router_cfs, cmap="YlGnBu", format_str="{:,}", is_percentage=False):
    n_cols, n_rows = len(server_cfs), len(router_cfs)

    labels, max_chars = _cell_labels(data, format_str, is_percentage)

    # Size cells to the widest label, then scale the whole figure with the grid.
    cell_in = _cell_inches(max_chars)
    fig_w = min(80, n_cols * cell_in + 3)
    fig_h = min(70, n_rows * cell_in + 3)
    cell_label_fs = _label_font_size(cell_in, max_chars)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=200)

    im = _draw_heatmap(ax, data, server_cfs, router_cfs, cmap, format_str, is_percentage,
                       vmin=data.min(), vmax=data.max(), cell_label_fs=cell_label_fs,
                       labels=labels)

    cbar = ax.figure.colorbar(im, ax=ax, pad=0.04)
    cbar.ax.set_ylabel(ylabel_cbar, rotation=-90, va="bottom", fontsize=12, fontweight='medium', color=INK)
    cbar.ax.tick_params(labelsize=10, colors=MUTED)
    cbar.outline.set_visible(False)

    ax.set_title(title, fontsize=15, fontweight='bold', color=INK, pad=30)

    plt.tight_layout()
    _save_figure(filename, kind="Plot")


def plot_faceted_heatmap(data3d, delays, title, ylabel_cbar, filename, server_cfs, router_cfs,
                         cmap="YlGnBu", format_str="{:,}", is_percentage=False):
    """Faceted small-multiples: one heatmap panel per propagation-delay value.

    All panels share a single colour scale (vmin/vmax over every delay slice) and one
    colorbar, so the staleness trend is comparable by scanning across panels.
    `data3d` is indexed [delay][router_cf][server_cf].
    """
    data3d = np.asarray(data3d)
    n_delays = len(delays)
    n_cols, n_rows = len(server_cfs), len(router_cfs)

    # Shared colour scale across all delay slices for this metric.
    vmin, vmax = float(data3d.min()), float(data3d.max())
    if vmin == vmax:                       # avoid a degenerate colour range
        vmax = vmin + 1e-9

    # The widest label across the whole metric drives cell sizing/font.
    max_chars = max(_cell_labels(data3d[k], format_str, is_percentage)[1] for k in range(n_delays))

    # Pick a cell size, then shrink uniformly so the full row of panels stays within
    # a sane total width. Font tracks the final cell size.
    cell_in = _cell_inches(max_chars)
    max_total_w = 60.0                     # inches, hard cap on the whole figure
    panel_gap = 0.6                        # inches of padding charged per panel
    total_w = n_delays * (n_cols * cell_in + panel_gap) + 3
    if total_w > max_total_w:
        cell_in *= (max_total_w - 3) / (n_delays * (n_cols * cell_in + panel_gap))
        cell_in = max(0.18, cell_in)
    cell_label_fs = _label_font_size(cell_in, max_chars, floor=3.0)

    fig_w = min(max_total_w, n_delays * (n_cols * cell_in + panel_gap) + 3)
    fig_h = min(70, n_rows * cell_in + 3)
    fig, axes = plt.subplots(1, n_delays, figsize=(fig_w, fig_h), dpi=200, squeeze=False)
    axes = axes[0]

    im = None
    for k, delay in enumerate(delays):
        ax = axes[k]
        im = _draw_heatmap(ax, data3d[k], server_cfs, router_cfs, cmap, format_str, is_percentage,
                           vmin=vmin, vmax=vmax, cell_label_fs=cell_label_fs,
                           show_xlabel=True, show_ylabel=(k == 0))
        ax.set_title(f"delay = {delay}", fontsize=13, fontweight='bold', color=INK, pad=18)

    cbar = fig.colorbar(im, ax=axes.tolist(), pad=0.02, fraction=0.025)
    cbar.ax.set_ylabel(ylabel_cbar, rotation=-90, va="bottom", fontsize=12, fontweight='medium', color=INK)
    cbar.ax.tick_params(labelsize=10, colors=MUTED)
    cbar.outline.set_visible(False)

    fig.suptitle(title, fontsize=13, fontweight='bold', color=INK, y=1.2)

    _save_figure(filename, kind="Faceted plot")


def generate_matrix_plots(data, metrics):
    # Construct filenames and titles based on routing mode
    mode_str = "hop_by_hop" if data["hop_by_hop"] else "first_decide"
    mode_title = "Hop-by-Hop" if data["hop_by_hop"] else "First Decide"

    # How the metrics were collected. Goes in both the title and the filename so a
    # log-based plot is never mistaken for a monkey-patch one (and they don't clobber
    # each other on disk). Older caches with no "source" key are monkey-patch (probe).
    source = data.get("source", "probe")
    source_title = "Pure Log" if source == "log" else "Monkey-Patch (legacy)"

    suffix = f"{mode_str}_{source}"
    title_suffix = f"\n({mode_title}, Collected: {source_title})"

    delays = data["delays"]
    server_cfs, router_cfs = data["server_cfs"], data["router_cfs"]

    print(f"\nGenerating heatmaps for metrics: {metrics} across {len(delays)} delays {delays}...")

    for metric in metrics:
        spec = METRIC_SPECS[metric]
        if spec.data_key not in data:
            # Probe and log builds carry different metric sets; skip ones this file lacks.
            print(f"  - skipping '{metric}': '{spec.data_key}' not in data "
                  f"(source={data.get('source', 'probe')})")
            continue
        data3d = np.array(data[spec.data_key])   # [delay][router_cf][server_cf]

        # Primary deliverable: faceted small-multiples, one panel per delay, shared scale.
        plot_faceted_heatmap(
            data3d, delays,
            spec.title + title_suffix, spec.cbar_label,
            f"change_factor_matrix_{spec.file_tag}_{suffix}_facet.png",
            server_cfs, router_cfs,
            cmap=spec.cmap, format_str=spec.cell_format, is_percentage=spec.is_percentage,
        )

        # Secondary: full-size single-panel PNG per delay for zoom-in.
        for k, delay in enumerate(delays):
            delay_tag = f"{delay:g}".replace(".", "p")
            plot_heatmap(
                data3d[k],
                spec.title + title_suffix + f"\nPropagation delay = {delay}",
                spec.cbar_label,
                f"change_factor_matrix_{spec.file_tag}_{suffix}_delay{delay_tag}.png",
                server_cfs, router_cfs,
                cmap=spec.cmap, format_str=spec.cell_format, is_percentage=spec.is_percentage,
            )


def parse_args():
    parser = argparse.ArgumentParser(description="Sweep damping parameters and plot heatmaps.")
    parser.add_argument(
        "--metrics",
        nargs="+",
        choices=ALL_METRICS + ["all"],
        default=["all"],
        help="List of metrics to plot. Defaults to 'all'."
    )
    parser.add_argument(
        "--hop-by-hop",
        type=str,
        choices=["true", "false"],
        default="false",
        help="Set Router.hop_by_hop (true or false). Defaults to false."
    )
    parser.add_argument(
        "--delays",
        nargs="+",
        type=float,
        default=[0.1, 0.5, 1.0, 2.0, 4.0],
        help="Graph.default_propagation_delay values to sweep as the third axis. "
             "Use a short list (e.g. --delays 0.1 1) for a quick smoke test."
    )
    parser.add_argument(
        "--source",
        type=str,
        choices=["log", "probe"],
        default="log",
        help="Which collector to use on a cache miss and which default cache file to read: "
             "'log' (purely from log text, default) or 'probe' (legacy monkey-patch in-memory)."
    )
    parser.add_argument(
        "--data-file",
        type=str,
        default=None,
        help="Path to JSON results file to plot directly from."
    )
    parser.add_argument(
        "--rerun",
        action="store_true",
        help="Ignore any cached sweep data and run the simulation sweep again."
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="For --source log (the default): parallel worker processes for the sweep. "
             "Use 0 for auto (cores-2)."
    )
    return parser.parse_args()


def resolve_config(args):
    """Resolve the routing mode and the cache file path, auto-detecting the mode
    from the codebase when it is not given on the command line."""
    if args.hop_by_hop is None:
        hop_by_hop = Router.hop_by_hop
        print(f"Auto-detected Router.hop_by_hop from codebase: {hop_by_hop}")
    else:
        hop_by_hop = args.hop_by_hop.lower() == "true"

    if args.data_file:
        data_file_path = args.data_file
    else:
        mode_str = "hop_by_hop" if hop_by_hop else "first_decide"
        prefix = "sweep_data_log" if args.source == "log" else "sweep_data"
        data_file_path = os.path.join(project_path, "matrix_data", f"{prefix}_{mode_str}.json")

    return hop_by_hop, data_file_path


def load_cached_sweep(path):
    """Return cached sweep data from `path`, or None if it is missing or in an
    outdated format. Warns when the cache predates the current code commit so
    stale results are never plotted silently."""
    if not os.path.exists(path):
        return None

    try:
        print(f"Loading cached sweep data from: {path}")
        with open(path, "r") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error loading cache: {e}")
        return None

    if not all(k in data for k in REQUIRED_KEYS):
        print("Cache data is in an outdated format. Discarding cache...")
        return None

    cached_commit = data.get("code_commit")
    generated_at = data.get("generated_at", "unknown time")
    if cached_commit is None:
        print("WARNING: cache has no code version recorded - "
              "use --rerun if the simulation code has changed since it was generated.")
    elif cached_commit != current_git_commit():
        print(f"WARNING: cache was generated at {generated_at} from commit {cached_commit}, "
              f"but the code is now at {current_git_commit()} - use --rerun for fresh data.")
    else:
        print(f"Cache generated at {generated_at} from current commit {cached_commit}.")
    return data


def main():
    args = parse_args()
    hop_by_hop, data_file_path = resolve_config(args)

    # Load from cache if valid, otherwise run the simulation sweep.
    data = None
    if args.rerun:
        print("--rerun given: ignoring any cached sweep data.")
    else:
        data = load_cached_sweep(data_file_path)

    if data is None:
        if args.source == "log":
            print("Running LOG-based simulation sweep...")
            from run_simulation_sweep_log import run_sweep_log
            data = run_sweep_log(hop_by_hop, data_file_path,
                                 delays=args.delays, jobs=args.jobs)
        else:
            print("Running legacy monkey-patch (probe) simulation sweep...")
            from run_simulation_sweep import run_sweep
            data = run_sweep(hop_by_hop, data_file_path, delays=args.delays)

    selected_metrics = ALL_METRICS if "all" in args.metrics else args.metrics
    generate_matrix_plots(data, selected_metrics)


if __name__ == "__main__":
    main()

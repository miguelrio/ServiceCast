import os
import sys
import argparse
import json
import subprocess
import numpy as np
import matplotlib.pyplot as plt

# Ensure project path is in sys.path
project_path = os.path.dirname(os.path.abspath(__file__))
if project_path not in sys.path:
    sys.path.insert(0, project_path)

# Import defaults from Router and Network for CLI auto-detection
from Router import Router
from Network import Network
from Utility import Place

def current_git_commit():
    """Short hash of the current code, to validate sweep cache provenance."""
    try:
        result = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                cwd=project_path, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except Exception:
        return "unknown"

# metric name -> (data key, filename tag, title, colorbar label, colormap, cell format, is_percentage)
METRIC_SPECS = {
    "created":     ("matrix_created",         "created",
                    "Unique Control Messages Created vs. Damping Factors",
                    "Unique ServerMetric Packets Created",           "YlGnBu", "{:,.0f}", False),
    "messages":    ("matrix_hops",            "messages",
                    "Control Message Hops Transmitted vs. Damping Factors",
                    "Total ServerMetric Hops Transmitted",           "YlGnBu", "{:,.0f}", False),
    "accuracy":    ("matrix_accuracy",        "accuracy",
                    "Oracle Selection Accuracy (%) vs. Damping Factors",
                    "Selection Accuracy (%)",                        "YlGn",   "{:.1f}",  True),
    "mean_all":    ("matrix_mean_err_all",    "mean_error_all",
                    "Mean Utility Error (All Requests) vs. Damping Factors",
                    "Mean Absolute Utility Error (All)",             "Reds",   "{:.4f}",  False),
    "mean_subopt": ("matrix_mean_err_subopt", "mean_error_subopt",
                    "Mean Utility Error (Suboptimal Requests Only) vs. Damping Factors",
                    "Mean Absolute Utility Error (Suboptimal Only)", "Reds",   "{:.4f}",  False),
    "max_error":   ("matrix_max_err",         "max_error",
                    "Max Utility Error vs. Damping Factors",
                    "Max Absolute Utility Error",                    "Reds",   "{:.4f}",  False),
}

def plot_heatmap(data, title, ylabel_cbar, filename, server_cfs, router_cfs, cmap="YlGnBu", format_str="{:,}", is_percentage=False):
    fig, ax = plt.subplots(figsize=(12, 10), dpi=300)
    im = ax.imshow(data, cmap=cmap, aspect="auto", origin="upper")
    
    cbar = ax.figure.colorbar(im, ax=ax, pad=0.04)
    cbar.ax.set_ylabel(ylabel_cbar, rotation=-90, va="bottom", fontsize=12, fontweight='medium', color='#1e293b')
    cbar.ax.tick_params(labelsize=10, colors='#475569')
    cbar.outline.set_visible(False)

    ax.set_xticks(np.arange(len(server_cfs)))
    ax.set_yticks(np.arange(len(router_cfs)))
    ax.set_xticklabels([f"{val:.2f}" for val in server_cfs], fontsize=10, color='#475569')
    ax.set_yticklabels([f"{val:.3f}" for val in router_cfs], fontsize=10, color='#475569')

    ax.xaxis.tick_top()
    ax.xaxis.set_label_position('top')
    
    ax.set_xlabel("Server.change_factor", fontsize=13, fontweight='bold', color='#1e293b', labelpad=15)
    ax.set_ylabel("Router.fib_utility_update_threshold", fontsize=13, fontweight='bold', color='#1e293b', labelpad=15)
    ax.set_title(title, fontsize=15, fontweight='bold', color='#1e293b', pad=30)

    for edge in ['top', 'bottom', 'left', 'right']:
        ax.spines[edge].set_visible(False)

    # Add numeric labels in each cell
    threshold = (data.max() + data.min()) / 2.0
    for i in range(len(router_cfs)):
        for j in range(len(server_cfs)):
            val = data[i, j]
            color = "white" if val > threshold else "black"
            label = format_str.format(val)
            if is_percentage:
                label += "%"
            ax.text(j, i, label, ha="center", va="center", color=color, fontsize=8, fontweight='medium')

    plt.tight_layout()
    plots_dir = os.path.join(project_path, "matrix_plots")
    os.makedirs(plots_dir, exist_ok=True)
    output_path = os.path.join(plots_dir, filename)
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Plot saved successfully to: {output_path}")

def generate_matrix_plots(data, metrics):
    # Construct filenames and titles based on routing mode and oracle timing
    mode_str = "hop_by_hop" if data["hop_by_hop"] else "first_decide"
    mode_title = "Hop-by-Hop" if data["hop_by_hop"] else "First Decide"
    oracle_timing = data["oracle_timing"]

    suffix = f"{mode_str}_{oracle_timing}"
    title_suffix = f"\n({mode_title}, Oracle: {oracle_timing.capitalize()})"

    print(f"\nGenerating heatmaps for metrics: {metrics}...")

    for metric in metrics:
        data_key, file_tag, title, cbar_label, cmap, cell_format, is_percentage = METRIC_SPECS[metric]
        plot_heatmap(
            np.array(data[data_key]),
            title + title_suffix,
            cbar_label,
            f"change_factor_matrix_{file_tag}_{suffix}.png",
            data["server_cfs"], data["router_cfs"],
            cmap=cmap, format_str=cell_format, is_percentage=is_percentage
        )

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sweep damping parameters and plot heatmaps.")
    parser.add_argument(
        "--metrics", 
        nargs="+", 
        choices=["created", "messages", "accuracy", "mean_all", "mean_subopt", "max_error", "all"], 
        default=["all"], 
        help="List of metrics to plot. Defaults to 'all'."
    )
    parser.add_argument(
        "--hop-by-hop", 
        type=str, 
        choices=["true", "false"], 
        default=None, 
        help="Set Router.hop_by_hop (true or false). Defaults to auto-detected value from codebase."
    )
    parser.add_argument(
        "--oracle-timing", 
        type=str, 
        choices=["replica", "router", "client"], 
        default=None, 
        help="Set Network.optimal_utility_timing. Defaults to auto-detected value from codebase."
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
    args = parser.parse_args()
    
    # Process arguments with auto-detection from codebase
    if args.hop_by_hop is None:
        hop_by_hop = Router.hop_by_hop
        print(f"Auto-detected Router.hop_by_hop from codebase: {hop_by_hop}")
    else:
        hop_by_hop = args.hop_by_hop.lower() == "true"
        
    if args.oracle_timing is None:
        oracle_timing = Network.optimal_utility_timing
        print(f"Auto-detected Network.optimal_utility_timing from codebase: '{oracle_timing}'")
    else:
        oracle_timing = args.oracle_timing.lower()

    # Determine default data file path if not overridden
    if args.data_file:
        data_file_path = args.data_file
    else:
        mode_str = "hop_by_hop" if hop_by_hop else "first_decide"
        timing_str = oracle_timing.name.lower() if isinstance(oracle_timing, Place) else oracle_timing
        data_file_path = os.path.join(project_path, "matrix_data", f"sweep_data_{mode_str}_{timing_str}.json")

    # Load from cache if valid, otherwise run simulation sweep
    data_loaded = False
    if args.rerun:
        print("--rerun given: ignoring any cached sweep data.")
    elif os.path.exists(data_file_path):
        try:
            print(f"Loading cached sweep data from: {data_file_path}")
            with open(data_file_path, "r") as f:
                data = json.load(f)
            # Check if all required keys are present
            required_keys = ["hop_by_hop", "oracle_timing", "server_cfs", "router_cfs",
                             "matrix_created", "matrix_hops", "matrix_accuracy",
                             "matrix_mean_err_all", "matrix_mean_err_subopt", "matrix_max_err"]
            if all(k in data for k in required_keys):
                data_loaded = True
            else:
                print("Cache data is in an outdated format. Discarding cache...")
        except Exception as e:
            print(f"Error loading cache: {e}")

    if data_loaded:
        # Warn if the cached data was generated from a different code version,
        # so stale results are never plotted silently
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
    else:
        print("Running simulation sweep...")
        from run_simulation_sweep import run_sweep
        data = run_sweep(hop_by_hop, oracle_timing, data_file_path)
            
    selected_metrics = args.metrics
    if "all" in selected_metrics:
        selected_metrics = ["created", "messages", "accuracy", "mean_all", "mean_subopt", "max_error"]
        
    generate_matrix_plots(data, selected_metrics)

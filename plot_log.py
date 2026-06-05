import os
import sys
import re
import csv
import pandas as pd
import matplotlib.pyplot as plt

# Ensure sibling imports work regardless of execution directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from log_to_csv import convert_log_to_csv

def generate_utility_plot():
    # Resolve absolute paths relative to the script location
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Handle optional command-line input (CSV or LOG file)
    input_file = sys.argv[1] if len(sys.argv) > 1 else None
    
    if input_file:
        if not os.path.exists(input_file):
            print(f"Error: Input file not found: {input_file}")
            return
        
        if input_file.endswith('.csv'):
            csv_path = input_file
        else:
            # Assume it's a log file, parse it first to a temporary CSV
            plots_dir = os.path.join(script_dir, 'plots')
            os.makedirs(plots_dir, exist_ok=True)
            csv_path = os.path.join(plots_dir, 'parsed_choices.csv')
            convert_log_to_csv(input_file, csv_path)
    else:
        # Locate the default CSV file
        csv_path = os.path.abspath(os.path.join(script_dir, '..', 'replica_choices_investigation.csv'))
        if not os.path.exists(csv_path):
            csv_path = os.path.abspath(os.path.join(script_dir, 'replica_choices_investigation.csv'))
        
    if not os.path.exists(csv_path):
        print(f"Error: CSV file not found at: {csv_path}")
        print("Please provide a log file or a CSV file: python3 plot_results.py [log_or_csv_file]")
        return

    # Load data
    df = pd.read_csv(csv_path)

    # Create figure with high DPI and clean sizing
    fig, ax = plt.subplots(figsize=(12, 10), dpi=300)

    # Grid and background styling for maximum elegance
    ax.grid(True, linestyle='--', alpha=0.5, color='#cbd5e1')
    ax.set_facecolor('#f8fafc')
    fig.patch.set_facecolor('#ffffff')

    # Determine limits dynamically to fit the data range exactly with a slight margin
    if not df.empty:
        min_val = min(df['Optimal_Utility'].min(), df['Selected_Utility'].min())
        max_val = max(df['Optimal_Utility'].max(), df['Selected_Utility'].max())
        margin = (max_val - min_val) * 0.05 if max_val != min_val else 0.05
        xlims = [min_val - margin, max_val + margin]
    else:
        xlims = [0.0, 1.0]

    ax.plot(xlims, xlims, linestyle='--', color='#ef4444', linewidth=2, label='Perfect Selection (y=x)')

    # Group by exact coordinates to generate clean, non-overlapping annotations
    grouped = df.groupby(['Optimal_Utility', 'Selected_Utility'])

    # Plot all points with a modern steel blue color and transparency for natural density scaling
    ax.scatter(
        df['Optimal_Utility'], 
        df['Selected_Utility'], 
        s=60, 
        color='#3b82f6', 
        alpha=0.5, 
        edgecolors='#1d4ed8', 
        linewidths=0.5, 
        zorder=3
    )

    # Annotate grouped coordinate points elegant and clearly
    for (opt_util, sel_util), group in grouped:
        # Unique sorted list of client names for this exact coordinate
        clients = ",".join(sorted(group['Client'].unique()))
        count = len(group)
        
        # Format label text to maintain 4 decimal places of utility resolution
        # Show oracle utility
        # label_text = f"{clients}\n{opt_util:.4f}"
        # Show selected utility
        label_text = f"{clients}\n{sel_util:.4f}"
        # Show both
        # label_text = f"{clients}\n{opt_util:.4f} | {sel_util:.4f}"
        if count > 1:
            label_text += f" ({count})"

        # Offset heuristic: diagonal elements go up-left, off-diagonal elements go down-right
        if abs(opt_util - sel_util) < 1e-7:
            xytext = (-6, 6)
            ha = 'right'
            va = 'bottom'
        else:
            xytext = (6, -6)
            ha = 'left'
            va = 'top'

        ax.annotate(
            label_text,
            xy=(opt_util, sel_util),
            xytext=xytext,
            textcoords='offset points',
            fontsize=6,
            color='#1e293b',
            fontweight='medium',
            ha=ha,
            va=va,
            bbox=dict(boxstyle='round,pad=0.1', facecolor='#ffffff', edgecolor='none', alpha=0.7, zorder=2),
            zorder=4
        )

    # Calculate oracle divergence metrics
    total_samples = len(df)
    divergent_samples = len(df[df['Is_Optimal'] == 'DIFFERENT'])
    percentage_diff = (divergent_samples / total_samples) * 100

    # Display stats text box at bottom right
    info_text = f"Different from oracle: {divergent_samples}/{total_samples} ({percentage_diff:.1f}%)"
    ax.text(
        0.95, 0.05, info_text,
        transform=ax.transAxes,
        fontsize=11,
        fontweight='bold',
        color='#1e293b',
        ha='right',
        va='bottom',
        bbox=dict(boxstyle='round,pad=0.5', facecolor='#fef08a', edgecolor='#cbd5e1', alpha=0.9, zorder=5)
    )

    # Determine the title based on the input file name
    if input_file:
        if "first_decide" in input_file.lower():
            title = "First Decide: Optimal vs Selected Utility"
        elif "hop_by_hop" in input_file.lower():
            title = "Hop-by-Hop: Optimal vs Selected Utility"
        else:
            title = "ServiceCast: Optimal vs Selected Utility"

        # Detect oracle timing from the filename and append to title
        input_lower = input_file.lower()
        if "router" in input_lower:
            title += " (Oracle: Router)"
        elif "client" in input_lower:
            title += " (Oracle: Client)"
        elif "replica" in input_lower:
            title += " (Oracle: Replica)"
    else:
        title = "ServiceCast: Optimal vs Selected Utility"

    # Title & Axis labels
    ax.set_title(title, fontsize=16, fontweight='bold', color='#1e293b', pad=15)
    ax.set_xlabel("Optimal (Utility)", fontsize=13, color='#334155', labelpad=10)
    ax.set_ylabel("Selected (Utility)", fontsize=13, color='#334155', labelpad=10)

    # Set exact limits
    ax.set_xlim(xlims)
    ax.set_ylim(xlims)

    # Clean borders
    for spine in ['top', 'right', 'left', 'bottom']:
        ax.spines[spine].set_color('#cbd5e1')

    # Tick parameter styling
    ax.tick_params(colors='#475569', labelsize=11)

    # Legend placement
    ax.legend(loc='upper left', frameon=True, facecolor='#ffffff', edgecolor='#cbd5e1', fontsize=11)

    plt.tight_layout()

    # Save to plots directory
    output_dir = os.path.join(script_dir, 'plots')
    os.makedirs(output_dir, exist_ok=True)
    
    base_name = os.path.splitext(os.path.basename(input_file))[0] if input_file else "optimal_vs_selected"
    output_path = os.path.join(output_dir, f"{base_name}_utility.png")
    
    plt.savefig(output_path, dpi=300)
    print(f"Plot saved successfully to: {output_path}")

if __name__ == "__main__":
    generate_utility_plot()

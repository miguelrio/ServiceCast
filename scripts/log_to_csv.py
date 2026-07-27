import re
import csv
import sys
import os

def convert_log_to_csv(log_path, csv_path):
    # Pre-compiled regex to match BEST_REPLICA_UTILITY log lines
    log_pattern = re.compile(
        r"([0-9.]+):\s*Net\s*BEST_REPLICA_UTILITY\s*'([^']+)'\s*pkt:\s*([a-zA-Z0-9]+)\.([0-9]+)\s*"
        r"selected:\s*(\S+)\s*load\(([^)]+)\)\s*latency\(([^)]+)\)\s*utility\(([^)]+)\)\s*"
        r"best\s*\(at\s*([0-9.]+)\):\s*(\S+)\s*load\(([^)]+)\)\s*latency\(([^)]+)\)\s*utility\(([^)]+)\)"
    )

    headers = [
        "Timestamp", "Client", "Packet_ID", "Requesting_Server",
        "Selected_Replica", "Selected_Raw_Load", "Selected_Raw_Delay",
        "Selected_Load_Utility", "Selected_Delay_Utility", "Selected_Utility",
        "Optimal_Snapshot_Time", "Optimal_Replica", "Optimal_Raw_Load", "Optimal_Raw_Delay",
        "Optimal_Load_Utility", "Optimal_Delay_Utility", "Optimal_Utility",
        "Is_Optimal", "Utility_Diff"
    ]

    records = []

    with open(log_path, 'r') as f:
        for line in f:
            if 'BEST_REPLICA_UTILITY' not in line:
                continue
            
            match = log_pattern.search(line)
            if match:
                timestamp = float(match.group(1))
                req_server = match.group(2)
                client = match.group(3)
                pkt_id = int(match.group(4))
                sel_replica = match.group(5)
                sel_load = float(match.group(6))
                sel_delay = float(match.group(7))
                
                opt_snapshot_time = float(match.group(9))
                opt_replica = match.group(10)
                opt_load = float(match.group(11))
                opt_delay = float(match.group(12))

                # Extract the exact utility values directly from the logged decisions
                # to handle changes in topology, alpha, or the utility formula.
                sel_util = float(match.group(8))
                opt_util = float(match.group(13))

                # Sub-component utilities are not logged, so they are left empty
                sel_load_util = ""
                sel_delay_util = ""
                opt_load_util = ""
                opt_delay_util = ""

                # is_optimal = "SAME" if sel_replica == opt_replica else "DIFFERENT"
                is_optimal = "SAME" if sel_util == opt_util else "DIFFERENT"
                util_diff = opt_util - sel_util

                records.append([
                    timestamp, client, pkt_id, req_server,
                    sel_replica, sel_load, sel_delay,
                    sel_load_util, sel_delay_util, sel_util,
                    opt_snapshot_time, opt_replica, opt_load, opt_delay,
                    opt_load_util, opt_delay_util, opt_util,
                    is_optimal, util_diff
                ])

    # Save to CSV
    os.makedirs(os.path.dirname(os.path.abspath(csv_path)), exist_ok=True)
    with open(csv_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(records)

    print(f"Successfully converted {len(records)} records from {log_path} to {csv_path}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 log_to_csv.py <log_file_path> [output_csv_path]")
        sys.exit(1)
        
    log_file = sys.argv[1]
    output_csv = sys.argv[2] if len(sys.argv) > 2 else "replica_choices_investigation.csv"
    convert_log_to_csv(log_file, output_csv)

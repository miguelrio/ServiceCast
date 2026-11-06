#!/usr/bin/env python3
"""Turn parsed simulation logs into change-factor matrix results.

This module contains no simulation or subprocess code. Each input cell holds the
axis values used for its main.py run and the metrics parsed from its complete log.
"""

import numpy as np


METRIC_FIELDS = [
    "created", "recv_total", "accuracy", "mean_err_all", "mean_err_subopt",
    "max_err", "fib_updates", "blocked_rate", "accuracy_arrival",
    "mean_err_arrival", "recv_announce", "recv_withdraw",
]


def summarise_records(records):
    """Reduce per-request utility records to accuracy/error statistics.

    Each record is (selected_sel, best_sel, selected_arr, best_arr). Selection-time
    errors measure the routing decision; arrival-time errors include staleness.
    """
    if not records:
        return {
            "accuracy": 100.0, "mean_err_all": 0.0, "mean_err_subopt": 0.0,
            "max_err": 0.0, "accuracy_arrival": 100.0, "mean_err_arrival": 0.0,
        }

    errors = [abs(best - sel) for sel, best, _, _ in records]
    arrival_errors = [abs(best - sel) for _, _, sel, best in records]
    suboptimal = [error for error in errors if error >= 1e-9]
    correct = sum(1 for error in errors if error < 1e-9)
    correct_arrival = sum(1 for error in arrival_errors if error < 1e-9)
    return {
        "accuracy": correct / len(errors) * 100.0,
        "mean_err_all": float(np.mean(errors)),
        "mean_err_subopt": float(np.mean(suboptimal)) if suboptimal else 0.0,
        "max_err": float(np.max(errors)),
        "accuracy_arrival": correct_arrival / len(arrival_errors) * 100.0,
        "mean_err_arrival": float(np.mean(arrival_errors)),
    }


def cell_from_metrics(log_metrics):
    """Convert one log_metrics.LogMetrics result to the established cell shape."""
    served = len(log_metrics.records)
    blocked_rate = log_metrics.blocked / max(1, log_metrics.blocked + served) * 100.0
    return {
        "created": log_metrics.created,
        "recv_total": log_metrics.recv_total,
        "recv_announce": log_metrics.recv_announce,
        "recv_withdraw": log_metrics.recv_withdraw,
        "fib_updates": log_metrics.fib_updates,
        "blocked_rate": blocked_rate,
        **summarise_records(log_metrics.records),
    }


def build_matrix_data(cells, delays, server_cfs, router_cfs, metrics,
                      hop_by_hop, code_commit, generated_at):
    """Build the JSON-compatible matrix consumed by plot_change_factor_matrix.py."""
    shape = (len(delays), len(router_cfs), len(server_cfs))
    matrices = {name: np.zeros(shape) for name in metrics}
    delay_indices = {value: index for index, value in enumerate(delays)}
    server_indices = {value: index for index, value in enumerate(server_cfs)}
    router_indices = {value: index for index, value in enumerate(router_cfs)}
    seen = set()

    for cell in cells:
        axes = cell["axes"]
        position = (
            delay_indices[axes["GRAPH_DELAY"]],
            router_indices[axes["ROUTER_FIB_UPT"]],
            server_indices[axes["SERVER_CF"]],
        )
        if position in seen:
            raise ValueError(f"duplicate sweep cell at matrix position {position}")
        seen.add(position)
        for name in metrics:
            matrices[name][position] = cell["metrics"][name]

    expected = len(delays) * len(router_cfs) * len(server_cfs)
    if len(seen) != expected:
        raise ValueError(f"incomplete sweep: {len(seen)} cells for a {expected}-cell matrix")

    return {
        "code_commit": code_commit,
        "generated_at": generated_at,
        "source": "log",
        "hop_by_hop": hop_by_hop,
        "delay_unit": "ms",
        "delays": delays,
        "server_cfs": server_cfs,
        "router_cfs": router_cfs,
        **{f"matrix_{name}": matrices[name].tolist() for name in metrics},
    }

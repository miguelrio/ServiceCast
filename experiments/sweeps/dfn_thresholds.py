# The 3 x 3 DFN example from sweep_simple.py, using the matrix collector.
# Run from the repository root:
#   python3 experiments/sweep.py experiments/sweeps/dfn_thresholds.py

BASE_CONFIG = "configs/dfn_s5_c5.py"

FIXED = {
    "UNTIL": 360000,
    "VERBOSE_LEVEL": 1,
}

AXES = {
    "SERVER_CF": [0.001, 0.01, 0.05],
    "ROUTER_FIB_UPT": [0.0001, 0.001, 0.01],
}

METRICS = [
    "created",
    "recv_total",
    "accuracy",
    "mean_err_all",
    "mean_err_subopt",
    "max_err",
    "fib_updates",
    "blocked_rate",
    "accuracy_arrival",
    "mean_err_arrival",
    "recv_announce",
    "recv_withdraw",
]

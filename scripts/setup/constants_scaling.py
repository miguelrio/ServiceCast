# --- Scaling benchmark constants --------------------------------------------
#
# Declares the scaling experiment: the baseline configuration, the axis level
# definitions, and the matrix combination spec (which axes are factorial, which
# are one-at-a-time, the confirmation points, the noise-floor repeat count, and
# the per-group repeat counts). No logic lives here -- `run_scaling_benchmark`
# enumerates the matrix from these declarations, `measure_one` runs one cell.
# Scope is Dfn + Cogentco only.

# --- Fixed service constants (not swept; read by measure_one) ------------------
#
# SERVICE             the single service every client requests
# SERVER_LOAD_LAMBDA  background-load inter-arrival; has no effect here (the
#                     wiring passes background_load=False)
SERVICE = "§a"
SERVER_LOAD_LAMBDA = 55

# --- Baseline config ---------------------------------------------------------
#
# The fixed point every one-at-a-time axis varies from. Dfn, 5 servers, 5
# clients, the calibrated default knobs. Every key `apply_config` reads must be
# present here; swept axes override one (or two) of these keys per level.
BASELINE = {
    "topology":      "Dfn",
    "num_servers":    5,
    "num_clients":    5,
    "arrival_lambda": 0.4,     # mean inter-arrival time (s) between client requests
    "session_lambda": 10,      # mean session length (s)
    "session_scale":  10,      # session-length multiplier (effective ~= lambda*scale)
    "slots":          50,      # server capacity
    "sim_duration":   360,     # simulated seconds per run
    "verbose_level":  1,       # minimum level that emits every needed line
    "server_cf":      0.1,     # Server.change_factor
    "router_cf":      0.1,     # Router.fib_utility_update_threshold
    "prop_delay":     1.0,     # Graph.default_propagation_delay
    "hop_by_hop":     False,   # first-decide unicast (False) or hop-by-hop anycast (True)
    "alpha":          0.50,    # Utility load/delay weighting (inert: no axis sweeps it)
    "seed":           15112022,
}

# --- Group A: factorial core -------------------------------------------------
#
# Cross product of these axes: 2 topologies x 4 arrival rates x 4 server counts
# = 32 configs. This is where interaction is expected: server count and offered
# load couple through the Server.change_factor announcement threshold. Both
# topologies have ample low-degree nodes (0<deg<=3 router pool: Dfn 42 of
# 51 routers, Cogentco 177), so no placement skips at any factorial config
# (max needed = 20+5 = 25).
#
# Each factorial config runs PAIRED: once at verbose 1 / log_mode
# "file" and once at verbose -1 / log_mode "null", so the compute cost and the
# compute+logging+I/O cost are measured separately and their difference is
# logging's true share. Each side repeats FACTORIAL_REPEATS times.
FACTORIAL_AXES = {
    "topology":      ["Dfn", "Cogentco"],
    "arrival_lambda": [1.6, 0.8, 0.4, 0.2],   # mean inter-arrival (s): 0.2 = fastest (most load), 1.6 = slowest
    "num_servers":    [2, 5, 10, 20],
}
FACTORIAL_REPEATS = 3

# --- Group B: one-at-a-time axes from baseline -------------------------------
#
# Each entry maps an axis name to a list of override dicts applied to BASELINE.
# Every OFAT cell runs at log_mode "file" and verbose_level = BASELINE (1),
# repeated OFAT_REPEATS times -- EXCEPT the "verbosity" axis, which varies
# verbose_level itself (one child per level, still file mode, so log size and
# runtime are measured as a function of verbose level).
#
# `clients_fixed_total`       spatial spread at constant offered load (the
#                             current semantics: one arrival stream for the
#                             whole population, NUM_CLIENTS is not a load knob).
# `clients_fixed_per_client`  clients as a genuine load axis: arrival_lambda =
#                             base*5/N, so total offered load scales with N.
# `arrival_sweep`             load axis at fixed spatial spread: for each N in
#                             {2,5,10,20}, sweep arrival_lambda across
#                             {1.6,0.8,0.4,0.2,0.1} so offered load % covers
#                             25%..400%. Orthogonal to clients_fixed_total
#                             (fix λ, var N) and clients_fixed_per_client
#                             (var N with λ=2/N). Together the three form a
#                             full N×λ 2-D scan via three 1-D slices.
# `session_length`            concurrent flows per server (SESSION_SIZE_LAMBDA).
# `load_curve`                the load response at each scale: for each total
#                             capacity T, sweep offered load 30..150% via
#                             arrival_lambda = 100/(load*T) s. The 90% row IS
#                             the capacity_90 operating point, so the two axes
#                             share those four cells (independent repeats).
# `capacity_90`               the scaling curve at constant 90% offered load:
#                             total_slots T in {100,250,1000,5000} with lambda
#                             co-varied as 100/(0.9*T). total_slots is TOTAL
#                             network capacity, not per-server (measure_one
#                             resolves slots = total // num_servers; 5 servers
#                             here, so every level divides evenly). A per-server
#                             slots sweep at fixed lambda would vary the
#                             offered load as well.
# `duration`                  linearity in SIM_DURATION (calibration: 2.03x for 2x).
# `verbosity`                 log-size multiplier, and logging's share of runtime.
# `change_factor`             announcement volume as a log-size driver
#                             (server_cf and router_cf move together).
# `prop_delay`                delay's effect on in-flight message count.
# `hop_by_hop`                the second forwarding mode, absent from the first draft.
OFAT_AXES = {
    "clients_fixed_total":       [{"num_clients": n} for n in (2, 5, 10, 20, 40)],
    "clients_fixed_per_client":  [{"num_clients": n,
                                   "arrival_lambda": round(0.4 * 5 / n, 6)}
                                  for n in (2, 5, 10, 20, 40)],
    "arrival_sweep":             [{"num_clients": n, "arrival_lambda": lam}
                                  for n in (2, 5, 10, 20)
                                  for lam in (1.6, 0.8, 0.4, 0.2, 0.1)],
    "session_length":            [{"session_lambda": lam} for lam in (2.5, 5, 10, 20, 40)],
    "load_curve":                [{"total_slots": T,
                                   "arrival_lambda": round(100.0 / (load * T), 6)}
                                  for T in (100, 250, 1000, 5000)
                                  for load in (0.30, 0.45, 0.60, 0.75, 0.90, 1.20, 1.50)],
    "capacity_90":               [{"total_slots": T,
                                   "arrival_lambda": round(100.0 / (0.90 * T), 6)}
                                  for T in (100, 250, 1000, 5000)],
    "duration":                  [{"sim_duration": d} for d in (90, 180, 360, 720, 1440)],
    "verbosity":                 [{"verbose_level": v} for v in (-1, 0, 1, 2, 3)],
    "change_factor":             [{"server_cf": s, "router_cf": s} for s in (0.0, 0.1, 0.2, 0.3)],
    "prop_delay":                [{"prop_delay": d} for d in (0.1, 1.0, 4.0)],
    "hop_by_hop":                [{"hop_by_hop": hb} for hb in (False, True)],
}
OFAT_REPEATS = 3

# --- Group C: confirmation points --------------------------------------------
#
# Combined-high settings not in the factorial. Used in the analysis to compare
# PREDICTED vs MEASURED cost -- the test of whether the per-axis fits compose.
# Each runs at log_mode "file", verbose 1, CONFIRMATION_REPEATS times.
CONFIRMATION_CONFIGS = [
    {"topology": "Cogentco", "num_servers": 20, "num_clients": 40,
     "arrival_lambda": 0.2, "sim_duration": 720},
    {"topology": "Cogentco", "num_servers": 20, "num_clients": 40,
     "arrival_lambda": 0.2, "sim_duration": 1440},
    {"topology": "Dfn", "num_servers": 20, "num_clients": 40,
     "arrival_lambda": 0.2, "sim_duration": 720},
    {"topology": "Cogentco", "num_servers": 10, "num_clients": 20,
     "arrival_lambda": 0.8, "sim_duration": 720},
]
CONFIRMATION_REPEATS = 3

# --- Group D: noise floor ----------------------------------------------------
#
# The baseline repeated NOISE_FLOOR_REPEATS times. A tight estimate of
# run-to-run variance: the calibration measured ~25% spread on one heavy
# config, and every fitted exponent is only meaningful relative to this number.
# File mode, verbose 1.
NOISE_FLOOR_REPEATS = 10

# --- Orchestration -----------------------------------------------------------
#
# Per-run subprocess timeout (seconds). The heaviest constructible config
# finishes in well under 10 s, but confirmation point 2 (Cogentco 20/40, 1440
# sim-s) and the verbosity-3 axis are beyond the calibration range, so the
# default leaves a wide margin. One runaway cell is recorded as status=timeout
# rather than stalling the matrix.
DEFAULT_TIMEOUT = 900

# Verbose levels for the factorial's paired file/null runs.
FACTORIAL_FILE_VERBOSE = 1
FACTORIAL_NULL_VERBOSE = -1

# --- END of constants --------------------------------------------------------

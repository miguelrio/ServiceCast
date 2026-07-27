"""Legacy monkey-patch collector for the change-factor matrix.

The default collector is now the pure-log one (`run_simulation_sweep_log.py`),
which derives every metric from the simulation's own log text. This probe build
is kept as the independent cross-check (`validate_log_vs_probe.py`) and as the
home of the shared pieces both builds use: `build_network`, `_configure_globals`,
`summarise_records`, and the experiment constants.
"""

import os
import sys
import json
import subprocess
from contextlib import contextmanager, ExitStack
from datetime import datetime
from typing import NamedTuple
import numpy as np
import simpy

# Ensure project path is in sys.path
project_path = os.path.dirname(os.path.abspath(__file__))
if project_path not in sys.path:
    sys.path.insert(0, project_path)

import Router as RouterModule
from tinydb.storages import MemoryStorage
import tinydb

class InMemoryTinyDB(tinydb.TinyDB):
    def __init__(self, *args, **kwargs):
        # Force MemoryStorage and discard the path argument since MemoryStorage is purely in-memory
        super().__init__(storage=MemoryStorage)

# Monkeypatch Router module's TinyDB to be in-memory
RouterModule.TinyDB = InMemoryTinyDB

from Graph import Graph
from Network import Network
from Server import Server
from Router import Router
from Generator import Generator
from Verbose import Verbose
from Utility import Utility
from Link import LinkEnd
from Gml import read_gml


# --- Fixed experiment constants -------------------------------------------------
# These define the scenario every sweep cell shares; only the swept axes
# (server_cf, router_cf, propagation_delay) vary between runs.
SIM_DURATION = 3600           # simulated seconds per run
ALPHA = 0.50                  # Utility load/delay weighting
SLOTS = 50                    # server capacity
SEED = 15112022               # shared RNG seed for reproducibility
SERVICE = "§a"                # the single service every client requests

NUM_SERVERS = 5               # servers attached to core nodes
NUM_CLIENTS = 5               # clients attached to local nodes

SERVER_LOAD_LAMBDA = 55       # background-load inter-arrival; INERT here: we pass
                              # background_load=False, and Generator.py:216 (the only
                              # line that reads it) is commented out, so it has no effect
CLIENT_ARRIVAL_LAMBDA = 5     # mean inter-arrival time (s) between client requests
SESSION_SIZE_LAMBDA = 10      # mean session length (s)
SESSION_SIZE_SCALE = 10       # session-length multiplier (effective session ~= lambda*scale)

# Metric fields, in output order. Drives both the per-cell accumulation and the
# JSON keys (matrix_<field>), so the seven metrics are named in exactly one place.
METRIC_FIELDS = ["created", "hops", "accuracy",
                 "mean_err_all", "mean_err_subopt", "max_err", "fib_updates",
                 "blocked_rate", "accuracy_arrival", "mean_err_arrival",
                 "hops_announce", "hops_withdraw"]

# Swept axes, shared so the log-based collector samples the identical grid.
# Ranges trimmed to the region where the metrics actually vary for this
# configuration (Dfn topology, Server.slots=50, this request distribution).
# Past Server.change_factor=0.32 no server ever clears its announcement
# threshold (max observed |Δload| ~0.32 = ~16/50 slots), and past
# Router.fib_utility_update_threshold=0.16 no replica's utility gap is ever
# large enough to switch the FIB (U=1-0.5*load-0.5*delay on a compact graph),
# so the upper ~two-thirds of the original axes were a flat dead zone.
SERVER_CFS = [0.0, 0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.14, 0.16, 0.18, 0.20, 0.22, 0.24, 0.26, 0.28, 0.30, 0.32, 0.34]
ROUTER_CFS = [0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.11, 0.12, 0.13, 0.14, 0.15, 0.16, 0.17, 0.18]


def current_git_commit():
    """Short hash of the code that produced the sweep data, for cache provenance."""
    try:
        result = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                cwd=project_path, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except Exception:
        return "unknown"


@contextmanager
def patched(obj, attr_name, replacement):
    """Temporarily replace obj.attr_name, restoring it even if the body raises."""
    original = getattr(obj, attr_name)
    setattr(obj, attr_name, replacement)
    try:
        yield
    finally:
        setattr(obj, attr_name, original)


class ExperimentResult(NamedTuple):
    """The raw measurements collected from a single simulation run."""
    created: int          # unique ServerMetric packets originated at servers
    hops: int             # total ServerMetric packets transmitted (hop count)
    records: list         # (selected_sel, best_sel, selected_arr, best_arr) per served request
    fib_updates: int      # genuine SERVICE_FIB updates across all routers (churn)
    blocked: int          # client requests dropped at a full replica (no capacity)
    hops_announce: int    # ServerMetric announcement (A) hops transmitted
    hops_withdraw: int    # ServerMetric withdrawal (W) hops transmitted


class RecordSummary(NamedTuple):
    """Selection quality derived from a run's per-request utility records."""
    accuracy: float          # % of requests that picked the optimal replica (selection time)
    mean_err_all: float      # mean |optimal - selected| utility over all requests
    mean_err_subopt: float   # mean error over suboptimal requests only
    max_err: float           # worst-case error
    accuracy_arrival: float  # % optimal judged by live state at arrival time
    mean_err_arrival: float  # mean |optimal - selected| utility judged at arrival time


def summarise_records(records):
    """Reduce per-request utility records to accuracy/error statistics.

    Each record is (selected_sel, best_sel, selected_arr, best_arr): the selected
    and best utilities at selection time and at arrival time. Selection-time stats
    measure the routing decision; arrival-time stats measure how good the pick
    looks once propagation delay has passed (decision staleness).
    """
    if not records:
        return RecordSummary(accuracy=100.0, mean_err_all=0.0, mean_err_subopt=0.0,
                             max_err=0.0, accuracy_arrival=100.0, mean_err_arrival=0.0)

    errors = [abs(best - sel) for sel, best, _, _ in records]
    arrival_errors = [abs(best - sel) for _, _, sel, best in records]

    subopt = [e for e in errors if e >= 1e-9]
    correct = sum(1 for e in errors if e < 1e-9)
    correct_arrival = sum(1 for e in arrival_errors if e < 1e-9)
    return RecordSummary(
        accuracy=correct / len(errors) * 100.0,
        mean_err_all=float(np.mean(errors)),
        mean_err_subopt=float(np.mean(subopt)) if subopt else 0.0,
        max_err=float(np.max(errors)),
        accuracy_arrival=correct_arrival / len(arrival_errors) * 100.0,
        mean_err_arrival=float(np.mean(arrival_errors)),
    )


class SimulationProbes:
    """Measurement wrappers installed around a simulation run, restored on exit.

    Each wrapper only records a measurement and then delegates to the original, so
    simulation behaviour is unchanged. After the `with` block these attributes hold
    the collected values:
      created       - unique ServerMetric packets originated at the servers
      hops          - total ServerMetric packets transmitted across all LinkEnds
      hops_announce - ServerMetric announcement (A) hops transmitted
      hops_withdraw - ServerMetric withdrawal (W) hops transmitted
      blocked       - client requests dropped at a full replica (no capacity)
      records       - list of (selected_sel, best_sel, selected_arr, best_arr) per served request
    """

    def __init__(self):
        self.created = 0
        self.hops = 0
        self.hops_announce = 0
        self.hops_withdraw = 0
        self.blocked = 0
        self.records = []
        self._stack = ExitStack()

    def __enter__(self):
        probe = self

        # Count ServerMetric transmissions (hops) at every LinkEnd, split by the
        # message type carried on packet.operation ('A' announce / 'W' withdraw).
        original_put = LinkEnd.put
        def counting_put(self, packet):
            if getattr(packet, 'type', None) == "ServerMetric":
                probe.hops += 1
                op = getattr(packet, 'operation', None)
                if op == 'A':
                    probe.hops_announce += 1
                elif op == 'W':
                    probe.hops_withdraw += 1
            return original_put(self, packet)

        # Count unique metric updates created at the servers
        original_send_load_packet = Server.send_load_packet
        def counting_send_load_packet(self, time, service_name):
            probe.created += 1
            return original_send_load_packet(self, time, service_name)

        # Record per-request utilities (selection- and arrival-time) per request.
        # The simulator passes a `status` dict for blocked requests (no capacity).
        original_best_replica_utility = Network.best_replica_utility
        def recording_best_replica_utility(self, requesting_server, packet, status=None):
            probe._record_utilities(self, requesting_server, packet, status)
            return original_best_replica_utility(self, requesting_server, packet, status)

        self._stack.enter_context(patched(LinkEnd, 'put', counting_put))
        self._stack.enter_context(patched(Server, 'send_load_packet', counting_send_load_packet))
        self._stack.enter_context(patched(Network, 'best_replica_utility', recording_best_replica_utility))
        return self

    def __exit__(self, *exc):
        return self._stack.__exit__(*exc)

    def _record_utilities(self, network, requesting_server, packet, status=None):
        """Capture per-request utilities the way the Network would.

        Records a 4-tuple per *served* request: the selected and best utilities
        both at selection time (from the optimal_snapshot, if any) and at arrival
        time (from live replica state). Blocked requests (status set) are counted
        separately and excluded from the records, so they do not skew accuracy or
        error statistics.
        """
        if status is not None:
            # Request reached a replica with no free capacity and was dropped.
            self.blocked += 1
            return

        client_name = packet.src
        requesting_server_id = requesting_server.id()

        # Live utilities for every replica, computed at arrival as the Network does.
        utility_values = {}
        for server in (r for r in network.network_nodes() if isinstance(r, Server)):
            load = server.calculate_load()
            latency = network.latency_table[server.id()][client_name]
            normalised_delay = network.get_normalised_delay(latency)
            utility_values[server.id()] = Utility.eval_forwarding_utility(
                Utility.alpha, load, latency, normalised_delay)

        selected_arr = utility_values.get(requesting_server_id, 0)
        best_arr = max(utility_values.values()) if utility_values else 0

        if hasattr(packet, 'optimal_snapshot'):
            snapshot = packet.optimal_snapshot
            selected_sel = snapshot['all_utilities'].get(requesting_server_id, 0)
            best_sel = snapshot['utility']
        else:
            # No FIB decision recorded: selection state is the same live state.
            selected_sel = selected_arr
            best_sel = best_arr

        self.records.append((selected_sel, best_sel, selected_arr, best_arr))


def _configure_globals(server_cf, router_cf, hop_by_hop, propagation_delay):
    """Set the global knobs that define a single experiment. Verbose output is silenced."""
    Verbose.level = -1
    Verbose.table = 0

    Router.hop_by_hop = hop_by_hop
    Graph.default_propagation_delay = propagation_delay
    Utility.alpha = ALPHA
    Server.slots = SLOTS
    Server.change_factor = server_cf
    Router.fib_utility_update_threshold = router_cf


def build_network(env, propagation_delay):
    """Build the Dfn network ready to run: graph -> network, attach servers and clients,
    pre-compute forwarding tables, and install the load/request generators."""
    gml_file = os.path.join(project_path, "gml/Dfn.gml")
    network = Network.from_graph(read_gml(gml_file), env)

    # Core nodes (degree > 3) host servers; local nodes (degree <= 3) host clients.
    core = [r for r in network.network_nodes() if r.degree() > 3]
    local = [r for r in network.network_nodes() if r.degree() <= 3]

    servers = [f"s{s}" for s in range(1, NUM_SERVERS + 1)]
    for s, name in enumerate(servers, start=1):
        network.add_server(name, core[s], propagation_delay)

    clients = [f"c{c}" for c in range(1, NUM_CLIENTS + 1)]
    for c, name in enumerate(clients, start=1):
        network.add_client(name, local[c], propagation_delay)

    network.calculate_forwarding_tables()

    for name in servers:
        Generator.server_load_event_generator(
            network, name, [SERVICE], exponential_lambda=SERVER_LOAD_LAMBDA,
            seed=SEED, background_load=False)
    Generator.multi_client_event_generator(
        network, clients, SERVICE, arrival_lambda=CLIENT_ARRIVAL_LAMBDA,
        size_lambda=SESSION_SIZE_LAMBDA, size_scale_factor=SESSION_SIZE_SCALE, seed=SEED)

    return network


def _close_router_dbs(network):
    """Close router DBs to release file descriptors (avoids 'Too many open files')."""
    for router in network.routers.values():
        if getattr(router, 'db', None):
            router.db.close()


def run_single_experiment(server_cf, router_cf, hop_by_hop=False, propagation_delay=0.1):
    """Run one SIM_DURATION-second simulation for the given parameters.

    Returns an ExperimentResult of raw measurements (see summarise_records for the
    derived selection-quality statistics).
    """
    _configure_globals(server_cf, router_cf, hop_by_hop, propagation_delay)

    env = simpy.Environment()
    network = build_network(env, propagation_delay)

    # Run with the observation wrappers installed; the context manager guarantees
    # the originals are restored afterwards even if the run raises.
    with SimulationProbes() as probes:
        network.start(until=SIM_DURATION)

    fib_updates = sum(getattr(r, 'service_fib_updates', 0) for r in network.routers.values())
    _close_router_dbs(network)

    return ExperimentResult(probes.created, probes.hops, probes.records, fib_updates,
                            probes.blocked, probes.hops_announce, probes.hops_withdraw)


def run_sweep(hop_by_hop, output_path=None, delays=(0.1, 0.5, 1.0, 2.0, 4.0)):
    """
    Runs the full parameter sweep and saves/returns the matrix data.

    The sweep spans three axes: Server.change_factor (columns),
    Router.fib_utility_update_threshold (rows), and Graph.default_propagation_delay
    (the `delays` list). Each matrix_* result is 3D, indexed [delay][router_cf][server_cf].
    """
    # Swept columns/rows (see SERVER_CFS / ROUTER_CFS at module level).
    server_cfs = SERVER_CFS
    router_cfs = ROUTER_CFS

    delays = list(delays)

    mode_title = "Hop-by-Hop Anycast" if hop_by_hop else "First Decide Unicast"

    print(f"Starting sweep ({mode_title}): "
          f"{len(delays)} delays x {len(server_cfs)} columns x {len(router_cfs)} rows "
          f"= {len(delays) * len(server_cfs) * len(router_cfs)} simulations...")

    # One 3D array per metric, indexed [delay][router_cf][server_cf].
    shape = (len(delays), len(router_cfs), len(server_cfs))
    matrices = {name: np.zeros(shape) for name in METRIC_FIELDS}

    for k, delay in enumerate(delays):
        print(f"\n=== Propagation delay {delay} ({k + 1}/{len(delays)}) ===")
        for i, r_cf in enumerate(router_cfs):
            for j, s_cf in enumerate(server_cfs):
                result = run_single_experiment(
                    s_cf, r_cf, hop_by_hop, propagation_delay=delay)
                summary = summarise_records(result.records)

                blocked_rate = result.blocked / max(1, result.blocked + len(result.records)) * 100.0
                cell = {"created": result.created, "hops": result.hops,
                        "fib_updates": result.fib_updates,
                        "blocked_rate": blocked_rate,
                        "hops_announce": result.hops_announce,
                        "hops_withdraw": result.hops_withdraw,
                        **summary._asdict()}
                for name in METRIC_FIELDS:
                    matrices[name][k, i, j] = cell[name]

                print(f"Delay: {delay}, CF Server: {s_cf:.2f}, CF Router: {r_cf:.3f} => "
                      f"Created: {result.created}, Hops: {result.hops} "
                      f"(A:{result.hops_announce} W:{result.hops_withdraw}), "
                      f"Acc: {summary.accuracy:.1f}%, Blocked: {blocked_rate:.1f}%, "
                      f"FIB updates: {result.fib_updates}")

    data = {
        "code_commit": current_git_commit(),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "probe",
        "hop_by_hop": hop_by_hop,
        "delays": delays,
        "server_cfs": server_cfs,
        "router_cfs": router_cfs,
        **{f"matrix_{name}": matrices[name].tolist() for name in METRIC_FIELDS},
    }

    if output_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"Sweep results saved to: {output_path}")

    return data

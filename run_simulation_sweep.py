import os
import sys
import json
import subprocess
from contextlib import contextmanager
from datetime import datetime
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

from Network import Network
from Server import Server
from Router import Router
from Generator import Generator
from Verbose import Verbose
from Utility import Utility, Place
from Link import LinkEnd
from gml import read_gml


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


def run_single_experiment(server_cf, router_cf, hop_by_hop=False, oracle_timing="router"):
    """
    Runs a single simulation run for 3600s with the given change factors.
    Returns:
      - unique_metric_created: unique ServerMetric packets originated at servers
      - server_metric_count: total ServerMetric packets transmitted (hops)
      - utility_records: list of tuples (selected_utility, optimal_utility) for each client request
    """
    # Suppress verbose prints
    Verbose.level = -1
    Verbose.table = 0
    
    # Configure parameters
    Router.hop_by_hop = hop_by_hop
    if isinstance(oracle_timing, str):
        oracle_timing = Place[oracle_timing.capitalize()]
    Network.optimal_utility_timing = oracle_timing
    Utility.alpha = 0.50
    Server.slots = 50
    Server.change_factor = server_cf
    Router.fib_utility_update_threshold = router_cf

    # Set up SimPy environment
    env = simpy.Environment()
    gml_file = os.path.join(project_path, "gml/Dfn.gml")
    graph = read_gml(gml_file)
    network = Network.from_graph(graph, env)
    
    core = [r for r in network.network_nodes() if r.degree() > 3]
    local = [r for r in network.network_nodes() if r.degree() <= 3]

    # Add servers and clients
    servers = []
    for s in range(1, 6):
        name = f"s{s}"
        servers.append(name)
        network.add_server(name, core[s])

    clients = []
    for c in range(1, 6):
        name = f"c{c}"
        clients.append(name)
        network.add_client(name, local[c])

    # Pre-calculate routing/forwarding tables
    network.calculate_forwarding_tables()

    # Add load event generators (servers) and client event generators
    for server_name in servers:
        Generator.server_load_event_generator(network, server_name, ["§a"], exponential_lambda=55, seed=15112022, background_load=False)
    
    Generator.multi_client_event_generator(network, clients, "§a", arrival_lambda=5, size_lambda=10, size_scale_factor=10, seed=15112022)

    # The simulation is observed through three wrappers, installed below with
    # patched(). Each one only records a measurement and then delegates to the
    # original, so simulation behaviour is unchanged.

    # Count ServerMetric transmissions (hops) at every LinkEnd
    original_put = LinkEnd.put
    server_metric_count = 0

    def counting_put(self, packet):
        nonlocal server_metric_count
        if getattr(packet, 'type', None) == "ServerMetric":
            server_metric_count += 1
        return original_put(self, packet)

    # Count unique metric updates created at the servers
    original_send_load_packet = Server.send_load_packet
    unique_metric_created = 0

    def counting_send_load_packet(self, time, service_name):
        nonlocal unique_metric_created
        unique_metric_created += 1
        return original_send_load_packet(self, time, service_name)

    # Record (selected_utility, optimal_utility) per client request
    original_best_replica_utility = Network.best_replica_utility
    utility_records = []

    def recording_best_replica_utility(self, requesting_server, packet):
        client_name = packet.src
        requesting_server_id = requesting_server.id()

        # Re-determine selected_utility and best_utility as printed by the Network object
        if hasattr(packet, 'optimal_snapshot'):
            snapshot = packet.optimal_snapshot
            selected_utility = snapshot['all_utilities'].get(requesting_server_id, 0)
            best_utility = snapshot['utility']
        else:
            # Compute current utilities
            servers_list = [r for r in self.network_nodes() if isinstance(r, Server)]
            utility_values = {}
            for server in servers_list:
                load = server.calculate_load()
                latency = self.latency_table[server.id()][client_name]
                normalised_delay = self.get_normalised_delay(latency)
                utility = Utility.eval_forwarding_utility(Utility.alpha, load, latency, normalised_delay)
                utility_values[server.id()] = utility
            
            selected_utility = utility_values.get(requesting_server_id, 0)
            best_utility = max(utility_values.values()) if utility_values else 0
        
        utility_records.append((selected_utility, best_utility))
        return original_best_replica_utility(self, requesting_server, packet)

    # Run the simulation with the observation wrappers installed;
    # patched() guarantees the originals are restored afterwards
    with patched(LinkEnd, 'put', counting_put), \
         patched(Server, 'send_load_packet', counting_send_load_packet), \
         patched(Network, 'best_replica_utility', recording_best_replica_utility):
        network.start(until=3600)

    # Close databases to release file descriptors and prevent "Too many open files" errors
    for router in network.routers.values():
        if hasattr(router, 'db') and router.db:
            router.db.close()

    return unique_metric_created, server_metric_count, utility_records

def run_sweep(hop_by_hop, oracle_timing, output_path=None):
    """
    Runs the full parameter sweep and saves/returns the matrix data.
    """
    server_cfs = [0.0, 0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.14, 0.16, 0.18, 0.20,0.22,0.24,0.26]
    router_cfs = [0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10,0.11,0.12,0.13] 

    oracle_timing_enum = oracle_timing if isinstance(oracle_timing, Place) else Place[oracle_timing.capitalize()]
    timing_str = oracle_timing_enum.name.lower()

    mode_title = "Hop-by-Hop Anycast" if hop_by_hop else "First Decide Unicast"
    timing_title = f"Oracle: {timing_str.capitalize()}"

    print(f"Starting sweep ({mode_title}, {timing_title}): {len(server_cfs)} columns x {len(router_cfs)} rows...")

    matrix_created = np.zeros((len(router_cfs), len(server_cfs)))
    matrix_hops = np.zeros((len(router_cfs), len(server_cfs)))
    matrix_accuracy = np.zeros((len(router_cfs), len(server_cfs)))
    matrix_mean_err_all = np.zeros((len(router_cfs), len(server_cfs)))
    matrix_mean_err_subopt = np.zeros((len(router_cfs), len(server_cfs)))
    matrix_max_err = np.zeros((len(router_cfs), len(server_cfs)))

    for i, r_cf in enumerate(router_cfs):
        for j, s_cf in enumerate(server_cfs):
            created_count, hop_count, records = run_single_experiment(s_cf, r_cf, hop_by_hop, oracle_timing_enum)
            
            matrix_created[i, j] = created_count
            matrix_hops[i, j] = hop_count
            
            # Compute selection errors
            errors = [abs(best - sel) for sel, best in records]
            subopt_errors = [err for err in errors if err >= 1e-9]
            
            correct_selections = sum(1 for err in errors if err < 1e-9)
            accuracy = (correct_selections / len(errors) * 100.0) if errors else 100.0
            matrix_accuracy[i, j] = accuracy
            
            mean_err = np.mean(errors) if errors else 0.0
            matrix_mean_err_all[i, j] = mean_err
            
            mean_err_subopt = np.mean(subopt_errors) if subopt_errors else 0.0
            matrix_mean_err_subopt[i, j] = mean_err_subopt
            
            max_err = np.max(errors) if errors else 0.0
            matrix_max_err[i, j] = max_err
            
            print(f"CF Server: {s_cf:.2f}, CF Router: {r_cf:.3f} => Created: {created_count}, Hops: {hop_count}, Acc: {accuracy:.1f}%")

    data = {
        "code_commit": current_git_commit(),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "hop_by_hop": hop_by_hop,
        "oracle_timing": timing_str,
        "server_cfs": server_cfs,
        "router_cfs": router_cfs,
        "matrix_created": matrix_created.tolist(),
        "matrix_hops": matrix_hops.tolist(),
        "matrix_accuracy": matrix_accuracy.tolist(),
        "matrix_mean_err_all": matrix_mean_err_all.tolist(),
        "matrix_mean_err_subopt": matrix_mean_err_subopt.tolist(),
        "matrix_max_err": matrix_max_err.tolist()
    }

    if output_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"Sweep results saved to: {output_path}")

    return data

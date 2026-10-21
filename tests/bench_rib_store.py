#!/usr/bin/env python3
"""Benchmark: A/B comparison of two Router versions -- by default the
original TinyDB-based tables (src/Router-old.py, "old") vs the current
plain-dict tables (src/Router.py, "new"). --old-file / --new-file pick any
two versions in src/, e.g. a version before and after an optimisation.

Both versions are loaded straight from their own files by importlib.

Part A (always runs): microbenchmark driving the real Router storage paths --
RIB insert/update, sent_table check/add/clear, decide_announcements,
delete_rib_entry -- for R replicas x D neighbours. Reports wall time per
phase and tracemalloc peak per backend, and verifies both backends agree on
the final state.

Part B (--fullsim): full-simulation A/B. Each run is a fresh subprocess
(this script with --fullsim-worker) for clean per-process peak-RSS.
  * Timing: --repeats uninstrumented runs per backend, interleaved
    (old, new, old, new, ...); the median wall time and peak RSS are
    reported.
  * Equivalence: one extra instrumented run per backend records
      - every client request reaching a server, in order, and whether it
        was accepted or blocked
      - per-router counts of packets sent, by type and operation (A/W)
      - SHA-256 digests of the stream of every packet any router sent
        (time, router, neighbour, type, op, replica, payload, ...): one
        that ignores order among packets one router sends at one instant
        (pass/fail), and one in strict order (reported as a NOTE if only
        it differs -- e.g. two withdrawals from one step sent in a
        different order)
      - final per-router service FIB, FIB update count, RIB, sent table
        and pkt_no, and per-client pkt_no
    and the parent compares them all.
  * Logs (--logs DIR): one more run per backend at --log-level, stdout
    saved to DIR/old.log and DIR/new.log, then
    scripts/check-tinydb-dict-logs.py is run on the pair.

Usage:
    python3 tests/bench_rib_store.py                 # Part A only
    python3 tests/bench_rib_store.py --fullsim       # Part A + Part B
    python3 tests/bench_rib_store.py --fullsim --until 120 --repeats 5
    python3 tests/bench_rib_store.py --fullsim --logs logs/ab
    python3 tests/bench_rib_store.py --fullsim --skip-part-a --gml <file>
    python3 tests/bench_rib_store.py --fullsim --skip-part-a \
        --gml topologies/gml/Dfn.gml --servers 5 --clients 5 --until 300
    python3 tests/bench_rib_store.py --old-file Router-before.py \
        --new-file Router.py --fullsim ...

Notes:
- A TinyDB-based version needs tinydb installed.
- Network.py builds routers from its module-global `Router`; the worker
  swaps that for the selected backend's class.
- Part A's storage speedup leaves out decide_announcements, which is
  reported separately.
"""

import argparse
import collections
import hashlib
import importlib.util
import json
import os
import random
import resource
import statistics
import subprocess
import sys
import time
import tempfile
import tracemalloc

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO_ROOT, "src")
sys.path.insert(0, SRC)

DEFAULT_GML = os.path.join(
    REPO_ROOT, "topologies/synthetic/topology_synthetic_1788876186136.gml")
SEED = 15112022

import simpy  # noqa: E402

from Verbose import Verbose  # noqa: E402

# Silence the simulator's own prints during benchmarking.
Verbose.level = -1
Verbose.table = 0


def load_router_module(filename, modname):
    """Load a Router variant from src/<filename> (the hyphen in the file
    names prevents a normal import)."""
    spec = importlib.util.spec_from_file_location(
        modname, os.path.join(SRC, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --old-file / --new-file choose the two Router versions compared. They are
# needed before argparse runs (the modules load at import), so pre-parse them.
_pre = argparse.ArgumentParser(add_help=False)
_pre.add_argument('--old-file', default='Router-old.py')
_pre.add_argument('--new-file', default='Router.py')
_files, _ = _pre.parse_known_args()
OLD_FILE, NEW_FILE = _files.old_file, _files.new_file

old_router_mod = load_router_module(OLD_FILE, "Router_old")
new_router_mod = load_router_module(NEW_FILE, "Router_new")


# --------------------------------------------------------------------------
# Part A -- microbenchmark
# --------------------------------------------------------------------------

def make_doc(replica, neighbour, t, load, delay):
    return {'replica': replica, 'neighbour': neighbour,
            'link_end': 'le-' + neighbour, 'msgID': 1,
            'servicename': '§a', 'creationTime': t,
            'load': load, 'no_of_flows': int(load * 10),
            'delay': delay, 'slots': 50}


class TinyDBAdapter:
    """Storage primitives replicating the exact TinyDB calls the old
    Router code makes inline (RIB insert/search/update are not factored
    into methods in the old implementation)."""
    kind = "tinydb"

    @staticmethod
    def rib_insert(r, doc):
        r.service_RIB.insert(doc)

    @staticmethod
    def rib_get(r, replica):
        from tinydb import Query
        q = Query()
        res = r.service_RIB.search(q.replica == replica)
        return res[0] if res else None

    @staticmethod
    def rib_update(r, replica, fields):
        from tinydb import Query
        q = Query()
        docs = r.service_RIB.search(q.replica == replica)
        r.service_RIB.update(fields, doc_ids=[d.doc_id for d in docs])

    @staticmethod
    def rib_all(r):
        return r.service_RIB.all()

    @staticmethod
    def sent_key(doc):
        return doc.doc_id

    @staticmethod
    def sent_state(r):
        # {replica: set(neighbours)}; metric_doc_id -> replica via the RIB
        id2rep = {d.doc_id: d['replica'] for d in r.service_RIB.all()}
        state = {}
        for entry in r.sent_table:
            rep = id2rep.get(entry['metric_doc_id'])
            if rep is not None:
                state.setdefault(rep, set()).add(entry['neighbour'])
        return state


class DictAdapter:
    kind = "dict"

    @staticmethod
    def rib_insert(r, doc):
        r.service_RIB[doc['replica']] = doc

    @staticmethod
    def rib_get(r, replica):
        return r.service_RIB.get(replica)

    @staticmethod
    def rib_update(r, replica, fields):
        r.service_RIB[replica].update(fields)

    @staticmethod
    def rib_all(r):
        return list(r.service_RIB.values())

    @staticmethod
    def sent_key(doc):
        return doc['replica']

    @staticmethod
    def sent_state(r):
        return {rep: set(ns) for rep, ns in r.sent_table.items()}


def adapter_for(module):
    """TinyDB-backed Router modules import TinyDB; the rest use dicts."""
    return TinyDBAdapter if hasattr(module, 'TinyDB') else DictAdapter


# the two versions compared, in the order they are reported
BACKENDS = {'old': (old_router_mod, adapter_for(old_router_mod)),
            'new': (new_router_mod, adapter_for(new_router_mod))}


def describe_backends():
    return (f"old = {OLD_FILE} ({BACKENDS['old'][1].kind}), "
            f"new = {NEW_FILE} ({BACKENDS['new'][1].kind})")


def drive_backend(module, adapter, R, D, update_rounds, withdraw_frac, seed):
    """Drive one backend through the announce/update/withdraw storage
    workload. Returns (phase_times, router)."""
    env = simpy.Environment()
    router = module.Router("hub", env)
    rng = random.Random(seed)
    replicas = [f"s{i}" for i in range(R)]
    neighbours = [f"n{i}" for i in range(D)]
    times = {}

    # Phase 1: populate the RIB (one entry per replica, as the announce
    # handler does on first sight of a replica)
    t0 = time.perf_counter()
    for i, rep in enumerate(replicas):
        adapter.rib_insert(router, make_doc(rep, rng.choice(neighbours),
                                            0.0, 0.1 * i, 1.0 + i))
    times['rib_insert'] = time.perf_counter() - t0

    # Phase 2: update rounds. Each round: one replica's metrics drift
    # (RIB search + update), then the announce fan-out over all D
    # neighbours (check_sent_table + update_sent_table per neighbour),
    # then the Pareto decision over the whole RIB.
    t0 = time.perf_counter()
    for rnd in range(update_rounds):
        rep = replicas[rnd % R]
        fields = {'load': rng.random(), 'delay': 0.5 + rng.random() * 5,
                  'creationTime': float(rnd + 1), 'msgID': rnd + 1,
                  'no_of_flows': rng.randint(0, 50), 'slots': 50,
                  'neighbour': rng.choice(neighbours),
                  'link_end': 'le-x', 'servicename': '§a'}
        adapter.rib_update(router, rep, fields)
        doc = adapter.rib_get(router, rep)
        for n in neighbours:
            if not router.check_sent_table(doc, n):
                router.update_sent_table(doc, n)
    times['update_and_announce'] = time.perf_counter() - t0

    # Phase 3: Pareto announce decision over the full RIB
    t0 = time.perf_counter()
    entries = adapter.rib_all(router)
    for _ in range(update_rounds):
        router.decide_announcements(entries)
    times['decide_announcements'] = time.perf_counter() - t0

    # Phase 4: withdraw a fraction of the replicas
    # (clear_sent_table + delete_rib_entry per replica)
    t0 = time.perf_counter()
    n_withdraw = max(1, int(R * withdraw_frac))
    for rep in replicas[:n_withdraw]:
        doc = adapter.rib_get(router, rep)
        if doc is not None:
            router.clear_sent_table(adapter.sent_key(doc))
            router.delete_rib_entry(doc)
    times['withdraw'] = time.perf_counter() - t0

    times['total'] = sum(times.values())
    times['storage'] = times['total'] - times['decide_announcements']
    return times, router


def run_cell(module, adapter, R, D, update_rounds, seed):
    tracemalloc.start()
    try:
        times, router = drive_backend(module, adapter, R, D, update_rounds,
                                      0.25, seed)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    rib_state = {rep: dict(doc) for rep, doc in
                 ((d['replica'], d) for d in adapter.rib_all(router))}
    return times, peak, rib_state, adapter.sent_state(router)


def part_a(seed):
    print("=" * 78)
    print("Part A -- microbenchmark of Router storage paths")
    print(describe_backends())
    print("=" * 78)
    # (replicas R, degree D, update rounds)
    cells = [(5, 10, 200), (20, 100, 100), (20, 100, 30)]
    ok = True
    for R, D, rounds in cells:
        print(f"\nR={R} replicas, D={D} neighbours, {rounds} update rounds")
        header = f"{'backend':<8} {'insert':>9} {'upd+ann':>9} {'decide':>9} " \
                 f"{'withdraw':>9} {'total':>9} {'peak MB':>9}"
        print(header)
        print("-" * len(header))
        results = {}
        for name, (module, ad) in BACKENDS.items():
            times, peak, rib, sent = run_cell(module, ad, R, D, rounds, seed)
            results[name] = (times, peak, rib, sent)
            print(f"{name:<8} {times['rib_insert']:>9.4f} "
                  f"{times['update_and_announce']:>9.4f} "
                  f"{times['decide_announcements']:>9.4f} "
                  f"{times['withdraw']:>9.4f} {times['total']:>9.4f} "
                  f"{peak / 1e6:>9.3f}")
        speedup = results['old'][0]['storage'] / max(
            results['new'][0]['storage'], 1e-12)
        dspeed = results['old'][0]['decide_announcements'] / max(
            results['new'][0]['decide_announcements'], 1e-12)
        mem_ratio = results['old'][1] / max(results['new'][1], 1)
        print(f"--> new storage speedup x{speedup:.1f} (excl. decide), "
              f"decide speedup x{dspeed:.2f}, "
              f"old/new peak-memory ratio x{mem_ratio:.2f}")

        # correctness: both backends must agree on the final state
        old_rib = results['old'][2]
        new_rib = results['new'][2]
        old_sent = results['old'][3]
        new_sent = results['new'][3]
        if old_rib != new_rib or old_sent != new_sent:
            ok = False
            print("!! STATE MISMATCH between backends")
            if old_rib != new_rib:
                print("   RIB keys old:", sorted(old_rib),
                      " new:", sorted(new_rib))
            if old_sent != new_sent:
                print("   sent old:", old_sent, " new:", new_sent)
        else:
            print("    state check: identical RIB and sent_table")
    print("\nPart A:", "OK" if ok else "FAILED")
    return ok


# --------------------------------------------------------------------------
# Part B -- full-simulation A/B (subprocess per run)
# --------------------------------------------------------------------------

def _peak_rss_mb():
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes, Linux kilobytes
    return rss / 1e6 if sys.platform == 'darwin' else rss / 1e3


def _instrument(router_cls, server_cls):
    """Wrap the Router send path and the Server admission check to record
    what the simulation actually did. Returns the record dict, filled in as
    the simulation runs."""
    rec = {'sends': collections.Counter(), 'digest': hashlib.sha256(),
           'batch_digest': hashlib.sha256(), 'batch_key': None, 'batch': [],
           'n_sends': 0, 'requests': []}

    def flush_batch():
        # the batch digest sorts the packets one router sends at one instant,
        # so it ignores the order of sends within a single decision step
        # (pkt_no is left out: it is numbered in send order)
        for item in sorted(rec['batch']):
            rec['batch_digest'].update(item.encode())
        rec['batch'].clear()

    rec['flush_batch'] = flush_batch

    orig_send = router_cls.send_packet_to_neighbour

    def send_packet_to_neighbour(self, packet, neighbour):
        ptype = getattr(packet, 'type', None)
        op = getattr(packet, 'operation', None)
        rec['sends'][f"{self.id()}|{ptype}|{op}"] += 1
        rec['n_sends'] += 1
        payload = getattr(packet, 'payload', None)
        if isinstance(payload, dict):
            payload = sorted(payload.items())
        fields = (neighbour, ptype, op, getattr(packet, 'replica', None),
                  packet.src, packet.id, getattr(packet, 'msg_time', None),
                  payload)
        rec['digest'].update(repr((self.env.now, self.id(),
                                   getattr(packet, 'pkt_no', None))
                                  + fields).encode())
        key = (self.env.now, self.id())
        if key != rec['batch_key']:
            flush_batch()
            rec['batch_key'] = key
            rec['batch_digest'].update(repr(key).encode())
        rec['batch'].append(repr(fields))
        return orig_send(self, packet, neighbour)

    router_cls.send_packet_to_neighbour = send_packet_to_neighbour

    # can_increase_load is the accept/block decision for every client
    # request that reaches a server
    orig_can = server_cls.can_increase_load

    def can_increase_load(self, request):
        accepted = orig_can(self, request)
        rec['requests'].append(
            [self.env.now, self.id(), request.src, request.id, accepted])
        return accepted

    server_cls.can_increase_load = can_increase_load
    return rec


def attach_hosts(network, num_servers, num_clients):
    """Attach servers s1.. and clients c1.. to distinct local (degree <= 3)
    nodes, chosen with the same seeded sample as experiments/main_cog.py."""
    if not num_servers and not num_clients:
        return
    from Graph import Graph
    local = [r for r in network.network_nodes() if r.degree() <= 3]
    needed = num_servers + num_clients
    if len(local) < needed:
        sys.exit(f"Not enough local nodes: need {needed}, found {len(local)}")
    chosen = random.Random(SEED).sample(local, needed)
    for s, dest in enumerate(chosen[:num_servers], start=1):
        network.add_server("s" + str(s), dest, Graph.default_propagation_delay)
    for c, dest in enumerate(chosen[num_servers:], start=1):
        network.add_client("c" + str(c), dest, Graph.default_propagation_delay)


def fullsim_worker(backend, gml, until, mode, result_file, log_level,
                   hosts=(0, 0), hop_by_hop=False, weighted=False):
    """Run one full simulation with the selected Router backend and write a
    JSON result to result_file.

    mode: 'time'  -- uninstrumented, Verbose off (timing run)
          'check' -- instrumented, Verbose off (equivalence run)
          'log'   -- Verbose at log_level, stdout is the simulation log
    hosts: (num_servers, num_clients) to attach to local (degree <= 3)
           nodes, as experiments/main_cog.py does; (0, 0) uses only the
           hosts already in the GML
    hop_by_hop: Router.hop_by_hop -- hop-by-hop anycast forwarding of client
           requests (True) or first-decide unicast (False)
    weighted: engine Dijkstra over link weights instead of hop count, as
           experiments/main_precomputed_t1.py's "weighted" option does
           (ignored when the GML carries precomputed routing tables)
    """
    from Graph import Graph
    import Network as network_mod
    from Generator import Generator
    from Utility import Utility
    from Server import Server

    router_mod, adapter = BACKENDS[backend]
    router_cls = router_mod.Router
    # Network.py holds its own module-global reference; swap it
    network_mod.Router = router_cls

    router_cls.hop_by_hop = hop_by_hop
    router_cls.fib_utility_update_threshold = 0.001
    Graph.default_propagation_delay = 100   # ms (0.1 s), src/units.py
    Utility.alpha = 0.50
    Server.slots = 50
    Server.change_factor = 0.01

    if mode == 'log':
        Verbose.level = log_level

    rec = _instrument(router_cls, Server) if mode == 'check' else None

    env = simpy.Environment()
    graph = Graph.from_gml_file(gml)
    network = network_mod.Network.from_graph(graph, env, drop_external=False)
    attach_hosts(network, *hosts)
    if not network.server_names() or not network.client_names():
        sys.exit(f"{os.path.basename(gml)} has {len(network.server_names())} "
                 f"servers and {len(network.client_names())} clients; pass "
                 "--servers N --clients N to attach hosts to it")
    if weighted:
        orig_dijkstra = Graph.dijkstra_algorithm
        Graph.dijkstra_algorithm = classmethod(
            lambda cls, g, start, use_weights=False: orig_dijkstra(g, start,
                                                                   True))
    network.calculate_forwarding_tables()
    if weighted:
        Graph.dijkstra_algorithm = orig_dijkstra
    routing = ('precomputed' if network.precomputed_tables
               else 'engine weighted' if weighted else 'engine min-hop')

    for server_name in network.server_names():
        Generator.server_load_event_generator(network, server_name, ["§a"],
                                              seed=SEED, background_load=False)
    Generator.multi_client_event_generator(network, network.client_names(),
                                           "§a", arrival_lambda=0.4,
                                           size_lambda=10,
                                           size_scale_factor=10, seed=SEED)

    t0 = time.perf_counter()
    network.start(until=until)
    wall = time.perf_counter() - t0

    result = {'backend': backend, 'mode': mode, 'wall_s': wall,
              'peak_rss_mb': _peak_rss_mb(), 'routing': routing,
              'hop_by_hop': hop_by_hop}

    if mode == 'check':
        # network.routers also holds Server/Client (Host subclasses); only
        # real Router instances carry the service FIB
        routers = {rid: r for rid, r in network.routers.items()
                   if isinstance(r, router_cls)}
        result.update({
            'requests': rec['requests'],
            'sends': dict(rec['sends']),
            'n_sends': rec['n_sends'],
            'send_digest': rec['digest'].hexdigest(),
            'send_batch_digest': (rec['flush_batch'](),
                                  rec['batch_digest'].hexdigest())[1],
            'fib': {rid: r.service_FIB for rid, r in routers.items()},
            'fib_updates': {rid: r.service_fib_updates
                            for rid, r in routers.items()},
            'rib': {rid: {d['replica']: dict(d) for d in adapter.rib_all(r)}
                    for rid, r in routers.items()},
            'sent': {rid: {rep: sorted(ns) for rep, ns in
                           adapter.sent_state(r).items()}
                     for rid, r in routers.items()},
            'router_pkt_no': {rid: r.pkt_no for rid, r in routers.items()},
            'client_pkt_no': {c.id(): c.pkt_no
                              for c in network.clients.values()},
        })

    with open(result_file, 'w') as fh:
        # default=str: FIB/RIB values may hold non-JSON types; both backends
        # are stringified the same way, so comparison is unaffected
        json.dump(result, fh, default=str)


def _run_worker(backend, gml, until, mode, log_level=2, log_path=None,
                hosts=(0, 0), hop_by_hop=False, weighted=False):
    fd, result_file = tempfile.mkstemp(suffix='.json', prefix='bench_')
    os.close(fd)
    cmd = [sys.executable, os.path.abspath(__file__),
           '--fullsim-worker', backend, '--worker-mode', mode,
           '--result-file', result_file, '--gml', gml,
           '--until', str(until), '--log-level', str(log_level),
           '--servers', str(hosts[0]), '--clients', str(hosts[1]),
           '--old-file', OLD_FILE, '--new-file', NEW_FILE]
    if hop_by_hop:
        cmd.append('--hop-by-hop')
    if weighted:
        cmd.append('--weighted')
    try:
        if log_path:
            with open(log_path, 'w') as log:
                proc = subprocess.run(cmd, stdout=log, stderr=subprocess.PIPE,
                                      text=True, cwd=REPO_ROOT)
        else:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  cwd=REPO_ROOT)
        if proc.returncode != 0:
            print(f"!! {backend} {mode} worker failed:\n{proc.stderr[-4000:]}")
            return None
        with open(result_file) as fh:
            return json.load(fh)
    finally:
        os.remove(result_file)


def _diff_dict(label, a, b, limit=10):
    """Print up to `limit` keys where two dicts differ. Returns True if equal."""
    if a == b:
        return True
    keys = sorted(set(a) | set(b), key=str)
    bad = [k for k in keys if a.get(k) != b.get(k)]
    print(f"!! {label}: {len(bad)} of {len(keys)} entries differ")
    for k in bad[:limit]:
        print(f"   {label}[{k}]: old={a.get(k)} new={b.get(k)}")
    return False


def _compare_requests(a, b):
    """Compare the ordered request-outcome lists. Returns True if equal."""
    if a == b:
        return True
    n = min(len(a), len(b))
    first = next((i for i in range(n) if a[i] != b[i]), n)
    print(f"!! client requests: old={len(a)} new={len(b)}; "
          f"first difference at #{first}")
    for i in range(first, min(first + 5, max(len(a), len(b)))):
        print(f"   #{i}: old={a[i] if i < len(a) else '-'} "
              f"new={b[i] if i < len(b) else '-'}")
    return False


def _summarise_requests(reqs):
    accepted = sum(1 for r in reqs if r[4])
    per_server = collections.Counter(r[1] for r in reqs)
    return accepted, len(reqs) - accepted, per_server


def part_b(gml, until, repeats, logs_dir, log_level, hosts=(0, 0),
           hop_by_hop=False, weighted=False):
    wk = dict(hosts=hosts, hop_by_hop=hop_by_hop, weighted=weighted)
    print("\n" + "=" * 78)
    print("Part B -- full-simulation A/B "
          f"(gml={os.path.basename(gml)}, until={until}, repeats={repeats})")
    print(describe_backends())
    print("=" * 78)

    # ---- timing: interleaved so drift affects both backends alike ----
    timings = {b: [] for b in BACKENDS}
    for i in range(repeats):
        for backend in BACKENDS:
            r = _run_worker(backend, gml, until, 'time', **wk)
            if r is None:
                return False
            timings[backend].append(r)
            print(f"  run {i + 1}/{repeats} {backend:<6} "
                  f"wall {r['wall_s']:>8.3f}s  "
                  f"peak RSS {r['peak_rss_mb']:>8.1f} MB", flush=True)

    first = timings['old'][0]
    print(f"\nrouting: {first['routing']}, hop_by_hop: {first['hop_by_hop']}")
    print(f"{'backend':<8} {'median s':>9} {'min s':>9} {'max s':>9} "
          f"{'RSS MB':>9}")
    med = {}
    for backend, runs in timings.items():
        walls = [r['wall_s'] for r in runs]
        med[backend] = statistics.median(walls)
        rss = statistics.median(r['peak_rss_mb'] for r in runs)
        print(f"{backend:<8} {med[backend]:>9.3f} {min(walls):>9.3f} "
              f"{max(walls):>9.3f} {rss:>9.1f}")
    print(f"--> new wall-time speedup x"
          f"{med['old'] / max(med['new'], 1e-12):.2f} (median)")

    # ---- equivalence: one instrumented run per backend ----
    print("\nEquivalence (instrumented run per backend)")
    chk = {}
    for backend in BACKENDS:
        chk[backend] = _run_worker(backend, gml, until, 'check', **wk)
        if chk[backend] is None:
            return False
    a, b = chk['old'], chk['new']

    acc, blk, per_server = _summarise_requests(a['requests'])
    print(f"  old: {len(a['requests'])} requests at servers "
          f"({acc} accepted, {blk} blocked), {a['n_sends']} router sends")
    acc, blk, _ = _summarise_requests(b['requests'])
    print(f"  new: {len(b['requests'])} requests at servers "
          f"({acc} accepted, {blk} blocked), {b['n_sends']} router sends")
    if not a['requests'] and not b['requests']:
        print("  !! no client request reached a server: the request check is "
              "vacuous (routes may not have converged yet -- raise --until)")

    checks = [
        ('client request outcomes (ordered)',
         _compare_requests(a['requests'], b['requests'])),
        ('router packet sends by type/op',
         _diff_dict('sends', a['sends'], b['sends'])),
        ('router send stream, order within each (time, router) step '
         'ignored', a['send_batch_digest'] == b['send_batch_digest']),
        ('service FIB', _diff_dict('fib', a['fib'], b['fib'])),
        ('FIB update counts',
         _diff_dict('fib_updates', a['fib_updates'], b['fib_updates'])),
        ('final RIB', _diff_dict('rib', a['rib'], b['rib'])),
        ('final sent table', _diff_dict('sent', a['sent'], b['sent'])),
        ('router pkt_no', _diff_dict('router_pkt_no', a['router_pkt_no'],
                                     b['router_pkt_no'])),
        ('client pkt_no', _diff_dict('client_pkt_no', a['client_pkt_no'],
                                     b['client_pkt_no'])),
    ]
    for label, same in checks:
        print(f"  [{'OK' if same else 'DIFF'}] {label}")
    ok = all(same for _, same in checks)

    # Strict send order is reported but not failed on its own: the dict
    # backend may emit several withdrawals from one decision step in a
    # different order (sent_table insertion order vs TinyDB doc_id set order)
    strict = a['send_digest'] == b['send_digest']
    if strict:
        print("  [OK] router send stream, strict order")
    elif checks[2][1]:
        print("  [NOTE] router send stream, strict order: packets sent by one "
              "router at one instant\n"
              "         are in a different order (e.g. two withdrawals in one "
              "step); not a failure")
    else:
        print("  [DIFF] router send stream, strict order -- run with --logs "
              "to find the first divergence")

    # ---- optional: log capture + log comparison ----
    if logs_dir:
        print(f"\nLogs (Verbose.level={log_level}) -> {logs_dir}")
        os.makedirs(logs_dir, exist_ok=True)
        paths = {}
        for backend in BACKENDS:
            paths[backend] = os.path.join(logs_dir, f"{backend}.log")
            if _run_worker(backend, gml, until, 'log', log_level,
                           paths[backend], **wk) is None:
                return False
            print(f"  {backend}: {paths[backend]} "
                  f"({os.path.getsize(paths[backend]) / 1e6:.1f} MB)")
        checker = os.path.join(REPO_ROOT, 'scripts',
                               'check-tinydb-dict-logs.py')
        proc = subprocess.run([sys.executable, checker, paths['old'],
                               paths['new']], capture_output=True, text=True,
                              cwd=REPO_ROOT)
        print(proc.stdout.rstrip())
        if proc.stderr:
            print(proc.stderr.rstrip()[-2000:])
        log_ok = proc.returncode == 0
        order_note = (" -- order differs within simultaneous steps only"
                      if log_ok and "ORDER ONLY" in proc.stdout else "")
        print(f"  [{'OK' if log_ok else 'DIFF'}] log comparison "
              f"(check-tinydb-dict-logs.py){order_note}")
        ok = ok and log_ok

    print("Part B:", "OK" if ok else "FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=
                                 argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--fullsim', action='store_true',
                    help='also run Part B (full-simulation A/B)')
    ap.add_argument('--skip-part-a', action='store_true',
                    help='skip the Part A microbenchmark')
    ap.add_argument('--gml', default=DEFAULT_GML,
                    help='topology file for Part B')
    ap.add_argument('--servers', type=int, default=0,
                    help='Part B: attach N servers to local (degree <= 3) '
                         'nodes, for GMLs without hosts (e.g. topologies/gml)')
    ap.add_argument('--clients', type=int, default=0,
                    help='Part B: attach N clients likewise')
    ap.add_argument('--hop-by-hop', action='store_true',
                    help='Part B: Router.hop_by_hop = True (hop-by-hop anycast '
                         'request forwarding; default first-decide unicast)')
    ap.add_argument('--weighted', action='store_true',
                    help='Part B: engine Dijkstra over link weights instead of '
                         'hop count (as main_precomputed_t1.py "weighted")')
    ap.add_argument('--until', type=float, default=60,
                    help='simulated seconds for Part B (default 60)')
    ap.add_argument('--repeats', type=int, default=3,
                    help='timing runs per backend in Part B (default 3)')
    ap.add_argument('--logs', metavar='DIR',
                    help='Part B: also capture both logs into DIR and run '
                         'scripts/check-tinydb-dict-logs.py on them')
    ap.add_argument('--log-level', type=int, default=2,
                    help='Verbose.level for --logs runs (default 2)')
    ap.add_argument('--seed', type=int, default=SEED)
    ap.add_argument('--old-file', default='Router-old.py',
                    help='Router version in src/ used as the baseline '
                         '(default Router-old.py)')
    ap.add_argument('--new-file', default='Router.py',
                    help='Router version in src/ being tested '
                         '(default Router.py)')
    # internal: run one backend in a subprocess
    ap.add_argument('--fullsim-worker', metavar='BACKEND',
                    choices=list(BACKENDS), help=argparse.SUPPRESS)
    ap.add_argument('--worker-mode', choices=['time', 'check', 'log'],
                    default='time', help=argparse.SUPPRESS)
    ap.add_argument('--result-file', help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.fullsim_worker:
        fullsim_worker(args.fullsim_worker, args.gml, args.until,
                       args.worker_mode, args.result_file, args.log_level,
                       (args.servers, args.clients), args.hop_by_hop,
                       args.weighted)
        return 0

    ok = True
    if not args.skip_part_a:
        ok = part_a(args.seed)
    if args.fullsim:
        ok = part_b(args.gml, args.until, args.repeats, args.logs,
                    args.log_level,
                    (args.servers, args.clients), args.hop_by_hop,
                    args.weighted) and ok
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())

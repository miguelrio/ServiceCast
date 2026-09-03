#!/usr/bin/env python3
"""L0 probe: static (no-traffic) cost of building a ServiceCast network.

Phases (each timed; rss_mb_hwm is the cumulative ru_maxrss high-water mark):
  gen         synth.generate -> Graph          (or --gml Name -> read_gml)
  from_graph  Network.from_graph               (Router objects, each with a
              TinyDB(MemoryStorage); SwitchPort+LinkEnd per directed link)
  tables      calculate_forwarding_tables      [--with-tables] O(N^2)-per-
              source Dijkstra, per-router unicast tables, the global
              latency_table, and the network diameter
  verify      correctness checks              [--with-tables, n <= --verify-max]
              table completeness + sampled next-hop path walking

Structural verification (always, synth mode): exact intra-clique edge count,
per-router intra-degree == routers_per_as-1, union-find connectivity.

--selftest: prove synth's direct Graph construction equals the public
add_node/add_edge API on a small topology (AdjNode chains + labels), then
exit. --gml NAME runs the same phases on a real topology as an anchor.

Memory watchdog (--mem-guard-gb, default 20): a thread polls ru_maxrss and
exits with the partial JSON row and status censored:memguard before the OS
has to OOM-kill us.

--sweep n1,n2,... re-executes this script per point as a subprocess (clean
RSS isolation, per-point --timeout), appending JSONL rows to -o. Costs are
monotone in N, so after --max-censor-stops (default 2) consecutive
censored:timeout/memguard/killed points the sweep stops extending and only
reports the remaining points in the summary.
"""

import os
import sys
import json
import time
import random
import argparse
import platform
import resource
import subprocess

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

import simpy  # noqa: E402

from Graph import Graph, AdjNode  # noqa: E402
from Network import Network  # noqa: E402
from Verbose import Verbose  # noqa: E402
from Gml import read_gml  # noqa: E402
import synth  # noqa: E402

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# shared with the watchdog thread; simple assignments, GIL-atomic
STATE = {"phases": [], "row": None, "guard_mb": None}


def peak_rss_mb():
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return rss / (1024.0 * 1024.0)
    return rss / 1024.0


def _total_ram_gb():
    """Total physical RAM in GB, or None if it cannot be determined."""
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024.0 ** 3
    except (ValueError, OSError, AttributeError):
        try:
            out = subprocess.run(["sysctl", "-n", "hw.memsize"],
                                 capture_output=True, text=True).stdout.strip()
            return int(out) / 1024.0 ** 3
        except Exception:
            return None


def timed_phase(name, fn):
    t0 = time.perf_counter()
    out = fn()
    STATE["phases"].append({"name": name, "s": round(time.perf_counter() - t0, 3),
                            "rss_mb_hwm": round(peak_rss_mb(), 1)})
    return out


def start_watchdog(limit_mb):
    import threading

    def watch():
        while True:
            time.sleep(0.5)
            rss = peak_rss_mb()
            if rss > limit_mb:
                row = STATE["row"] or {}
                row["status"] = "censored:memguard"
                row["phases"] = STATE["phases"]
                row["guard_rss_mb"] = round(rss, 1)
                row["guard_limit_mb"] = limit_mb
                print(json.dumps(row))
                sys.stdout.flush()
                os._exit(78)

    t = threading.Thread(target=watch, daemon=True)
    t.start()


def current_git_commit():
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                           cwd=PROJECT, capture_output=True, text=True, check=True)
        return r.stdout.strip()
    except Exception:
        return "unknown"


# --- structural checks on a synth Graph --------------------------------------

def adjacency_lists(graph):
    """[(index, [(nbr_index, weight), ...]), ...] from the AdjNode chains."""
    out = []
    for i in range(graph.V):
        nbrs = []
        node = graph.graph[i]
        while node is not None:
            nbrs.append((node.vertex, node.weight))
            node = node.next
        out.append((i, nbrs))
    return out


def check_structure(graph, stats, row):
    n = graph.V
    intra = 0
    deg = [0] * n
    for i, nbrs in adjacency_lists(graph):
        for (j, _w) in nbrs:
            deg[i] += 1
            if j // stats["routers_per_as"] == i // stats["routers_per_as"]:
                intra += 1
    intra //= 2
    row["edges"] = sum(deg) // 2
    row["intra_edges"] = intra
    row["degree_mean"] = round(2.0 * row["edges"] / n, 3)
    row["degree_max"] = max(deg)
    if intra != stats["expected_intra_edges"]:
        row["status"] = "error:intra_count"
        row["error"] = (f"intra edges {intra} != expected "
                        f"{stats['expected_intra_edges']}")
    # every router sits in a full clique of its AS block
    rpa = stats["routers_per_as"]
    bad_intra = sum(1 for i, nbrs in adjacency_lists(graph)
                    if sum(1 for (j, _w) in nbrs if j // rpa == i // rpa) != rpa - 1)
    if bad_intra:
        row["status"] = "error:clique"
        row["error"] = f"{bad_intra} routers without a full intra-AS clique"

    # union-find connectivity
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, nbrs in adjacency_lists(graph):
        for (j, _w) in nbrs:
            ra, rb = find(i), find(j)
            if ra != rb:
                parent[ra] = rb
    roots = {find(i) for i in range(n)}
    row["connected"] = len(roots) == 1
    if len(roots) != 1 and not row.get("error"):
        row["status"] = "error:disconnected"
        row["error"] = f"{len(roots)} connected components"


# --- table verification -------------------------------------------------------

def verify_tables(network, verify_pairs, row):
    names = network.nodes()
    name_set = set(names)
    routers = network.routers

    # completeness: every router has a finite entry for every other router
    # (the table never contains an entry for the router itself)
    incomplete = 0
    for r in names:
        table = routers[r].unicast_forwarding_table
        if set(table.keys()) != name_set - {r} or any(
                e[2] == float("inf") for e in table.values()):
            incomplete += 1
    row["verify_incomplete_routers"] = incomplete

    # path walking: follow next hops from src until dst is reached
    rng = random.Random(7)
    pairs = []
    if len(names) > 1:
        for _ in range(min(verify_pairs, len(names) * (len(names) - 1))):
            pairs.append(tuple(rng.sample(names, 2)))
    ok = bad = 0
    for (src, dst) in pairs:
        cur, steps = src, 0
        while steps <= len(names):
            entry = routers[cur].unicast_forwarding_table.get(dst)
            if entry is None or entry[1] == cur:
                bad += 1
                break
            if entry[1] == dst:
                ok += 1
                break
            cur = entry[1]
            steps += 1
        else:
            bad += 1
    row["verify_pairs_ok"], row["verify_pairs_bad"] = ok, bad

    # mean hop distance over a sample of routers' tables (weights are hops:
    # dijkstra runs with use_weights=False)
    sample = names[:10]
    weights = [w for r in sample
               for (_d, _nh, w) in routers[r].unicast_forwarding_table.values()
               if w != float("inf")]
    row["mean_hops"] = round(sum(weights) / max(1, len(weights)), 2)

    lat = network.latency_table
    row["latency_outer"] = len(lat)
    if len(names) <= 4000:
        row["latency_inner"] = sum(len(v) for v in lat.values())


# --- selftest: direct construction == public API ------------------------------

def selftest():
    graph, _stats = synth.generate(n_as=4, routers_per_as=5, as_degree=5,
                                   seed=15112022)
    edges = set()
    for i, nbrs in adjacency_lists(graph):
        for (j, w) in nbrs:
            edges.add((min(i, j), max(i, j), round(w, 6)))
    g2 = Graph()
    for name in graph.labels:
        g2.add_node(name)
    for (i, j, w) in sorted(edges):
        g2.add_edge(graph.labels[i], graph.labels[j], w)

    def adj_canonical(g):
        # vertices may be int indices or names (public add_edge stores the
        # first endpoint pre-conversion); normalize through labels
        def vname(v):
            return v if isinstance(v, str) else g.labels[v]
        return {i: sorted((vname(j), round(w, 6)) for (j, w) in nbrs)
                for i, nbrs in adjacency_lists(g)}

    same = (g2.V == graph.V and g2.labels == graph.labels
            and adj_canonical(g2) == adj_canonical(graph))
    print(json.dumps({"selftest": "ok" if same else "FAILED",
                      "nodes": graph.V, "edges": len(edges)}))
    return 0 if same else 1


# --- one probe run -------------------------------------------------------------

def run_probe(args):
    row = {
        "commit": current_git_commit(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "routers_per_as": args.routers_per_as,
        "as_degree": args.as_degree,
        "seed": args.seed,
        "mem_guard_gb": args.mem_guard_gb,
        "status": "ok",
    }
    STATE["row"] = row

    if args.gml:
        row["mode"] = "gml"
        gml_file = os.path.join(PROJECT, "topologies", "gml",
                                f"{args.gml}.gml")
        graph = timed_phase("gen", lambda: read_gml(gml_file))
        stats = {"routers_per_as": 0}
        row["n_routers"] = len(graph)
        row["n_as"] = None
        deg_total = sum(len(nbrs) for _i, nbrs in adjacency_lists(graph))
        row["edges"] = deg_total // 2
        row["degree_mean"] = round(2.0 * row["edges"] / max(1, len(graph)), 3)
        row["connected"] = None
    else:
        row["mode"] = "synth"
        n_as = args.n_routers // args.routers_per_as
        if args.n_routers % args.routers_per_as:
            raise SystemExit("--n-routers must be divisible by --routers-per-as")
        row["n_routers"] = args.n_routers
        row["n_as"] = n_as

        def build():
            g, s = synth.generate(
                n_as=n_as, routers_per_as=args.routers_per_as,
                as_degree=args.as_degree, seed=args.seed)
            row["as_edges"] = s["as_edges"]
            row["dropped_stubs"] = s["dropped_stubs"]
            return g

        graph = timed_phase("gen", build)
        check_structure(graph, {"routers_per_as": args.routers_per_as,
                                "expected_intra_edges":
                                    n_as * args.routers_per_as *
                                    (args.routers_per_as - 1) // 2}, row)
        if row["status"] != "ok":
            return row

    env = simpy.Environment()
    network = timed_phase("from_graph",
                          lambda: Network.from_graph(graph, env))
    row["network_routers"] = len(network.routers)
    row["network_links"] = len(network.links)

    if args.with_tables:
        timed_phase("tables", network.calculate_forwarding_tables)
        row["diameter"] = network.network_diameter()
        if row["n_routers"] <= args.verify_max:
            timed_phase("verify",
                        lambda: verify_tables(network, 200, row))
            if (row.get("verify_incomplete_routers") or
                    row.get("verify_pairs_bad")):
                row["status"] = "error:tables"
                row["error"] = (f"incomplete={row.get('verify_incomplete_routers')} "
                                f"bad_paths={row.get('verify_pairs_bad')}")

    for router in network.routers.values():
        db = getattr(router, "db", None)
        if db is not None:
            db.close()
    row["phases"] = STATE["phases"]
    return row


# --- sweep ---------------------------------------------------------------------

def run_sweep(args, points):
    tag = "l0b" if args.with_tables else "l0a"
    out_path = args.output or os.path.join(
        PROJECT, "results", f"probe-{tag}-{time.strftime('%Y%m%d-%H%M%S')}.jsonl")
    censors = 0
    with open(out_path, "w") as out:
        for idx, n in enumerate(points):
            cmd = [sys.executable, os.path.abspath(__file__),
                   "--n-routers", str(n),
                   "--routers-per-as", str(args.routers_per_as),
                   "--as-degree", str(args.as_degree),
                   "--seed", str(args.seed),
                   "--mem-guard-gb", str(args.mem_guard_gb),
                   "--verify-max", str(args.verify_max)]
            if args.with_tables:
                cmd.append("--with-tables")
            t0 = time.perf_counter()
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True,
                                      timeout=args.timeout)
                wall = time.perf_counter() - t0
                line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    row = {"n_routers": n, "status": f"error:exit{proc.returncode}",
                           "error": (proc.stderr or line)[:300]}
                row["wall_s"] = round(wall, 1)
            except subprocess.TimeoutExpired:
                row = {"n_routers": n, "status": "censored:timeout",
                       "wall_s": round(time.perf_counter() - t0, 1)}
            out.write(json.dumps(row) + "\n")
            out.flush()
            print(f"[{idx + 1}/{len(points)}] n={n:>7d} {row['status']:<24s} "
                  f"wall={row['wall_s']:>8.1f}s", file=sys.stderr)
            if str(row["status"]).startswith(("censored:timeout",
                                              "censored:memguard",
                                              "censored:killed", "error:")):
                censors += 1
                if censors >= args.max_censor_stops:
                    rest = points[idx + 1:]
                    print(f"stopping sweep: {censors} consecutive censors; "
                          f"skipping {rest} (costs are monotone in N)",
                          file=sys.stderr)
                    break
            else:
                censors = 0
    print(out_path)


# --- CLI -----------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--n-routers", type=int, default=250)
    p.add_argument("--routers-per-as", type=int, default=5)
    p.add_argument("--as-degree", type=int, default=5)
    p.add_argument("--seed", type=int, default=15112022)
    p.add_argument("--with-tables", action="store_true")
    p.add_argument("--verify-max", type=int, default=2000,
                   help="run table verification when n_routers <= this")
    p.add_argument("--mem-guard-gb", type=float, default=None,
                   help="kill a run above this much memory (default: 80% of "
                        "this machine's RAM, capped at 20 GB)")
    p.add_argument("--gml", default=None,
                   help="topology name (e.g. Dfn, Cogentco) instead of synth")
    p.add_argument("--sweep", default=None,
                   help="comma-separated n_routers list; re-exec per point")
    p.add_argument("--timeout", type=float, default=1200.0,
                   help="per-point subprocess timeout in sweep mode")
    p.add_argument("--max-censor-stops", type=int, default=2)
    p.add_argument("--output", "-o", default=None, help="JSONL path (sweep)")
    p.add_argument("--selftest", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    Verbose.level = -1
    Verbose.table = 0

    if args.mem_guard_gb is None:
        ram = _total_ram_gb()
        args.mem_guard_gb = min(20.0, ram * 0.8) if ram else 20.0

    if args.selftest:
        sys.exit(selftest())

    if args.sweep:
        points = [int(x) for x in args.sweep.split(",") if x.strip()]
        run_sweep(args, points)
        return

    start_watchdog(args.mem_guard_gb * 1024.0)  # GB -> MB
    t0 = time.perf_counter()
    row = run_probe(args)
    row["wall_s"] = round(time.perf_counter() - t0, 1)
    print(json.dumps(row))


if __name__ == "__main__":
    main()

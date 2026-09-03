#!/usr/bin/env python3
"""Regenerate and inspect a probe topology.

Probe topologies are never written to disk: synth.generate builds the Graph
in memory inside each probe subprocess, and it dies with the process. They
are fully deterministic, though -- same (n_as, routers_per_as, as_degree,
seed) regenerates the identical topology -- so this script reconstructs any
of them on demand to characterize or render.

Usage:
  python3 scripts/show_topology.py --n-routers 1000            # stats only
  python3 scripts/show_topology.py --n-routers 100 --render    # + PNGs

Stats printed: node/edge counts, router-degree distribution, intra/inter
edge split, AS-level degree distribution, intra/inter weight ranges, and
hop statistics (exact multi-source BFS over the regenerated graph, hop
counts matching what the tables compute: dijkstra runs unweighted).
Render (small N only): router-level picture colored by AS, and the AS-level
graph (ring + stub pairings).
"""

import os
import sys
import json
import random
import argparse
import collections

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

import synth  # noqa: E402

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def hop_stats(graph, sources, n):
    """Unweighted shortest-path stats via BFS from each sampled source."""
    dists_sum = collections.Counter()
    ecc = []
    for s in sources:
        dist = {s: 0}
        frontier = [s]
        while frontier:
            nxt = []
            for u in frontier:
                node = graph.graph[u]
                while node is not None:
                    v = node.vertex
                    if v not in dist:
                        dist[v] = dist[u] + 1
                        nxt.append(v)
                    node = node.next
            frontier = nxt
        assert len(dist) == n, "graph not connected?"
        for d in dist.values():
            dists_sum[d] += 1
        ecc.append(max(dist.values()))
    total = sum(k * v for k, v in dists_sum.items())
    cnt = sum(dists_sum.values())
    order = sorted(dists_sum)
    p95 = order[0]
    acc = 0
    for d in order:
        acc += dists_sum[d]
        if acc >= 0.95 * cnt:
            p95 = d
            break
    return {"mean": round(total / cnt, 2), "median": order[len(order) // 2],
            "p95": p95, "max_sampled_ecc": max(ecc)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--n-routers", type=int, default=1000)
    p.add_argument("--routers-per-as", type=int, default=5)
    p.add_argument("--as-degree", type=int, default=5)
    p.add_argument("--seed", type=int, default=15112022)
    p.add_argument("--render", action="store_true",
                   help="draw PNGs (router-level and AS-level, small N only)")
    p.add_argument("--bfs-sources", type=int, default=40)
    args = p.parse_args()

    n_as = args.n_routers // args.routers_per_as
    graph, stats = synth.generate(
        n_as=n_as, routers_per_as=args.routers_per_as,
        as_degree=args.as_degree, seed=args.seed)
    n = graph.V
    rpa = args.routers_per_as

    deg = [0] * n
    intra_w, inter_w = [], []
    inter_per_as = collections.Counter()
    seen = set()
    for i in range(n):
        node = graph.graph[i]
        while node is not None:
            j = node.vertex
            deg[i] += 1
            key = (min(i, j), max(i, j))
            if key not in seen:
                seen.add(key)
                if j // rpa == i // rpa:
                    intra_w.append(node.weight)
                else:
                    inter_w.append(node.weight)
                    inter_per_as[i // rpa] += 1
                    inter_per_as[j // rpa] += 1
            node = node.next

    out = {
        "n_routers": n, "n_as": n_as,
        "edges": len(seen),
        "intra_edges": len(intra_w), "inter_edges": len(inter_w),
        "router_degree": {
            "min": min(deg), "mean": round(sum(deg) / n, 3), "max": max(deg),
            "distribution": {str(k): v for k, v in
                             sorted(collections.Counter(deg).items())}},
        "as_inter_degree": {
            "min": min(inter_per_as.values()),
            "mean": round(sum(inter_per_as.values()) / n_as, 3),
            "max": max(inter_per_as.values()),
            "distribution": {str(k): v for k, v in
                             sorted(collections.Counter(
                                 inter_per_as.values()).items())}},
        "weights": {
            "intra": [round(min(intra_w), 1), round(max(intra_w), 1)],
            "inter": [round(min(inter_w), 1), round(max(inter_w), 1)]},
        "regenerate": (f"synth.generate(n_as={n_as}, "
                       f"routers_per_as={args.routers_per_as}, "
                       f"as_degree={args.as_degree}, seed={args.seed})"),
    }
    if args.bfs_sources:
        src = random.Random(0).sample(range(n), min(args.bfs_sources, n))
        out["hops"] = hop_stats(graph, src, n)

    print(json.dumps(out, indent=1))

    if args.render:
        import networkx as nx
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        if n > 500:
            sys.exit("render refused: N > 500; render a smaller regeneration "
                     "of the same family instead")
        # router-level picture
        G = nx.Graph()
        G.add_nodes_from(range(n))
        intra, inter = [], []
        for (i, j) in seen:
            G.add_edge(i, j)
            (intra if j // rpa == i // rpa else inter).append((i, j))
        pos = nx.spring_layout(G, seed=args.seed, iterations=200,
                               k=1.2 / (n ** 0.5))
        fig, a = plt.subplots(figsize=(11, 8.5))
        nx.draw_networkx_edges(G, pos, edgelist=intra, edge_color="#bbbbbb",
                               width=0.6, ax=a)
        nx.draw_networkx_edges(G, pos, edgelist=inter, edge_color="steelblue",
                               width=0.9, ax=a)
        nx.draw_networkx_nodes(G, pos, node_size=28, ax=a,
                               node_color=[(i // rpa) for i in range(n)],
                               cmap="tab20")
        a.set_title(f"synth topology, N={n} routers, {n_as} ASes "
                    f"(nodes colored by AS; gray = intra-AS clique links, "
                    f"blue = inter-AS)")
        a.axis("off")
        out1 = os.path.join(PROJECT, "results",
                            f"topology-routers-n{n}-seed{args.seed}.png")
        fig.savefig(out1, dpi=150, bbox_inches="tight")
        print(out1)

        # AS-level picture
        GA = nx.Graph()
        for as_i in range(n_as):
            GA.add_node(as_i)
        for (i, j) in inter:
            GA.add_edge(i // rpa, j // rpa)
        fig, a = plt.subplots(figsize=(7, 6))
        posA = nx.spring_layout(GA, seed=args.seed)
        nx.draw_networkx(GA, posA, node_size=45, node_color="tab:orange",
                         edge_color="steelblue", width=0.8, with_labels=False,
                         ax=a)
        a.set_title(f"AS-level graph: {n_as} ASes, ring + random stubs "
                    f"(avg inter-degree {out['as_inter_degree']['mean']})")
        a.axis("off")
        out2 = os.path.join(PROJECT, "results",
                            f"topology-as-level-n{n_as}-seed{args.seed}.png")
        fig.savefig(out2, dpi=150, bbox_inches="tight")
        print(out2)


if __name__ == "__main__":
    main()

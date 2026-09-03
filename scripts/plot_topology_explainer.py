#!/usr/bin/env python3
"""Render a self-explanatory figure of the topologies used in the scaling probe.

One image, six panels, reading from building block to experiment scale:
  (a) inside one AS  -- the K5 clique every AS is made of, plus its inter-AS
      links, with the per-router degree arithmetic spelled out
  (b) how ASes connect -- AS-level graph on a circle: ring (guarantees the
      network is connected) + random extra links to ~5 neighbours
  (c) router-level view at the smallest experiment size (N=100): each AS's
      5 routers drawn as a small pentagon, cliques in grey, inter-AS links
      in blue, placed by the AS-level layout
  (d) the same structure at N=1,000 (the size the correctness checks ran at)
  (e) router-degree distribution at N=1,000
  (f) shortest-path-length distribution at N=1,000 (BFS, 40 sources)

Footer states that every experiment used this same family -- only the number
of ASes changed (5..80,000 ASes = 250..400,000 routers).
"""

import os
import sys
import math
import random
import collections

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

import numpy as np
import networkx as nx
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import synth  # noqa: E402

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED = 15112022
RPA = 5          # routers per AS (fixed across all experiment sizes)


def edges_of(graph):
    """Undirected edge list + intra/inter split, as (i, j) index pairs."""
    intra, inter, seen = [], [], set()
    for i in range(graph.V):
        node = graph.graph[i]
        while node is not None:
            j = node.vertex
            if (min(i, j), max(i, j)) not in seen:
                seen.add((min(i, j), max(i, j)))
                (intra if j // RPA == i // RPA else inter).append(
                    (min(i, j), max(i, j)))
            node = node.next
    return intra, inter


def as_graph(inter, n_as):
    GA = nx.Graph()
    GA.add_nodes_from(range(n_as))
    for (i, j) in inter:
        GA.add_edge(i // RPA, j // RPA)
    return GA


def cluster_layout(GA, n):
    """AS centroids from the AS-level layout; each AS's routers on a small
    pentagon around its centroid, so the clique structure is visible."""
    posA = nx.spring_layout(GA, seed=SEED, k=1.0 / math.sqrt(len(GA) + 1),
                            iterations=300)
    pos = {}
    r = 0.13
    for a in range(len(GA)):
        cx, cy = posA[a]
        for k in range(RPA):
            ang = 2 * math.pi * k / RPA + 0.3 * a
            pos[a * RPA + k] = (cx + r * math.cos(ang), cy + r * math.sin(ang))
    return pos


def bfs_distances(graph, sources, n):
    """Unweighted shortest paths (what the forwarding tables count)."""
    dists = collections.Counter()
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
        dists.update(dist.values())
    return dists


def main():
    rng = random.Random(0)
    g100, _ = synth.generate(n_as=100 // RPA, routers_per_as=RPA,
                             as_degree=5, seed=SEED)
    g1000, _ = synth.generate(n_as=1000 // RPA, routers_per_as=RPA,
                              as_degree=5, seed=SEED)
    intra100, inter100 = edges_of(g100)
    intra1000, inter1000 = edges_of(g1000)

    fig = plt.figure(figsize=(15, 10.5))
    gs = fig.add_gridspec(2, 3)

    # (a) anatomy of one AS: a K5 clique + its inter-AS links
    a = fig.add_subplot(gs[0, 0])
    ang5 = [2 * math.pi * k / 5 + math.pi / 2 for k in range(5)]
    pent = {k: (math.cos(t), math.sin(t)) for k, t in enumerate(ang5)}
    for i in range(5):
        for j in range(i + 1, 5):
            a.plot([pent[i][0], pent[j][0]], [pent[i][1], pent[j][1]],
                   color="#999999", lw=1.2, zorder=1)
    # which routers of AS 0 actually carry its inter-AS links in g100
    carry = []
    for (i, j) in inter100:
        if i < RPA:
            carry.append(i)
        if j < RPA:
            carry.append(j)
    for k in range(5):
        if k in carry:
            t = math.pi / 2 + rng.uniform(-1.2, 1.2)
            a.plot([pent[k][0], 1.75 * math.cos(t)], [pent[k][1], 1.75 * math.sin(t)],
                   color="steelblue", lw=2, zorder=1)
            a.plot(1.75 * math.cos(t), 1.75 * math.sin(t), "o",
                   color="lightsteelblue", ms=14, mec="steelblue", zorder=2)
    for k, (x, y) in pent.items():
        a.plot(x, y, "o", color="tab:orange", ms=17, mec="black", mew=0.6,
               zorder=3)
    a.set_title("(a) Inside one AS (autonomous system)\n"
                "every AS is 5 routers, all connected to each other",
                fontsize=10)
    a.text(0, -1.62,
           "grey: the 10 links inside the AS\n"
           "blue: links to other ASes (an AS has ~5)\n\n"
           "average router degree: 4 inside + 1 outside = 5",
           ha="center", fontsize=9,
           bbox=dict(boxstyle="round,pad=0.4", fc="#f5f5f5", ec="#cccccc"))
    a.set_xlim(-2.1, 2.1); a.set_ylim(-2.3, 1.5); a.axis("off")

    # (b) AS-level graph on a circle: ring + chords
    a = fig.add_subplot(gs[0, 1])
    n_as_show = 24
    GA = as_graph(inter100, 100 // RPA)
    sub = nx.Graph(); sub.add_nodes_from(range(n_as_show))
    posC = nx.circular_layout(nx.path_graph(n_as_show))
    ring = [(i, (i + 1) % n_as_show) for i in range(n_as_show)]
    chords = [(u, v) for (u, v) in GA.edges()
              if u < n_as_show and v < n_as_show and (u, v) not in ring
              and (v, u) not in ring]
    nx.draw_networkx_edges(sub, posC, edgelist=ring, edge_color="#bbbbbb",
                           width=1.6, ax=a)
    nx.draw_networkx_edges(sub, posC, edgelist=chords, edge_color="steelblue",
                           width=1.1, ax=a)
    nx.draw_networkx_nodes(sub, posC, node_size=90, node_color="tab:orange",
                           edgecolors="black", linewidths=0.5, ax=a)
    a.set_title("(b) How ASes are connected (24 shown; experiments use up to 80,000)\n"
                "grey ring keeps the network connected; blue links are added at random\n"
                "until each AS has ~5 AS neighbours", fontsize=10)
    a.axis("off")

    # (c) router-level view, N=100
    a = fig.add_subplot(gs[0, 2])
    pos100 = cluster_layout(as_graph(inter100, 100 // RPA), 100)
    G = nx.Graph(); G.add_nodes_from(range(100))
    nx.draw_networkx_edges(G, pos100, edgelist=intra100, edge_color="#bbbbbb",
                           width=0.7, ax=a)
    nx.draw_networkx_edges(G, pos100, edgelist=inter100, edge_color="steelblue",
                           width=1.3, ax=a)
    nx.draw_networkx_nodes(G, pos100, node_size=26,
                           node_color=[i // RPA for i in range(100)],
                           cmap="turbo", edgecolors="none", ax=a)
    a.set_title(f"(c) Whole network at the smallest experiment size\n"
                f"N=100 routers = 20 ASes; {len(intra100)} grey intra-AS links, "
                f"{len(inter100)} blue inter-AS links\neach coloured cluster is one AS "
                f"(the pentagons from panel a)", fontsize=10)
    a.axis("off")

    # (d) same structure at N=1000
    a = fig.add_subplot(gs[1, 0])
    pos1000 = cluster_layout(as_graph(inter1000, 1000 // RPA), 1000)
    G = nx.Graph(); G.add_nodes_from(range(1000))
    nx.draw_networkx_edges(G, pos1000, edgelist=intra1000, edge_color="#cccccc",
                           width=0.25, alpha=0.8, ax=a)
    nx.draw_networkx_edges(G, pos1000, edgelist=inter1000, edge_color="steelblue",
                           width=0.5, alpha=0.9, ax=a)
    nx.draw_networkx_nodes(G, pos1000, node_size=3,
                           node_color=[i // RPA for i in range(1000)],
                           cmap="turbo", edgecolors="none", ax=a)
    a.set_title("(d) Same structure at N=1,000 routers = 200 ASes\n"
                "(the size the correctness checks ran at)", fontsize=10)
    a.axis("off")

    # (e) router-degree distribution at N=1000
    a = fig.add_subplot(gs[1, 1])
    deg = collections.Counter()
    for (i, j) in intra1000:
        deg[i] += 1; deg[j] += 1
    for (i, j) in inter1000:
        deg[i] += 1; deg[j] += 1
    dist = collections.Counter(deg.values())
    ks = sorted(dist)
    a.bar(ks, [dist[k] for k in ks], color="tab:blue")
    for k in ks:
        a.text(k, dist[k] + 6, str(dist[k]), ha="center", fontsize=8)
    a.set_xlabel("router degree (4 = intra-AS clique only)")
    a.set_ylabel("number of routers")
    a.set_title("(e) Router degrees at N=1,000\n"
                f"mean {sum(k*dist[k] for k in ks)/1000:.2f} — the 4-link floor is the "
                "clique, the tail is inter-AS links", fontsize=10)
    a.grid(True, axis="y", alpha=0.25)

    # (f) shortest-path-length distribution at N=1000
    a = fig.add_subplot(gs[1, 2])
    src = rng.sample(range(1000), 40)
    hops = bfs_distances(g1000, src, 1000)
    hk = sorted(hops)
    a.bar(hk, [hops[k] for k in hk], color="tab:purple")
    total = sum(hops.values())
    a.set_xlabel("shortest-path length (router hops)")
    a.set_ylabel("number of router pairs (40 sources)")
    a.set_title(f"(f) Path lengths at N=1,000  (mean "
                f"{sum(k*hops[k] for k in hk)/total:.1f} hops)\n"
                "typical Internet-like distances: a handful of hops", fontsize=10)
    a.grid(True, axis="y", alpha=0.25)

    fig.suptitle("What the simulated networks look like — "
                 "the one topology family every scaling experiment ran on",
                 fontsize=14)
    fig.text(0.01, 0.002,
             "Generated deterministically from a seed (same family at every size; only the number of "
             "ASes changes): 5 routers per AS, fully linked inside each AS (link weights 1-10); ASes on a "
             "ring plus random extra links to ~5 AS neighbours each (inter-AS link weights 10-50). "
             "Experiments ran N = 250 ... 400,000 routers = 5 ... 80,000 ASes. Seed 15112022.",
             fontsize=8, color="dimgray")
    fig.tight_layout(rect=(0, 0.025, 1, 0.955))

    out = os.path.join(PROJECT, "results", "topology-explainer.png")
    fig.savefig(out, dpi=150)
    print(out)


if __name__ == "__main__":
    main()

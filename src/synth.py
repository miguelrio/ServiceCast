"""Minimal seeded synthetic topology generator for the scaling probe.

Structure (identical family at every size, so fitted slopes reflect size):
  * n_as autonomous systems, each a clique of `routers_per_as` routers
    (intra-AS links, weights uniform in [intra_lo, intra_hi]);
  * AS-level graph of average degree ~`as_degree`: a ring over the ASes
    (guarantees connectivity) plus random stub pairings, no self-loops or
    duplicate AS pairs (inter-AS links, weights uniform in
    [inter_lo, inter_hi]); each AS pair is realized on one random router
    of each AS, so no parallel router-router edges can occur.

Builds the Graph internals directly (labels list + AdjNode chains keyed by
int index). The public add_node/add_edge API resolves names with
labels.index(), an O(N) scan per call, which makes large builds quadratic;
the GML path only survives because those files are tiny. The structures
produced are exactly what Graph.add_edge writes for int endpoints
(AdjNode.vertex holds the int index, labels in insertion order) -- probe_static
--selftest checks this equivalence against the public API.
"""

import random

from Graph import Graph, AdjNode


def generate(n_as, routers_per_as=5, as_degree=5, seed=15112022,
             intra_lo=1.0, intra_hi=10.0, inter_lo=10.0, inter_hi=50.0):
    """Return (Graph, stats_dict) for one synthetic topology."""
    rng = random.Random(seed)

    n = n_as * routers_per_as
    graph = Graph(0)
    graph.V = n
    graph.labels = ["r%d" % i for i in range(n)]
    graph.graph = [None] * n

    def add_edge(i, j, w):
        node = AdjNode(j, w)
        node.next = graph.graph[i]
        graph.graph[i] = node
        node = AdjNode(i, w)
        node.next = graph.graph[j]
        graph.graph[j] = node

    # intra-AS cliques; router block of AS a starts at a * routers_per_as
    for a in range(n_as):
        base = a * routers_per_as
        for i in range(routers_per_as):
            for j in range(i + 1, routers_per_as):
                add_edge(base + i, base + j, rng.uniform(intra_lo, intra_hi))

    # AS-level edges: ring (connectivity) + random stub pairings to degree
    as_pairs = set()
    for a in range(n_as):
        b = (a + 1) % n_as
        as_pairs.add((a, b) if a < b else (b, a))
    stubs = [a for a in range(n_as) for _ in range(as_degree - 2)]
    rng.shuffle(stubs)
    dropped_stubs = 0
    for k in range(0, len(stubs) - 1, 2):
        a, b = stubs[k], stubs[k + 1]
        if a == b:
            dropped_stubs += 2
            continue
        key = (a, b) if a < b else (b, a)
        if key in as_pairs:
            dropped_stubs += 2
            continue
        as_pairs.add(key)

    for (a, b) in as_pairs:
        ra = a * routers_per_as + rng.randrange(routers_per_as)
        rb = b * routers_per_as + rng.randrange(routers_per_as)
        add_edge(ra, rb, rng.uniform(inter_lo, inter_hi))

    stats = {
        "n": n,
        "n_as": n_as,
        "routers_per_as": routers_per_as,
        "as_edges": len(as_pairs),
        "dropped_stubs": dropped_stubs,
        "expected_intra_edges": n_as * routers_per_as * (routers_per_as - 1) // 2,
        "seed": seed,
    }
    return graph, stats

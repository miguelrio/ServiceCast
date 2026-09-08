"""A faster Dijkstra engine for Graph.dijkstra_algorithm.

The original implementation in Graph.py (still the default, unchanged) picks
each next-closest node by scanning every unvisited node -- O(N^2) per source,
O(N^3) across a full all-nodes table build. This module provides a drop-in
binary-heap version with the SAME return contract:

    {'source': start_node,
     'shortest_path': {node_name: distance},        # inf when unreachable
     'previous_nodes': {node_name: previous_name}}  # only improved nodes

Select it with Graph.dijkstra_backend = "python" (or the SC_DIJKSTRA env
var). The graph's adjacency is read through the same duck-typed interface the
original used (nodes() / neighbours() / weight()), so both Graph and Network
objects work; it is read once per network and cached on the object.

Identical results, including tie-breaks: the original scan settles the first
node (lowest index in nodes() order) among those with minimal tentative
distance, so the heap here is ordered by the pair (distance, node index) and
relaxes with strict <. Equal-cost paths therefore resolve to the same tree as
the original implementation, and the forwarding / latency tables built from
these dicts are identical entry for entry.
"""

import heapq

INF = float("inf")


def _adjacency(graph, use_weights):
    """Read the graph's adjacency once and cache it on the object.

    Returns (names, idx, adj) where adj[v] is a list of (neighbour_index,
    weight) with weight 1 in min-hop mode (weights are not even read then,
    matching the original engine's `next = 1` shortcut).
    """
    mode = bool(use_weights)
    key = (mode, len(graph), len(getattr(graph, "links", None) or ()))
    cache = graph.__dict__.get("_sc_dijkstra_adj")
    if cache is not None and cache["key"] == key:
        return cache["names"], cache["idx"], cache["adj"]

    names = list(graph.nodes())
    idx = {name: i for i, name in enumerate(names)}
    adj = []
    for u in names:
        if mode:
            entry = [(idx[v], graph.weight(u, v)) for v in graph.neighbours(u)]
        else:
            entry = [(idx[v], 1) for v in graph.neighbours(u)]
        adj.append(entry)

    graph.__dict__["_sc_dijkstra_adj"] = {
        "key": key, "names": names, "idx": idx, "adj": adj,
    }
    return names, idx, adj


def dijkstra(graph, start_node, use_weights):
    """Binary-heap Dijkstra returning the original dict contract."""
    names, idx, adj = _adjacency(graph, use_weights)
    if start_node not in idx:
        raise ValueError(f"dijkstra: unknown start node {start_node!r}")
    src = idx[start_node]
    n = len(names)

    dist = [INF] * n
    prev = [-1] * n
    dist[src] = 0
    heap = [(0, src)]
    push, pop = heapq.heappush, heapq.heappop
    while heap:
        d, v = pop(heap)
        if d > dist[v]:
            continue                # stale queue entry
        for u, w in adj[v]:
            nd = d + w
            if nd < dist[u]:
                dist[u] = nd
                prev[u] = v
                push(heap, (nd, u))

    # pack into the original name-keyed dicts
    if use_weights:
        shortest_path = {names[i]: (INF if d == INF else d)
                         for i, d in enumerate(dist)}
    else:
        # the original engine sums hop counts as ints; keep that exact type
        shortest_path = {names[i]: (INF if d == INF else int(d))
                         for i, d in enumerate(dist)}
    previous_nodes = {names[v]: names[p]
                      for v, p in enumerate(prev) if p >= 0}
    return {"source": start_node,
            "shortest_path": shortest_path,
            "previous_nodes": previous_nodes}

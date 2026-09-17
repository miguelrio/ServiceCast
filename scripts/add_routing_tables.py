#!/usr/bin/env python3
"""
Add routing tables to router nodes in a GML topology.

For every router node, and for every destination node, computes:
  - the next-hop neighbor label on the shortest (minimum total delay) path
    from the router towards the destination
  - the total delay (ms) of that path

By default destinations are server nodes only. Pass --all-destinations to
also compute router-to-router entries (destinations = every router + server).

Approach: run one Dijkstra per destination (not all-pairs from every node),
using the destinations as sources over the undirected graph, then read off
next-hop = predecessor in each destination's shortest-path tree. With the
default (servers only) this is O(S * (V + E) log V) instead of O(V^2), which
matters for large topologies with few servers. --all-destinations instead
runs one tree per node (O(V * (V + E) log V)) and the output grows to
roughly V^2 lines, so it can be very expensive/large on big topologies -
there is no automatic size guard, use your judgment on the graph's actual
size before passing it. Either way, the Dijkstra runs happen inside
scipy.sparse.csgraph.dijkstra (compiled C, one call per set of source trees)
rather than a pure-Python heap loop.

Edge weights:
  - if the edge has a `delayMs` attribute, use it directly
  - otherwise, compute great-circle distance between the two endpoints'
    Latitude/Longitude (km) and convert at 0.009 ms/km

Only router<->router edges and server<->router ("hosts") edges are used to
build the routable graph; client nodes and client-related edges (access,
demand) are ignored, since routing tables are only requested for routers
reaching servers (and, with --all-destinations, other routers).

Output: a new GML file, with each router node gaining two attribute lines per
destination:
    nextHop "<destinationLabel>" "<neighbor label>"
    delayMs "<destinationLabel>" <total delay>
(omitted for a destination unreachable from that router). Note this two-
value-per-line form is not standard GML (GML only defines one value per
key), so generic GML readers (networkx, igraph, ...) will not parse these
lines.

Requires numpy + scipy (see the project .venv: .venv/bin/python3 add_routing_tables.py ...).
"""
import argparse
import os
import re
import sys
import time

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra as scipy_dijkstra

KM_PER_DEGREE_DELAY_MS_PER_KM = 0.009
EARTH_RADIUS_KM = 6371.0

ROUTER_ROUTER_EDGE_TYPES = {"internal", "p2p", "c2p"}
SERVER_ROUTER_EDGE_TYPES = {"hosts"}


def parse_gml(path):
    """Single-pass line parser tailored to this GML's `key value` / `key "value"`
    style. Returns (nodes, edges, node_line_ranges) where node_line_ranges maps
    node id -> (start_line_idx, end_line_idx) of its block in the raw file,
    for later in-place attribute insertion."""
    with open(path, "r") as f:
        lines = f.readlines()

    nodes = {}  # id -> dict of attrs
    edges = []  # list of dicts: source, target, type, delayMs
    node_blocks = {}  # id -> (start_idx, end_idx) inclusive, end_idx is the line with the closing ']'

    i = 0
    n = len(lines)
    kv_re = re.compile(r'^\s*(\w+)\s+(.+?)\s*$')

    while i < n:
        stripped = lines[i].strip()
        if stripped == "node [":
            start = i
            attrs = {}
            j = i + 1
            depth = 1
            while j < n:
                s = lines[j].strip()
                if s.endswith("["):
                    depth += 1
                elif s == "]":
                    depth -= 1
                    if depth == 0:
                        break
                else:
                    m = kv_re.match(lines[j])
                    if m:
                        key, val = m.group(1), m.group(2)
                        attrs[key] = _coerce(val)
                j += 1
            end = j
            node_id = attrs.get("id")
            nodes[node_id] = attrs
            node_blocks[node_id] = (start, end)
            i = end + 1
            continue
        elif stripped == "edge [":
            j = i + 1
            depth = 1
            attrs = {}
            while j < n:
                s = lines[j].strip()
                if s.endswith("["):
                    depth += 1
                elif s == "]":
                    depth -= 1
                    if depth == 0:
                        break
                else:
                    m = kv_re.match(lines[j])
                    if m:
                        key, val = m.group(1), m.group(2)
                        attrs[key] = _coerce(val)
                j += 1
            edges.append(attrs)
            i = j + 1
            continue
        else:
            i += 1

    return lines, nodes, edges, node_blocks


def _coerce(raw):
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    try:
        if "." in raw or "e" in raw.lower():
            return float(raw)
        return int(raw)
    except ValueError:
        return raw


def build_sparse_graph(nodes, edges):
    """Build a symmetric weighted adjacency matrix (CSR) over all node ids,
    plus the id<->matrix-index mappings. Vectorized: edge weights for the
    Euclidean-fallback case are computed for all such edges at once with
    numpy rather than one Python call per edge, which matters at 10^5+ scale.
    """
    node_ids = list(nodes.keys())
    id_to_idx = {nid: i for i, nid in enumerate(node_ids)}
    n = len(node_ids)

    routable_edges = [
        e
        for e in edges
        if e.get("type") in ROUTER_ROUTER_EDGE_TYPES or e.get("type") in SERVER_ROUTER_EDGE_TYPES
    ]
    routable_edges = [
        e
        for e in routable_edges
        if e.get("source") in nodes
        and e.get("target") in nodes
        and nodes[e["source"]].get("type") != "client"
        and nodes[e["target"]].get("type") != "client"
    ]

    src_ids = np.fromiter((e["source"] for e in routable_edges), dtype=np.int64, count=len(routable_edges))
    dst_ids = np.fromiter((e["target"] for e in routable_edges), dtype=np.int64, count=len(routable_edges))

    has_delay = np.fromiter(("delayMs" in e for e in routable_edges), dtype=bool, count=len(routable_edges))
    weights = np.empty(len(routable_edges), dtype=np.float64)
    weights[has_delay] = np.fromiter(
        (float(e["delayMs"]) for e in routable_edges if "delayMs" in e), dtype=np.float64, count=int(has_delay.sum())
    )

    if (~has_delay).any():
        no_delay_edges = [e for e, hd in zip(routable_edges, has_delay) if not hd]
        lat1 = np.array([nodes[e["source"]]["Latitude"] for e in no_delay_edges])
        lon1 = np.array([nodes[e["source"]]["Longitude"] for e in no_delay_edges])
        lat2 = np.array([nodes[e["target"]]["Latitude"] for e in no_delay_edges])
        lon2 = np.array([nodes[e["target"]]["Longitude"] for e in no_delay_edges])
        weights[~has_delay] = haversine_km_vec(lat1, lon1, lat2, lon2) * KM_PER_DEGREE_DELAY_MS_PER_KM

    row = np.fromiter((id_to_idx[i] for i in src_ids), dtype=np.int64, count=len(src_ids))
    col = np.fromiter((id_to_idx[i] for i in dst_ids), dtype=np.int64, count=len(dst_ids))

    # Store each undirected edge once; scipy's dijkstra(directed=False)
    # treats csgraph[i, j] and csgraph[j, i] as the same edge.
    graph = coo_matrix((weights, (row, col)), shape=(n, n)).tocsr()
    return graph, node_ids, id_to_idx


def print_progress(label, done, total, start_time):
    bar_len = 30
    pct = done / total if total else 1.0
    filled = int(bar_len * pct)
    bar = "#" * filled + "-" * (bar_len - filled)
    elapsed = time.perf_counter() - start_time
    end = "\n" if done >= total else ""
    print(
        f"\r{label} [{bar}] {done}/{total} ({pct * 100:5.1f}%) {elapsed:6.1f}s",
        end=end,
        file=sys.stderr,
        flush=True,
    )


def haversine_km_vec(lat1, lon1, lat2, lon2):
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.minimum(1.0, np.sqrt(a)))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input_gml")
    ap.add_argument("-o", "--output", required=True, help="output path for the new GML (input is never modified)")
    ap.add_argument(
        "--all-destinations",
        action="store_true",
        help=(
            "Compute routing table entries to every router as well as every server "
            "(instead of servers only). Runs one Dijkstra tree per node in the graph "
            "rather than per server, and the output grows to ~V^2 lines, so this can "
            "be very expensive/large on big topologies. No size guard is applied; "
            "use at your own judgment on the graph's actual size."
        ),
    )
    args = ap.parse_args()
    run_start = time.perf_counter()

    if os.path.abspath(args.output) == os.path.abspath(args.input_gml):
        print("Refusing to overwrite the input file; pass a different -o path.", file=sys.stderr)
        sys.exit(1)

    lines, nodes, edges, node_blocks = parse_gml(args.input_gml)

    router_ids = [nid for nid, a in nodes.items() if a.get("type") == "router"]
    server_ids = [nid for nid, a in nodes.items() if a.get("type") == "server"]

    if not server_ids:
        print("No server nodes found; nothing to do.", file=sys.stderr)
        sys.exit(1)

    if args.all_destinations:
        # Destinations = every non-client node (routers + servers), so each
        # router also gets entries for reaching every other router.
        destination_ids = router_ids + server_ids
    else:
        destination_ids = server_ids

    graph, node_id_list, id_to_idx = build_sparse_graph(nodes, edges)

    # Run the shortest-path computation in chunks of destinations (rather
    # than one call for all of them) purely so we can report progress;
    # each chunk is still a single vectorized scipy call covering many
    # source trees at once. With --all-destinations this is one Dijkstra
    # tree per node instead of per server, so cost scales with total node
    # count, not just server count.
    dest_indices = np.array([id_to_idx[did] for did in destination_ids], dtype=np.int64)
    n_dest = len(dest_indices)
    num_chunks = min(n_dest, 100)
    chunk_size = (n_dest + num_chunks - 1) // num_chunks

    dijkstra_start = time.perf_counter()
    dist_chunks = []
    pred_chunks = []
    print_progress("Computing shortest paths", 0, n_dest, dijkstra_start)
    for start in range(0, n_dest, chunk_size):
        chunk = dest_indices[start : start + chunk_size]
        d_chunk, p_chunk = scipy_dijkstra(graph, directed=False, indices=chunk, return_predecessors=True)
        dist_chunks.append(d_chunk)
        pred_chunks.append(p_chunk)
        print_progress("Computing shortest paths", min(start + chunk_size, n_dest), n_dest, dijkstra_start)
    dist_matrix = np.vstack(dist_chunks)
    predecessors = np.vstack(pred_chunks)

    router_indices = np.array([id_to_idx[rid] for rid in router_ids], dtype=np.int64)
    labels = [nodes[nid].get("label", str(nid)) for nid in node_id_list]
    destination_labels = [nodes[did].get("label", str(did)) for did in destination_ids]

    # routing_tables[router_id] = list of (destination_label, next_hop_label, delay_ms)
    routing_tables = {rid: [] for rid in router_ids}
    build_start = time.perf_counter()
    progress_every = max(1, n_dest // 100)
    print_progress("Building routing tables", 0, n_dest, build_start)
    for d_i, destination_label in enumerate(destination_labels):
        preds_row = predecessors[d_i]
        dist_row = dist_matrix[d_i]
        pred_at_router = preds_row[router_indices]
        dist_at_router = dist_row[router_indices]
        reachable = pred_at_router != -9999  # excludes the destination itself when it's a router
        for rid, pred_idx, delay in zip(
            (r for r, ok in zip(router_ids, reachable) if ok),
            pred_at_router[reachable],
            dist_at_router[reachable],
        ):
            routing_tables[rid].append((destination_label, labels[pred_idx], float(delay)))
        if (d_i + 1) % progress_every == 0 or d_i + 1 == n_dest:
            print_progress("Building routing tables", d_i + 1, n_dest, build_start)

    # Single forward pass over the file: right before a router's closing "]"
    # line, splice in its new attribute lines, then write that "]" line.
    # O(N + new_lines) instead of repeated in-place list insertion.
    insert_before = {}
    total_entries = 0
    for rid in router_ids:
        table = routing_tables[rid]
        if not table:
            continue
        table.sort(key=lambda t: t[0])
        new_lines = []
        for destination_label, next_hop_label, delay in table:
            new_lines.append(f'    nextHop "{destination_label}" "{next_hop_label}"\n')
            new_lines.append(f'    delayMs "{destination_label}" {delay:.6f}\n')
        _, end = node_blocks[rid]
        insert_before[end] = new_lines
        total_entries += len(table)

    with open(args.output, "w") as f:
        for i, line in enumerate(lines):
            extra = insert_before.get(i)
            if extra:
                f.writelines(extra)
            f.write(line)

    total_elapsed = time.perf_counter() - run_start
    print(
        f"Processed {len(router_ids)} routers, {len(destination_ids)} destinations "
        f"({'all routers + servers' if args.all_destinations else 'servers only'}). "
        f"Wrote {total_entries} routing-table entries to {args.output} "
        f"in {total_elapsed:.2f}s."
    )


if __name__ == "__main__":
    main()

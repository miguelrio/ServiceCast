#!/usr/bin/env python3
"""
Add routing tables to router nodes in a GML topology.

For every router node, and for every destination node, computes:
  - the next-hop neighbor label on the selected route from the router
    towards the destination
  - the total delay (ms) of that route

By default destinations are server nodes only. Pass --all-destinations to
also compute router-to-router entries (destinations = every router + server).

Routing policy (valley-free / Gao-Rexford):
  Inter-AS edges carry a business relationship: `c2p` (customer-provider)
  or `p2p` (settlement-free peering). Routes are only allowed to follow
  valley-free paths, i.e. zero or more customer->provider hops, then at most
  one peer-peer hop, then zero or more provider->customer hops (`internal`
  edges inside an AS may appear anywhere). Paths that go down to a customer
  and back up again, or use a peering link as transit, are never selected.

  Because tables are destination-based (each hop forwards using its *own*
  entry), picking the shortest valley-free path independently per router is
  not enough: router A may pick a peer B expecting B to go down, while B's
  own shortest route goes up to its provider. To keep hop-by-hop forwarding
  valley-free, route selection follows the standard Gao-Rexford model:
    1. prefer customer routes (reach the destination using only internal and
       provider->customer edges), then peer routes, then provider routes;
    2. among routes of the best class, pick the minimum total delay;
    3. a router only learns routes a neighbor would export to it: customer
       routes are exported to everyone, peer/provider routes only to
       customers (and internally within the AS).
  A router with no valley-free route to a destination gets no entry for it.
  Pass --ignore-policy for the old plain shortest-path behaviour.

  The `c2p` edge direction differs between generators (the synthetic
  topologies store customer->provider, the CAIDA-derived one stores
  provider->customer, as in CAIDA's as-rel `provider|customer|-1`). By default
  it is auto-detected from the nodes' `tier` attribute (stub < transit <
  tier1); override with --c2p-orientation.

Approach: per destination, three Dijkstra passes over directed "who learns
from whom" graphs (customer routes, then peer routes seeded from customer
routes, then provider routes seeded from everything already routed), each
run inside scipy.sparse.csgraph.dijkstra (compiled C). The next hop is the
neighbor a router learned its route from. The customer-route pass is batched
over chunks of destinations; the peer/provider passes run per destination.
--all-destinations runs this once per node and the output grows to roughly
V^2 lines, so it can be very expensive/large on big topologies - there is no
automatic size guard, use your judgment on the graph's actual size.

Edge weights:
  - if the edge has a `delayMs` attribute, use it directly
  - otherwise, compute great-circle distance between the two endpoints'
    Latitude/Longitude (km) and convert at 0.009 ms/km

Only router<->router edges and server<->router ("hosts") edges are used to
build the routable graph; client nodes and client-related edges (access,
demand) are ignored, since routing tables are only requested for routers
reaching servers (and, with --all-destinations, other routers). Servers are
only ever the last hop, never transit.

Output: a new GML file, with each router node gaining two attribute lines per
destination:
    nextHop "<destinationLabel>" "<neighbor label>"
    delayMs "<destinationLabel>" <total delay ms>
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
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra as scipy_dijkstra

KM_PER_DEGREE_DELAY_MS_PER_KM = 0.009
EARTH_RADIUS_KM = 6371.0

ROUTER_ROUTER_EDGE_TYPES = {"internal", "p2p", "c2p"}
SERVER_ROUTER_EDGE_TYPES = {"hosts"}

# The engine's default link weight (src/Graph.py: Graph.default_propagation_delay,
# set to 100 ms by experiments/main_precomputed_t1.py; all delays are ms, see
# src/units.py). Used for edges touching an Internal-0 node and for 0 delayMs,
# mirroring the engine exactly.
ENGINE_DEFAULT_PROPAGATION_DELAY = 100

TIER_RANK = {"stub": 0, "transit": 1, "tier1": 2}
C2P_ORIENTATIONS = ("customer-provider", "provider-customer")

# Route classes, in order of preference.
ROUTE_NONE, ROUTE_CUSTOMER, ROUTE_PEER, ROUTE_PROVIDER = 0, 1, 2, 3
ROUTE_CLASS_NAMES = {ROUTE_CUSTOMER: "customer", ROUTE_PEER: "peer", ROUTE_PROVIDER: "provider"}

NO_PRED = -9999  # scipy's "no predecessor" marker


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


def edge_weights(nodes, edges):
    """Delay (ms) of each edge. Vectorized: edge weights for the
    Euclidean-fallback case are computed for all such edges at once with
    numpy rather than one Python call per edge, which matters at 10^5+ scale.

    Weights mirror the engine's link rule exactly (src/Gml.py edge parsing +
    src/Network.from_graph): an edge touching an Internal-0 node (every
    server/client attachment) keeps Graph.default_propagation_delay regardless
    of any delayMs on the edge, and a 0 delayMs is replaced by the default as
    well. Tables must use the same weights the engine puts on links, otherwise
    accumulated announcement delay can exceed the table-derived diameter and
    crash MetricUtility's 0..1 range check.
    """
    has_delay = np.fromiter(("delayMs" in e for e in edges), dtype=bool, count=len(edges))
    weights = np.empty(len(edges), dtype=np.float64)
    weights[has_delay] = np.fromiter(
        (float(e["delayMs"]) for e in edges if "delayMs" in e), dtype=np.float64, count=int(has_delay.sum())
    )

    # engine: Network.from_graph replaces a 0 weight with the default
    zero_delay = np.zeros(len(edges), dtype=bool)
    zero_delay[has_delay] = weights[has_delay] == 0.0
    weights[zero_delay] = ENGINE_DEFAULT_PROPAGATION_DELAY

    # engine: Gml edge weight stays at the default when either endpoint is
    # external (Internal 0) -- delayMs is never read for those edges
    def touches_external(e):
        return int(nodes[e["source"]].get("Internal", 1)) == 0 or int(nodes[e["target"]].get("Internal", 1)) == 0

    external = np.fromiter((touches_external(e) for e in edges), dtype=bool, count=len(edges))
    weights[external] = ENGINE_DEFAULT_PROPAGATION_DELAY

    if (~has_delay & ~external).any():
        no_delay_edges = [e for e, hd, ex in zip(edges, has_delay, external) if not hd and not ex]
        lat1 = np.array([nodes[e["source"]]["Latitude"] for e in no_delay_edges])
        lon1 = np.array([nodes[e["source"]]["Longitude"] for e in no_delay_edges])
        lat2 = np.array([nodes[e["target"]]["Latitude"] for e in no_delay_edges])
        lon2 = np.array([nodes[e["target"]]["Longitude"] for e in no_delay_edges])
        weights[~has_delay & ~external] = haversine_km_vec(lat1, lon1, lat2, lon2) * KM_PER_DEGREE_DELAY_MS_PER_KM
    return weights


def detect_c2p_orientation(nodes, c2p_edges):
    """Guess whether `c2p` edges are stored customer->provider or
    provider->customer by comparing endpoint tiers (stub < transit < tier1)."""
    up = down = 0
    for e in c2p_edges:
        rs = TIER_RANK.get(nodes[e["source"]].get("tier"))
        rt = TIER_RANK.get(nodes[e["target"]].get("tier"))
        if rs is None or rt is None or rs == rt:
            continue
        if rs < rt:
            up += 1
        else:
            down += 1
    if up == down:
        print(
            "Cannot auto-detect c2p edge orientation from node tiers; pass --c2p-orientation.",
            file=sys.stderr,
        )
        sys.exit(1)
    orientation = "customer-provider" if up > down else "provider-customer"
    minority = min(up, down)
    print(
        f"c2p orientation: {orientation} (auto-detected from tiers: {max(up, down)} edges agree, "
        f"{minority} disagree)",
        file=sys.stderr,
    )
    if minority > 0.05 * (up + down):
        print("Warning: tier-based c2p orientation is ambiguous; consider passing --c2p-orientation.", file=sys.stderr)
    return orientation


def classify_edges(nodes, edges, id_to_idx, c2p_orientation):
    """Split the routable edges by relationship, as arrays of matrix indices
    plus weights:
        internal: (a, b, w)            undirected, same AS
        c2p:      (customer, provider, w)
        p2p:      (a, b, w)            undirected
        hosts:    (server, router, w)
    """
    routable = [
        e
        for e in edges
        if (e.get("type") in ROUTER_ROUTER_EDGE_TYPES or e.get("type") in SERVER_ROUTER_EDGE_TYPES)
        and e.get("source") in nodes
        and e.get("target") in nodes
        and nodes[e["source"]].get("type") != "client"
        and nodes[e["target"]].get("type") != "client"
    ]
    if c2p_orientation == "auto":
        c2p_orientation = detect_c2p_orientation(nodes, [e for e in routable if e["type"] == "c2p"])

    weights = edge_weights(nodes, routable)
    src = np.fromiter((id_to_idx[e["source"]] for e in routable), dtype=np.int64, count=len(routable))
    dst = np.fromiter((id_to_idx[e["target"]] for e in routable), dtype=np.int64, count=len(routable))
    etype = np.array([e["type"] for e in routable], dtype=object)
    src_is_server = np.fromiter(
        (nodes[e["source"]].get("type") == "server" for e in routable), dtype=bool, count=len(routable)
    )
    dst_is_server = np.fromiter(
        (nodes[e["target"]].get("type") == "server" for e in routable), dtype=bool, count=len(routable)
    )

    def pick(mask, a, b):
        return a[mask], b[mask], weights[mask]

    c2p = etype == "c2p"
    if c2p_orientation == "customer-provider":
        c2p_arrays = pick(c2p, src, dst)
    else:
        c2p_arrays = pick(c2p, dst, src)

    # A hosts edge is only usable as the final router->server hop; skip any
    # that do not connect exactly one server to one non-server.
    hosts = etype == "hosts"
    hosts_fwd = hosts & src_is_server & ~dst_is_server
    hosts_rev = hosts & dst_is_server & ~src_is_server
    hs1, hr1, hw1 = pick(hosts_fwd, src, dst)
    hs2, hr2, hw2 = pick(hosts_rev, dst, src)

    return {
        "internal": pick(etype == "internal", src, dst),
        "c2p": c2p_arrays,
        "p2p": pick(etype == "p2p", src, dst),
        "hosts": (np.concatenate([hs1, hs2]), np.concatenate([hr1, hr2]), np.concatenate([hw1, hw2])),
    }


def directed_csr(src, dst, w, n):
    """Directed CSR adjacency; parallel edges keep the minimum weight (a plain
    COO->CSR conversion would sum them). Explicit zero weights stay edges."""
    order = np.lexsort((w, dst, src))
    src, dst, w = src[order], dst[order], w[order]
    keep = np.ones(len(src), dtype=bool)
    keep[1:] = (src[1:] != src[:-1]) | (dst[1:] != dst[:-1])
    return csr_matrix((w[keep], (src[keep], dst[keep])), shape=(n, n))


class PolicyRouting:
    """Gao-Rexford route computation. All graphs are in the "learning"
    direction: an edge y -> x means x may use a route it learned from y, so
    the Dijkstra predecessor of x is x's next hop towards the destination."""

    def __init__(self, classified, n, ignore_policy=False):
        self.n = n
        ia, ib, iw = classified["internal"]
        cc, cp, cw = classified["c2p"]
        pa, pb, pw = classified["p2p"]
        hs, hr, hw = classified["hosts"]
        self.ignore_policy = ignore_policy

        # Internal edges propagate any route class within the AS.
        self.int_src = np.concatenate([ia, ib])
        self.int_dst = np.concatenate([ib, ia])
        self.int_w = np.concatenate([iw, iw])
        # Peers learn each other's customer routes only.
        self.peer_from = np.concatenate([pa, pb])
        self.peer_to = np.concatenate([pb, pa])
        self.peer_w = np.concatenate([pw, pw])
        # Customers learn every route of their providers.
        self.down_from, self.down_to, self.down_w = cp, cc, cw

        # Customer-route graph: internal edges, provider learns from customer,
        # hosting router learns from the server.
        c_src = [self.int_src, cc, hs]
        c_dst = [self.int_dst, cp, hr]
        c_w = [self.int_w, cw, hw]
        if ignore_policy:
            # Plain shortest paths: every router-router edge in both directions.
            c_src += [cp, self.peer_from]
            c_dst += [cc, self.peer_to]
            c_w += [cw, self.peer_w]
        self.graph_c = directed_csr(np.concatenate(c_src), np.concatenate(c_dst), np.concatenate(c_w), n)

    def customer_routes(self, dest_indices):
        return scipy_dijkstra(self.graph_c, directed=True, indices=dest_indices, return_predecessors=True)

    def complete(self, dist_c, pred_c):
        """Given one destination's customer-route tree, add peer and provider
        routes. Returns (dist, next_hop, route_class) arrays over all nodes."""
        dist = dist_c.copy()
        next_hop = pred_c.astype(np.int64)
        route_class = np.where(np.isfinite(dist), ROUTE_CUSTOMER, ROUTE_NONE)
        if self.ignore_policy:
            return dist, next_hop, route_class

        # Peer routes: learned over a p2p edge from a neighbor holding a
        # customer route (at this point every routed node is a customer
        # route), then spread over internal edges.
        routed = np.isfinite(dist)
        ok = routed[self.peer_from] & ~routed[self.peer_to]
        self._extend(
            dist, next_hop, route_class, ROUTE_PEER,
            self.peer_to[ok], self.peer_from[ok], self.peer_w[ok] + dist[self.peer_from[ok]],
            self.int_src, self.int_dst, self.int_w,
        )

        # Provider routes: learned from a provider holding any route, then
        # spread over internal edges and further down to customers.
        routed = np.isfinite(dist)
        seed = routed[self.down_from] & ~routed[self.down_to]
        chain = ~routed[self.down_from] & ~routed[self.down_to]
        self._extend(
            dist, next_hop, route_class, ROUTE_PROVIDER,
            self.down_to[seed], self.down_from[seed], self.down_w[seed] + dist[self.down_from[seed]],
            np.concatenate([self.int_src, self.down_from[chain]]),
            np.concatenate([self.int_dst, self.down_to[chain]]),
            np.concatenate([self.int_w, self.down_w[chain]]),
        )
        return dist, next_hop, route_class

    def _extend(self, dist, next_hop, route_class, cls, seed_to, seed_via, seed_cost, prop_src, prop_dst, prop_w):
        """Multi-source Dijkstra from seed costs (via a virtual super-source
        node), propagating over prop edges; fills in still-unrouted nodes."""
        if seed_to.size == 0:
            return
        n = self.n
        # Best seed per node (lowest cost).
        order = np.lexsort((seed_cost, seed_to))
        seed_to, seed_via, seed_cost = seed_to[order], seed_via[order], seed_cost[order]
        first = np.ones(len(seed_to), dtype=bool)
        first[1:] = seed_to[1:] != seed_to[:-1]
        seed_to, seed_via, seed_cost = seed_to[first], seed_via[first], seed_cost[first]

        super_node = n
        graph = directed_csr(
            np.concatenate([prop_src, np.full(len(seed_to), super_node, dtype=np.int64)]),
            np.concatenate([prop_dst, seed_to]),
            np.concatenate([prop_w, seed_cost]),
            n + 1,
        )
        d, p = scipy_dijkstra(graph, directed=True, indices=super_node, return_predecessors=True)
        d, p = d[:n], p[:n].astype(np.int64)
        via = np.full(n, NO_PRED, dtype=np.int64)
        via[seed_to] = seed_via
        p = np.where(p == super_node, via, p)

        new = np.isfinite(d) & ~np.isfinite(dist)
        dist[new] = d[new]
        next_hop[new] = p[new]
        route_class[new] = cls


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
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input_gml")
    ap.add_argument("-o", "--output", required=True, help="output path for the new GML (input is never modified)")
    ap.add_argument(
        "--all-destinations",
        action="store_true",
        help=(
            "Compute routing table entries to every router as well as every server "
            "(instead of servers only). Runs the route computation once per node in the graph "
            "rather than per server, and the output grows to ~V^2 lines, so this can "
            "be very expensive/large on big topologies. No size guard is applied; "
            "use at your own judgment on the graph's actual size."
        ),
    )
    ap.add_argument(
        "--c2p-orientation",
        choices=("auto",) + C2P_ORIENTATIONS,
        default="auto",
        help=(
            "Direction in which `c2p` edges are stored (source->target). 'auto' (default) "
            "infers it from the nodes' tier attribute."
        ),
    )
    ap.add_argument(
        "--ignore-policy",
        action="store_true",
        help="Ignore business relationships and use plain shortest-delay paths (not valley-free).",
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

    node_id_list = list(nodes.keys())
    id_to_idx = {nid: i for i, nid in enumerate(node_id_list)}
    classified = classify_edges(
        nodes, edges, id_to_idx, "provider-customer" if args.ignore_policy else args.c2p_orientation
    )
    routing = PolicyRouting(classified, len(node_id_list), ignore_policy=args.ignore_policy)

    router_indices = np.array([id_to_idx[rid] for rid in router_ids], dtype=np.int64)
    router_id_set = set(router_ids)
    labels = [nodes[nid].get("label", str(nid)) for nid in node_id_list]
    destination_labels = [nodes[did].get("label", str(did)) for did in destination_ids]

    # Customer routes are computed in chunks of destinations (one vectorized
    # scipy call per chunk, covering many trees at once); peer and provider
    # routes are then filled in per destination. Chunking also lets us
    # report progress and bounds memory with --all-destinations.
    dest_indices = np.array([id_to_idx[did] for did in destination_ids], dtype=np.int64)
    n_dest = len(dest_indices)
    num_chunks = min(n_dest, 100)
    chunk_size = (n_dest + num_chunks - 1) // num_chunks

    # routing_tables[router_id] = list of (destination_label, next_hop_label, delay_ms)
    routing_tables = {rid: [] for rid in router_ids}
    class_counts = {c: 0 for c in ROUTE_CLASS_NAMES}
    no_route = 0
    compute_start = time.perf_counter()
    print_progress("Computing routes", 0, n_dest, compute_start)
    for start in range(0, n_dest, chunk_size):
        chunk = dest_indices[start : start + chunk_size]
        dist_c, pred_c = routing.customer_routes(chunk)
        for k in range(len(chunk)):
            d_i = start + k
            destination_label = destination_labels[d_i]
            dist, next_hop, route_class = routing.complete(dist_c[k], pred_c[k])
            nh_at_router = next_hop[router_indices]
            dist_at_router = dist[router_indices]
            cls_at_router = route_class[router_indices]
            reachable = nh_at_router != NO_PRED  # also excludes the destination itself when it's a router
            no_route += int((~reachable).sum()) - int(destination_ids[d_i] in router_id_set)
            for c in class_counts:
                class_counts[c] += int((cls_at_router[reachable] == c).sum())
            for rid, nh_idx, delay in zip(
                (r for r, ok in zip(router_ids, reachable) if ok),
                nh_at_router[reachable],
                dist_at_router[reachable],
            ):
                routing_tables[rid].append((destination_label, labels[nh_idx], float(delay)))
        print_progress("Computing routes", min(start + chunk_size, n_dest), n_dest, compute_start)

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
    if args.ignore_policy:
        print(f"Policy ignored (plain shortest paths); {no_route} router/destination pairs unreachable.")
    else:
        print(
            "Valley-free routes by class: "
            + ", ".join(f"{name} {class_counts[c]}" for c, name in ROUTE_CLASS_NAMES.items())
            + f"; {no_route} router/destination pairs have no valley-free route (omitted)."
        )


if __name__ == "__main__":
    main()

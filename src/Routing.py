# Routing tables computed with scipy's compiled Dijkstra.
#
# For every router and every server, the next hop and the total delay of the
# route the router uses towards that server. Routes follow the valley-free
# (Gao-Rexford) policy when links carry business relationships (c2p, p2p), and
# plain shortest-delay paths otherwise.
#
# Destination-based: one route computation per server over the whole network
# (not one per router), so the cost is about S x (V + E) log V.
#
# Valley-free route selection:
#   1. prefer customer routes (reach the server using only internal and
#      provider->customer links), then peer routes, then provider routes;
#   2. among routes of the best class, pick the minimum total delay;
#   3. a router only learns routes a neighbour would export to it: customer
#      routes are exported to everyone, peer/provider routes only to customers
#      (and internally within the AS).
#
# Links with no relationship type are `internal`: they carry every route
# class in both directions, so a topology with no typed links gets plain
# shortest-delay paths. Servers, clients and nodes marked Internal 0 in the
# GML are never used as transit (an Internal 0 router still announces the
# servers attached to it).
#
# The weights are the network's own link delays, so the tables always match
# the delays packets experience.

import sys
from collections import Counter

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra as scipy_dijkstra

from Verbose import Verbose

TIER_RANK = {"stub": 0, "transit": 1, "tier1": 2}
C2P_ORIENTATIONS = ("customer-provider", "provider-customer")

# Route classes, in order of preference.
ROUTE_NONE, ROUTE_CUSTOMER, ROUTE_PEER, ROUTE_PROVIDER = 0, 1, 2, 3
ROUTE_CLASS_NAMES = {ROUTE_CUSTOMER: "customer", ROUTE_PEER: "peer", ROUTE_PROVIDER: "provider"}

NO_PRED = -9999  # scipy's "no predecessor" marker


class Routing:
    # "valley_free": follow c2p/p2p relationships (Gao-Rexford)
    # "shortest":    ignore them, plain shortest-delay paths
    policy = "valley_free"

    # Direction in which `c2p` links are stored (GML source -> target):
    # "auto" infers it from the nodes' tier attribute (stub < transit < tier1)
    c2p_orientation = "auto"

    # servers per scipy call for the customer-route pass
    chunk_size = 32

    @classmethod
    def compute_tables(cls, network):
        """Compute and install, for every router, its unicast forwarding table
        and its latency_table row towards every server.

        A router with no route to a server gets no entry for it. Hosts get no
        tables: a host has one link, so it always sends to its router.
        Returns a dict of counts for reporting."""
        names = list(network.routers)          # every node, hosts included
        idx = {name: i for i, name in enumerate(names)}
        n = len(names)
        servers = set(network.servers)
        hosts = servers | set(network.clients)

        classified, counts = cls._classify(network, idx, servers, hosts)

        no_transit = np.zeros(n, dtype=bool)
        for name in network.external_nodes:
            if name in idx and name not in hosts:
                no_transit[idx[name]] = True
        counts["no_transit_routers"] = int(no_transit.sum())

        ignore_policy = cls.policy == "shortest"

        router_names = [name for name in names if name not in hosts]
        router_indices = np.array([idx[name] for name in router_names], dtype=np.int64)
        server_names = list(network.servers)
        server_indices = np.array([idx[name] for name in server_names], dtype=np.int64)

        # A no-transit router still announces the servers attached to it: those
        # servers are computed with that one router's flag cleared.
        hosting = dict(zip(classified["hosts"][0].tolist(), classified["hosts"][1].tolist()))
        groups = {}
        for col, s in enumerate(server_indices.tolist()):
            r = hosting.get(s)
            key = r if r is not None and no_transit[r] else None
            groups.setdefault(key, []).append(col)

        # next hop and delay, router x server
        next_hops = np.full((len(router_names), len(server_names)), NO_PRED, dtype=np.int32)
        delays = np.zeros((len(router_names), len(server_names)), dtype=np.float64)
        class_counts = np.zeros(4, dtype=np.int64)
        for origin, cols in groups.items():
            flags = no_transit
            if origin is not None:
                flags = no_transit.copy()
                flags[origin] = False
            routing = PolicyRouting(classified, n, flags, ignore_policy=ignore_policy)
            cols = np.array(cols, dtype=np.int64)
            for start in range(0, len(cols), cls.chunk_size):
                chunk_cols = cols[start:start + cls.chunk_size]
                dist_c, pred_c = routing.customer_routes(server_indices[chunk_cols])
                for k, col in enumerate(chunk_cols.tolist()):
                    dist, next_hop, route_class = routing.complete(dist_c[k], pred_c[k])
                    next_hops[:, col] = next_hop[router_indices]
                    delays[:, col] = dist[router_indices]
                    class_counts += np.bincount(route_class[router_indices], minlength=4)

        # install, one router at a time; tuples share the name strings
        entries = 0
        for i, rname in enumerate(router_names):
            row_hops = next_hops[i].tolist()
            row_delays = delays[i].tolist()
            fib = {}
            latency = {}
            for j, hop in enumerate(row_hops):
                if hop != NO_PRED:
                    sname = server_names[j]
                    delay = row_delays[j]
                    fib[sname] = (sname, names[hop], delay)
                    latency[sname] = delay
            network.routers[rname].unicast_forwarding_table = fib
            network.latency_table[rname] = latency
            entries += len(fib)

        counts["routers"] = len(router_names)
        counts["servers"] = len(server_names)
        counts["entries"] = entries
        counts["unreachable_pairs"] = len(router_names) * len(server_names) - entries
        for c, cname in ROUTE_CLASS_NAMES.items():
            counts[cname + "_routes"] = int(class_counts[c])

        if Verbose.level >= 0:
            print("Routing: {} tables, {} routers x {} servers, {} entries, {} pairs unreachable".format(
                cls.policy, counts["routers"], counts["servers"], entries, counts["unreachable_pairs"]))
        if counts.get("untyped_links_in_typed_topology") and Verbose.level >= 0:
            print("Routing: {} router links have no type in a topology with typed links; "
                  "treated as internal".format(counts["untyped_links_in_typed_topology"]))
        return counts

    @classmethod
    def _classify(cls, network, idx, servers, hosts):
        """Split the network's links by relationship, as arrays of node
        indices plus weights:
            internal: (a, b, w)            undirected
            c2p:      (customer, provider, w)
            p2p:      (a, b, w)            undirected
            hosts:    (server, router, w)
        Client links and host-host links carry no routes and are skipped."""
        lists = {"internal": [], "c2p": [], "p2p": [], "hosts": []}
        other_types = Counter()
        untyped = 0
        for link in network.links:
            a = link.link1.src_node.id()
            b = link.link2.src_node.id()
            w = link.link1.propagation_delay
            if a in hosts or b in hosts:
                if a in servers and b not in hosts:
                    lists["hosts"].append((idx[a], idx[b], w))
                elif b in servers and a not in hosts:
                    lists["hosts"].append((idx[b], idx[a], w))
                continue
            edge_type = network.link_types.get(network.link_key(a, b))
            kind = edge_type[0] if edge_type is not None else None
            if kind == "c2p":
                lists["c2p"].append((idx[edge_type[1]], idx[edge_type[2]], w))
            elif kind == "p2p":
                lists["p2p"].append((idx[a], idx[b], w))
            else:
                if kind is None:
                    untyped += 1
                elif kind != "internal":
                    other_types[kind] += 1
                lists["internal"].append((idx[a], idx[b], w))

        counts = {"links_" + k: len(v) for k, v in lists.items()}
        if lists["c2p"] or lists["p2p"]:
            counts["untyped_links_in_typed_topology"] = untyped
        if other_types:
            counts["other_link_types_as_internal"] = dict(other_types)

        orientation = cls.c2p_orientation
        if lists["c2p"] and cls.policy != "shortest":
            if orientation == "auto":
                orientation = cls._detect_c2p_orientation(network, lists["c2p"], idx)
            elif orientation not in C2P_ORIENTATIONS:
                raise ValueError("Routing.c2p_orientation must be 'auto' or one of {}".format(C2P_ORIENTATIONS))
        if orientation == "provider-customer":
            lists["c2p"] = [(b, a, w) for a, b, w in lists["c2p"]]
        counts["c2p_orientation"] = orientation

        def arrays(rows):
            if not rows:
                return (np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.float64))
            a, b, w = zip(*rows)
            return (np.array(a, dtype=np.int64), np.array(b, dtype=np.int64), np.array(w, dtype=np.float64))

        return {k: arrays(v) for k, v in lists.items()}, counts

    @staticmethod
    def _detect_c2p_orientation(network, c2p_rows, idx):
        """Whether c2p links are stored customer->provider or provider->customer,
        from the endpoints' tiers (stub < transit < tier1)."""
        names = {i: name for name, i in idx.items()}
        up = down = 0
        for a, b, _ in c2p_rows:
            ra = TIER_RANK.get(network.node_tiers.get(names[a]))
            rb = TIER_RANK.get(network.node_tiers.get(names[b]))
            if ra is None or rb is None or ra == rb:
                continue
            if ra < rb:
                up += 1
            else:
                down += 1
        if up == down:
            raise ValueError("Routing: cannot detect the c2p link direction from node tiers; "
                             "set Routing.c2p_orientation")
        orientation = "customer-provider" if up > down else "provider-customer"
        if min(up, down) > 0.05 * (up + down):
            print("Routing: warning: tier-based c2p direction is ambiguous ({} links agree, {} disagree); "
                  "consider setting Routing.c2p_orientation".format(max(up, down), min(up, down)), file=sys.stderr)
        return orientation


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
    the Dijkstra predecessor of x is x's next hop towards the destination.
    A node marked no_transit never passes a route on: every edge out of it
    is dropped, so it can learn routes but no one learns through it."""

    def __init__(self, classified, n, no_transit, ignore_policy=False):
        self.n = n
        self.ignore_policy = ignore_policy

        def passes(src, dst, w):
            ok = ~no_transit[src]
            return src[ok], dst[ok], w[ok]

        ia, ib, iw = classified["internal"]
        cc, cp, cw = classified["c2p"]
        pa, pb, pw = classified["p2p"]
        hs, hr, hw = classified["hosts"]

        # Internal links propagate any route class within the AS.
        self.int_src, self.int_dst, self.int_w = passes(
            np.concatenate([ia, ib]), np.concatenate([ib, ia]), np.concatenate([iw, iw]))
        # Peers learn each other's customer routes only.
        self.peer_from, self.peer_to, self.peer_w = passes(
            np.concatenate([pa, pb]), np.concatenate([pb, pa]), np.concatenate([pw, pw]))
        # Customers learn every route of their providers.
        self.down_from, self.down_to, self.down_w = passes(cp, cc, cw)

        # Customer-route graph: internal links, provider learns from customer,
        # hosting router learns from the server.
        up_src, up_dst, up_w = passes(cc, cp, cw)
        c_src = [self.int_src, up_src, hs]
        c_dst = [self.int_dst, up_dst, hr]
        c_w = [self.int_w, up_w, hw]
        if ignore_policy:
            # Plain shortest paths: every router-router link in both directions.
            c_src += [self.down_from, self.peer_from]
            c_dst += [self.down_to, self.peer_to]
            c_w += [self.down_w, self.peer_w]
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

        # Peer routes: learned over a p2p link from a neighbour holding a
        # customer route (at this point every routed node is a customer
        # route), then spread over internal links.
        routed = np.isfinite(dist)
        ok = routed[self.peer_from] & ~routed[self.peer_to]
        self._extend(
            dist, next_hop, route_class, ROUTE_PEER,
            self.peer_to[ok], self.peer_from[ok], self.peer_w[ok] + dist[self.peer_from[ok]],
            self.int_src, self.int_dst, self.int_w,
        )

        # Provider routes: learned from a provider holding any route, then
        # spread over internal links and further down to customers.
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

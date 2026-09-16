
# Compare routing/latency tables from the three table sources on the same
# topology:
#   A - engine Dijkstra, min-hop (the current simulator default)
#   B - engine Dijkstra, weighted (use_weights=True)
#   C - precomputed tables baked into the GML (scipy weighted, topology tool)
#
# Reports next-hop agreement and delay relations per (router, server) pair,
# plus diameter and client-row comparisons.
#
# Usage: PYTHONPATH=src python3 experiments/compare_table_sources.py \
#            <plain_gml> <baked_gml>

import sys

import simpy

from Graph import Graph
from Network import Network
from Server import Server


def build(gml_file, force_weighted=False):
    graph = Graph.from_gml_file(gml_file)
    env = simpy.Environment()
    if force_weighted:
        orig = Graph.dijkstra_algorithm
        Graph.dijkstra_algorithm = classmethod(
            lambda cls, g, start, use_weights=False: orig(g, start, True)
        )
    network = Network.from_graph(graph, env, drop_external=False)
    network.calculate_forwarding_tables()
    if force_weighted:
        Graph.dijkstra_algorithm = orig
    return network


def fib(net, router, server):
    table = net[router].get_unicast_forwarding_table()
    entry = table.get(server)
    return (entry[1], entry[2]) if entry else None


def compare(name, net_x, net_y, routers, servers):
    same_hop = 0
    pairs = 0
    ratios = []
    for r in routers:
        for s in servers:
            ex, ey = fib(net_x, r, s), fib(net_y, r, s)
            if ex is None or ey is None:
                continue
            pairs += 1
            if ex[0] == ey[0]:
                same_hop += 1
            # delay comparison via latency_table (the FIB weight field is a
            # hop count under min-hop Dijkstra, not a delay)
            dx = net_x.latency_table.get(r, {}).get(s)
            dy = net_y.latency_table.get(r, {}).get(s)
            if dx is not None and dy is not None and dy > 0:
                ratios.append(dx / dy)
    ratios.sort()
    n = len(ratios)
    print(f"{name}: pairs={pairs} next-hop agreement={same_hop}/{pairs}"
          f" ({100.0 * same_hop / pairs:.1f}%)" if pairs else f"{name}: no pairs")
    if n:
        print(f"    latency ratio X/Y: min={ratios[0]:.3f} median={ratios[n // 2]:.3f} "
              f"mean={sum(ratios) / n:.3f} max={ratios[-1]:.3f}")


def main():
    plain_gml, baked_gml = sys.argv[1], sys.argv[2]

    # config parity with experiments/main_precomputed_t1.py
    Graph.default_propagation_delay = 0.1
    Server.slots = 50

    net_a = build(plain_gml)                    # engine, min-hop
    net_b = build(plain_gml, force_weighted=True)  # engine, weighted
    net_c = build(baked_gml)                    # precomputed

    routers = [r for r in net_a.routers
               if net_a[r].__class__.__name__ == 'Router']
    servers = list(net_a.servers)
    print(f"topology: {len(routers)} routers, {len(servers)} servers, "
          f"{len(net_a.clients)} clients")

    compare("A engine min-hop  vs C precomputed", net_a, net_c, routers, servers)
    compare("B engine weighted vs C precomputed", net_b, net_c, routers, servers)
    compare("A engine min-hop  vs B engine weighted", net_a, net_b, routers, servers)

    print(f"diameter: A={net_a.network_diameter():.6f} "
          f"B={net_b.network_diameter():.6f} C={net_c.network_diameter():.6f}")

    # engine latency asymmetry, for reference
    asym = 0
    checked = 0
    for r in routers:
        row = net_a.latency_table.get(r, {})
        for s in servers:
            if s in row:
                rev = net_a.latency_table.get(s, {}).get(r)
                if rev is not None:
                    checked += 1
                    if abs(row[s] - rev) > 1e-9:
                        asym += 1
    print(f"engine A asymmetric (router,server) latencies: {asym}/{checked}")

    # client rows: engine vs derived
    for cname in net_a.clients:
        row_a = net_a.latency_table.get(cname, {})
        row_b = net_b.latency_table.get(cname, {})
        row_c = net_c.latency_table.get(cname, {})
        ra = [(s, row_a[s]) for s in servers if s in row_a]
        rb = [(s, row_b[s]) for s in servers if s in row_b]
        rc = [(s, row_c[s]) for s in servers if s in row_c]
        if ra and rc:
            diffs = [abs(x[1] - y[1]) for x, y in zip(ra, rc)]
            print(f"client {cname}: rows A={len(ra)} C={len(rc)} "
                  f"max|A-C|={max(diffs):.6f}")
        if rb and rc:
            diffs = [abs(x[1] - y[1]) for x, y in zip(rb, rc)]
            print(f"client {cname}: max|B-C|={max(diffs):.6f}")


if __name__ == "__main__":
    main()

# Tests for the routing tables computed by src/Routing.py.
# Run with:  PYTHONPATH=src python3 tests/test_routing.py
# (also runs under pytest)

import os
import random
import tempfile

import simpy

from Graph import Graph
from Network import Network
from Routing import Routing
from Verbose import Verbose

Verbose.level = -2


def gml_text(nodes, edges):
    """nodes: (label, attrs); edges: (source, target, attrs)"""
    ids = {label: i for i, (label, _) in enumerate(nodes)}
    out = ["graph [\n"]
    for label, attrs in nodes:
        out.append("  node [\n    id {}\n    label \"{}\"\n".format(ids[label], label))
        for k, v in attrs.items():
            out.append("    {} {}\n".format(k, '"{}"'.format(v) if isinstance(v, str) else v))
        out.append("  ]\n")
    for s, t, attrs in edges:
        out.append("  edge [\n    source {}\n    target {}\n".format(ids[s], ids[t]))
        for k, v in attrs.items():
            out.append("    {} {}\n".format(k, '"{}"'.format(v) if isinstance(v, str) else v))
        out.append("  ]\n")
    out.append("]\n")
    return "".join(out)


def load(nodes, edges):
    Graph.default_propagation_delay = 100   # ms (src/units.py)
    fd, path = tempfile.mkstemp(suffix=".gml")
    with os.fdopen(fd, "w") as f:
        f.write(gml_text(nodes, edges))
    try:
        network = Network.from_graph(Graph.from_gml_file(path), simpy.Environment(), drop_external=False)
    finally:
        os.remove(path)
    return network


def router(tier=None, **extra):
    attrs = {"type": "router"}
    if tier:
        attrs["tier"] = tier
    attrs.update(extra)
    return attrs


SERVER = {"type": "server", "Internal": 0}
CLIENT = {"type": "client", "Internal": 0}


def link(kind=None, delay=1.0):
    attrs = {"delayMs": delay}
    if kind:
        attrs["type"] = kind
    return attrs


def hop(network, r, s):
    return network[r].next_hop_to(s)


def delay(network, r, s):
    return network.latency_table[r].get(s) if network[r].next_hop_to(s) else None


# P is the provider of A and B; A peers with C, C peers with D; server s at A.
def valley_free_network():
    nodes = [("P", router("tier1")), ("A", router("stub")), ("B", router("stub")),
             ("C", router("stub")), ("D", router("stub")), ("s", SERVER)]
    edges = [("A", "P", link("c2p")), ("B", "P", link("c2p")),
             ("A", "C", link("p2p")), ("C", "D", link("p2p")),
             ("s", "A", link("hosts"))]
    network = load(nodes, edges)
    network.calculate_forwarding_tables()
    return network


def test_customer_provider_and_peer_routes():
    network = valley_free_network()
    assert hop(network, "A", "s") == "s"
    assert hop(network, "P", "s") == "A"      # customer route
    assert hop(network, "B", "s") == "P"      # provider route
    assert hop(network, "C", "s") == "A"      # peer route


def test_peer_link_is_not_transit():
    network = valley_free_network()
    # C only has a peer route, which it does not export to its peer D
    assert hop(network, "D", "s") is None
    assert "s" not in network.latency_table["D"]
    assert network.routing_counts["unreachable_pairs"] == 1
    assert network.routing_counts["unreachable_other"] == 1


def test_customer_route_preferred_over_cheaper_provider_route():
    # q is a customer of both Y and Z; Y is a customer of X; X is a customer of Z.
    # X: customer route X->Y->q costs 20, provider route X->Z->q costs 2.
    nodes = [("q", router("stub")), ("Y", router("transit")), ("X", router("transit")),
             ("Z", router("tier1")), ("s", SERVER)]
    edges = [("q", "Y", link("c2p", 10)), ("Y", "X", link("c2p", 10)),
             ("X", "Z", link("c2p", 1)), ("q", "Z", link("c2p", 1)),
             ("s", "q", link("hosts"))]
    network = load(nodes, edges)
    network.calculate_forwarding_tables()
    assert hop(network, "X", "s") == "Y"
    assert abs(delay(network, "X", "s") - 21.0) < 1e-9   # 10 + 10 + the 1 ms server link


def test_internal0_router_is_not_transit_but_reachable():
    # untyped: R1 - E - R2 is cheap but E is Internal 0; R1 - R2 is long
    nodes = [("R1", router()), ("R2", router()), ("E", router(Internal=0)), ("s", SERVER)]
    edges = [("R1", "E", link()), ("E", "R2", link()), ("R1", "R2", link(delay=10)),
             ("s", "R1", link())]
    network = load(nodes, edges)
    network.calculate_forwarding_tables()
    assert hop(network, "R2", "s") == "R1"
    assert hop(network, "E", "s") == "R1"
    assert network.routing_counts["no_transit_routers"] == 1


def test_server_on_internal0_router_is_reachable():
    # s is attached to the no-transit router E: E announces s, but still
    # carries nothing else (R2 reaches t at R1 over the long link)
    nodes = [("R1", router()), ("R2", router()), ("E", router(Internal=0)),
             ("s", SERVER), ("t", SERVER)]
    edges = [("R1", "E", link()), ("E", "R2", link()), ("R1", "R2", link(delay=10)),
             ("s", "E", link()), ("t", "R1", link())]
    network = load(nodes, edges)
    network.calculate_forwarding_tables()
    assert hop(network, "R1", "s") == "E"
    assert hop(network, "R2", "s") == "E"
    assert hop(network, "R2", "t") == "R1"
    assert network.routing_counts["unreachable_pairs"] == 0


def test_untyped_graph_matches_brute_force():
    rng = random.Random(7)
    names = ["r{}".format(i) for i in range(30)]
    edges = [(names[i], names[rng.randrange(i)], link(delay=round(rng.uniform(1, 20), 3)))
             for i in range(1, 30)]
    for _ in range(30):
        a, b = rng.sample(names, 2)
        if not any({a, b} == {x, y} for x, y, _ in edges):
            edges.append((a, b, link(delay=round(rng.uniform(1, 20), 3))))
    servers = ["s{}".format(i) for i in range(3)]
    for s in servers:
        edges.append((s, rng.choice(names), link()))
    nodes = [(r, router()) for r in names] + [(s, SERVER) for s in servers]
    network = load(nodes, edges)
    network.calculate_forwarding_tables()

    # Floyd-Warshall over the network's own link weights; hosts are never transit
    hosts = set(servers)
    every = names + servers
    inf = float("inf")
    dist = {a: {b: (0 if a == b else inf) for b in every} for a in every}
    weight = {}
    for l in network.links:
        a, b, w = l.link1.src_node.id(), l.link2.src_node.id(), l.link1.propagation_delay
        dist[a][b] = dist[b][a] = min(dist[a][b], w)
        weight[(a, b)] = weight[(b, a)] = w
    for k in names:
        for a in every:
            for b in every:
                if dist[a][k] + dist[k][b] < dist[a][b]:
                    dist[a][b] = dist[a][k] + dist[k][b]
    for r in names:
        for s in servers:
            assert abs(delay(network, r, s) - dist[r][s]) < 1e-9
            # the next hop is on a shortest path (link weights read from the
            # links: Network.weight returns 0 towards a host, a known bug)
            h = hop(network, r, s)
            rest = 0 if h == s else delay(network, h, s)
            assert abs(weight[(r, h)] + rest - dist[r][s]) < 1e-9


def test_network_built_in_code():
    Graph.default_propagation_delay = 100   # ms (src/units.py)
    network = Network(simpy.Environment())
    network.add_edge("a", "b", 1)
    network.add_edge("b", "c", 2)
    network.add_edge("a", "c", 5)
    network.add_server("s1", "c", 0.5)
    network.add_client("c1", "a", 0.25)
    network.calculate_forwarding_tables()
    assert hop(network, "a", "s1") == "b"
    assert abs(delay(network, "a", "s1") - 3.5) < 1e-9
    assert abs(network.latency_table["c1"]["s1"] - 3.75) < 1e-9
    assert abs(network.latency_table["s1"]["c1"] - 3.75) < 1e-9
    # the diameter includes the client's access link
    assert abs(network.network_diameter() - 3.75) < 1e-9


def test_equal_cost_ties_are_deterministic():
    nodes = [("a", router()), ("b", router()), ("c", router()), ("d", router()), ("s", SERVER)]
    edges = [("a", "b", link()), ("a", "c", link()), ("b", "d", link()), ("c", "d", link()),
             ("s", "d", link())]
    hops = set()
    for _ in range(3):
        network = load(nodes, edges)
        network.calculate_forwarding_tables()
        hops.add(hop(network, "a", "s"))
    assert len(hops) == 1 and hops <= {"b", "c"}


def test_undetectable_c2p_direction_is_an_error():
    nodes = [("a", router("stub")), ("b", router("stub")), ("s", SERVER)]
    edges = [("a", "b", link("c2p")), ("s", "a", link("hosts"))]
    network = load(nodes, edges)
    try:
        network.calculate_forwarding_tables()
    except ValueError:
        pass
    else:
        assert False, "expected ValueError"
    # forcing the direction works
    Routing.c2p_orientation = "customer-provider"
    try:
        network.calculate_forwarding_tables()
        assert hop(network, "b", "s") == "a"
    finally:
        Routing.c2p_orientation = "auto"


def load_with_cones(nodes, edges, cones):
    """A GML whose observedCones attribute names a sidecar written beside it;
    cones: {AS: [ASes of its observed cone]}"""
    Graph.default_propagation_delay = 100   # ms (src/units.py)
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "cones.txt"), "w") as f:
            f.write("# AS, then its observed cone\n")
            for asn, members in cones.items():
                f.write(" ".join([asn] + members) + "\n")
        path = os.path.join(tmp, "topology.gml")
        with open(path, "w") as f:
            f.write(gml_text(nodes, edges).replace("graph [\n", 'graph [\n  observedCones "cones.txt"\n', 1))
        network = Network.from_graph(Graph.from_gml_file(path), simpy.Environment(), drop_external=False)
    network.calculate_forwarding_tables()
    return network


# Q (AS 20) is a customer of P (AS 10) and of the tier-1 T (AS 1); P is a
# customer of T. Server s at Q. P's customer route to s is P -> Q.
def cone_network(p_cone):
    nodes = [("T", router("tier1", asId="1")), ("P", router("transit", asId="10")),
             ("Q", router("stub", asId="20")), ("s", SERVER)]
    edges = [("Q", "P", link("c2p")), ("P", "T", link("c2p")), ("Q", "T", link("c2p", 5)),
             ("s", "Q", link("hosts"))]
    return load_with_cones(nodes, edges, {"1": ["10", "20"], "10": p_cone})


def test_observed_cone_rule():
    # Q in P's observed cone: P keeps its customer route
    network = cone_network(["20"])
    assert network.routing_counts["observed_cones"]
    assert hop(network, "P", "s") == "Q"
    # Q not in it: P falls back to the provider route through T (a tier-1,
    # unrestricted), and T no longer learns a customer route through P
    network = cone_network([])
    assert hop(network, "P", "s") == "T"
    assert hop(network, "T", "s") == "Q"
    assert abs(delay(network, "P", "s") - 7.0) < 1e-9   # 1 + 5 + the 1 ms server link
    # the rule can be turned off
    Routing.observed_cones = False
    try:
        network = cone_network([])
        assert hop(network, "P", "s") == "Q"
    finally:
        Routing.observed_cones = True


def test_crossing_delay():
    # A - X - B, X carries internalDelayMs 2.5; the direct A - B link costs 3.
    # Servers s at B and x at X.
    nodes = [("A", router()), ("X", router(internalDelayMs=2.5)), ("B", router()),
             ("s", SERVER), ("x", SERVER)]
    edges = [("A", "X", link()), ("X", "B", link()), ("A", "B", link(delay=3.5)),
             ("s", "B", link()), ("x", "X", link())]
    network = load(nodes, edges)
    network.calculate_forwarding_tables()
    # through X: 1 + 2.5 + 1 = 4.5 > 3.5 direct, so A goes direct
    assert hop(network, "A", "s") == "B"
    assert abs(delay(network, "A", "s") - 4.5) < 1e-9          # 3.5 + 1 ms server link
    # a route starting at X does not pay for X; neither does one ending at X
    assert abs(delay(network, "X", "s") - 2.0) < 1e-9
    assert abs(delay(network, "A", "x") - 2.0) < 1e-9
    # B to x: through X is 1 (link) + 1 (server link), X not charged: it hosts x
    assert hop(network, "B", "x") == "X"
    assert network.routing_counts["crossing_delay_routers"] == 1

    # A route crossing X pays once: C - X - D in a line
    nodes = [("C", router()), ("X", router(internalDelayMs=2.5)), ("D", router()), ("s", SERVER)]
    edges = [("C", "X", link()), ("X", "D", link()), ("s", "D", link())]
    network = load(nodes, edges)
    network.calculate_forwarding_tables()
    assert abs(delay(network, "C", "s") - 5.5) < 1e-9          # 1 + 2.5 + 1 + 1
    Routing.crossing_delay = False
    try:
        network = load(nodes, edges)
        network.calculate_forwarding_tables()
        assert abs(delay(network, "C", "s") - 3.0) < 1e-9
        assert network.crossing_delay == {}
    finally:
        Routing.crossing_delay = True


def test_embedded_server_announced_within_host_cone():
    # H (AS 2) is a customer of the tier-1 T (AS 1); C (AS 3) is a customer
    # of H; D (AS 4) is another customer of T. H's observed cone is {3}.
    # e is a cache embedded in H; s is an ordinary server at H.
    nodes = [("T", router("tier1", asId="1")), ("H", router("transit", asId="2")),
             ("C", router("stub", asId="3")), ("D", router("stub", asId="4")),
             ("e", dict(SERVER, embedded=1)), ("s", dict(SERVER, embedded=0))]
    edges = [("H", "T", link("c2p")), ("C", "H", link("c2p")), ("D", "T", link("c2p")),
             ("e", "H", link("hosts")), ("s", "H", link("hosts"))]
    network = load_with_cones(nodes, edges, {"1": ["2", "3", "4"], "2": ["3"]})
    assert network.embedded_servers == {"e"}
    assert network.routing_counts["embedded_servers_limited"] == 1
    assert hop(network, "H", "e") == "e"
    assert hop(network, "C", "e") == "H"
    assert hop(network, "T", "e") is None
    assert hop(network, "D", "e") is None
    # T and D lack a route to e by design, not for want of a path
    assert network.routing_counts["unreachable_embedded"] == 2
    assert network.routing_counts["unreachable_other"] == 0
    for r in ("T", "H", "C", "D"):
        assert hop(network, r, "s") is not None


if __name__ == "__main__":
    failed = []
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", name)
            except AssertionError:
                failed.append(name)
                print("FAIL", name)
    print("{} failed: {}".format(len(failed), failed))

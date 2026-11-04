# Tests for the small bug fixes of 2026-10-14 (doc/TODO.md Bugs):
#   - float rounding in the utility range check
#   - GML node ids not written 0, 1, 2 ... in order
#   - Network.contains_node with an int
#   - write_gml
#   - hosts are single-homed; host-to-host (demand) edges in a GML are ignored
# Run with:  PYTHONPATH=src python3 tests/test_bug_fixes.py
# (also runs under pytest)

import os
import tempfile

import simpy

from Gml import parse_gml, read_gml, write_gml
from MetricUtility import check_in_range
from Network import Network
from Router import Router
from Server import Server
from Verbose import Verbose

Verbose.level = -2


# check_in_range: rounding error is clamped, real errors still raise

def test_range_clamps_rounding():
    assert check_in_range(1 + 1e-16, "u") == 1
    assert check_in_range(-1e-16, "u") == 0
    assert check_in_range(0.5, "u") == 0.5


def test_range_still_raises():
    for bad in (-0.01, 1.01):
        try:
            check_in_range(bad, "u")
        except ValueError:
            continue
        assert False, "no ValueError for {}".format(bad)


# GML node ids out of order

OUT_OF_ORDER = """graph [
  node [ id 0 label "a" ]
  node [ id 5 label "b" ]
  node [ id 1 label "c" ]
  edge [ source 0 target 5 delayMs 1 ]
  edge [ source 5 target 1 delayMs 1 ]
]"""


def test_gml_ids_out_of_order():
    graph = parse_gml(OUT_OF_ORDER)
    assert sorted(graph.nodes()) == ["a", "b", "c"]
    assert graph.contains_edge("b", "c")


DUPLICATE = """graph [
  node [ id 0 label "a" ]
  node [ id 1 label "b" ]
  node [ id 1 label "c" ]
  edge [ source 0 target 1 delayMs 1 ]
]"""


def test_gml_duplicate_id_still_dropped():
    graph = parse_gml(DUPLICATE)
    assert sorted(graph.nodes()) == ["a", "b"]


# Network.contains_node

def test_contains_node_int():
    network = Network(simpy.Environment())
    network.routers["r0"] = Router("r0", network)
    assert network.contains_node(0)
    assert not network.contains_node(1)


# write_gml round trip

def test_write_gml_round_trip():
    graph = read_gml("topologies/gml/Bics.gml")
    fd, path = tempfile.mkstemp(suffix=".gml")
    os.close(fd)
    try:
        write_gml(graph, path)
        again = read_gml(path)
    finally:
        os.remove(path)
    assert again.nodes() == graph.nodes()
    assert sorted(again.edges()) == sorted(graph.edges())


# single-homed hosts

DEMAND = """graph [
  node [ id 0 label "r0" type "router" ]
  node [ id 1 label "r1" type "router" ]
  node [ id 2 label "s0" type "server" ]
  node [ id 3 label "c0" type "client" ]
  edge [ source 0 target 1 delayMs 1 ]
  edge [ source 2 target 0 delayMs 1 ]
  edge [ source 3 target 1 delayMs 1 ]
  edge [ source 3 target 2 delayMs 1 ]
]"""


def test_demand_edge_ignored():
    network = Network.from_graph(parse_gml(DEMAND), simpy.Environment(), drop_external=False)
    assert network.servers["s0"].neighbour == "r0"
    assert network.clients["c0"].neighbour == "r1"
    assert len(network.links) == 3


WEIGHTS = """graph [
  node [ id 0 label "r0" type "router" ]
  node [ id 1 label "r1" type "router" ]
  node [ id 2 label "s0" type "server" ]
  edge [ source 0 target 1 delayMs 2 ]
  edge [ source 2 target 0 delayMs 3 ]
]"""


def test_router_weight_edge_to_host():
    # Router.weight_edge used to return 0 for a Host object (Nov 2026 fix)
    network = Network.from_graph(parse_gml(WEIGHTS), simpy.Environment(), drop_external=False)
    r0, r1, s0 = network.node("r0"), network.node("r1"), network.node("s0")
    access = s0.weight_edge(r0)
    assert access > 0
    assert r0.weight_edge(s0) == access
    assert r0.weight_edge("s0") == access
    assert network.weight("r0", "s0") == access
    core = r0.weight_edge(r1)
    assert core > 0 and core != access
    assert r0.weight_edge("r1") == core
    assert r1.weight_edge(s0) == 0  # not a neighbour


def test_host_same_link_twice_is_noop():
    network = Network(simpy.Environment())
    router = Router("r0", network)
    server = Server("s0", network)
    status1, link1 = server.add_neighbour(router, 0.1)
    status2, link2 = server.add_neighbour(router, 0.1)
    assert (status1, status2) == ("create", "exists")
    assert link2 is link1


def test_host_second_router_raises():
    network = Network(simpy.Environment())
    server = Server("s0", network)
    server.add_neighbour(Router("r0", network), 0.1)
    try:
        server.add_neighbour(Router("r1", network), 0.1)
    except ValueError:
        return
    assert False, "no ValueError for a second link"


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

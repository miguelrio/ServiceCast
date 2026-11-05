# Tests for Router.forward_to_tree_children_only (on by default since
# Nov 2026, T-13): ServerMetric updates go only to neighbours whose unicast
# next hop to the replica is this router.
#   - a run with the flag on makes the same routing decisions as a run with
#     it off: same request outcomes, same FIB actions, same valid updates
#   - its not-sent counts (Router.tree_skipped, A and W) equal the updates
#     a run with the flag off sends and then drops as off the unicast route
#     (Router.invalid_route_drops_op)
# The client generator stops early and the run then drains, so no update is
# still in flight at the end and the counts must match exactly.
# This holds because the network is lightly loaded. With the flag off, the
# off-path updates also take transmission time on the outgoing SwitchPort
# and can delay on-path updates queued behind them; on a busy network
# (1K CAIDA subset) the two runs drift apart after about 20 s.
# Run with:  PYTHONPATH=src python3 tests/test_tree_children.py
# (also runs under pytest)

import contextlib
import io
import re

from Generator import Generator
from Gml import parse_gml
from Graph import Graph
from Network import Network
from Router import Router
from Server import Server
from Utility import Utility
from Verbose import Verbose
import simpy

# Dfn (Topology Zoo, 58 routers) with 4 servers and 8 clients attached
SERVERS = {100: 9, 101: 30, 102: 44, 103: 2}
CLIENTS = {200: 15, 201: 1, 202: 12, 203: 50, 204: 22, 205: 38, 206: 5, 207: 27}


def dfn_with_hosts():
    with open("topologies/gml/Dfn.gml") as f:
        text = f.read().rstrip()
    assert text.endswith("]")
    extra = []
    for kind, hosts, edge_type in (("server", SERVERS, "hosts"), ("client", CLIENTS, "access")):
        for node, router in hosts.items():
            name = "srv_{:03d}".format(node - 99) if kind == "server" else "client_{:05d}".format(node - 199)
            extra.append('  node [\n    id {}\n    label "{}"\n    Internal 0\n    type "{}"\n  ]\n'
                         '  edge [\n    source {}\n    target {}\n    type "{}"\n  ]\n'.format(
                             node, name, kind, node, router, edge_type))
    return text[:-1] + "".join(extra) + "]\n"


def run(tree_children_only, requests_until=20000, until=2000000):
    """Run with requests for requests_until ms, then drain until `until` ms.
    Returns the counters and the per-request outcome lines."""
    Router.forward_to_tree_children_only = tree_children_only
    Router.hop_by_hop = False
    Graph.default_propagation_delay = 10
    Utility.alpha = 0.5
    Server.slots = 10
    Server.change_factor = 0.01
    Verbose.level = -1

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        env = simpy.Environment()
        network = Network.from_graph(parse_gml(dfn_with_hosts()), env, drop_external=False)
        network.calculate_forwarding_tables()
        for server in network.server_names():
            Generator.server_load_event_generator(network, server, ["§a"], seed=15112022)
        clients = Generator.multi_client_event_generator(
            network, network.client_names(), "§a", arrival_lambda=50,
            size_lambda=10000, size_scale_factor=1, seed=15112022)
        clients.generator.finish = requests_until
        network.start(until=until)
    # nothing left to happen: every session ended, every update delivered
    # (left in the queue: the run's own stop event, and the server load
    # generators' idle infinite timeouts)
    assert all(t in (env.now, float("inf")) for t, *_ in env._queue)

    outcomes = [line for line in out.getvalue().splitlines()
                if re.search(r" (OUTCOME_GAP|DECISION_GAP|STALENESS_ERR|REQUEST_NOT_FORWARDED|BLOCKED) ", line)]
    return {
        "recv": dict(Router.recv_server_metric),
        "not_sent": dict(Router.tree_skipped),
        "drops": dict(Router.invalid_route_drops_op),
        "fib": {r: dict(c) for r, c in Router.fib_actions.items()},
        "outcomes": outcomes,
    }


def test_flag_on_matches_flag_off():
    off = run(False)
    on = run(True)
    try:
        assert len(off["outcomes"]) > 100
        assert off["drops"]["A"] > 0 and off["drops"]["W"] > 0
        assert off["not_sent"] == {'A': 0, 'W': 0}
        assert on["drops"] == {'A': 0, 'W': 0}
        # updates not sent with the flag on = dropped with it off
        assert on["not_sent"] == off["drops"]
        # and the rest is the same traffic
        for op in "AW":
            assert on["recv"][op] + on["not_sent"][op] == off["recv"][op]
        assert on["fib"] == off["fib"]
        assert on["outcomes"] == off["outcomes"]
    finally:
        Router.forward_to_tree_children_only = True


if __name__ == "__main__":
    test_flag_on_matches_flag_off()
    print("ok")

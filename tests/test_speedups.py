# Tests for the simulator speed-ups:
#   - the two implementations of Router.decide_announcements (sort and scan
#     for the default comparisons, pairwise for any others) agree, with the
#     original pairwise rule as the reference
#   - any other comparison function (e.g. an equivalence margin) uses the
#     pairwise implementation
#   - SwitchPort: packets queue in order, each taking size*8/rate to send,
#     then the propagation delay
# Run with:  PYTHONPATH=src python3 tests/test_speedups.py
# (also runs under pytest)

import random

import simpy

from Router import Router, same_as, less_than, Compare
from SimComponents import SwitchPort, Packet
from Link import LinkEnd
from Verbose import Verbose

Verbose.level = -2


# The original rule, written out pairwise with is_better_in_any_metrics
def reference_decide(router, entries):
    announce = [False] * len(entries)
    for i, ei in enumerate(entries):
        announce[i] = True
        for j, ej in enumerate(entries):
            if i == j:
                continue
            c = router.is_better_in_any_metrics(ej, ei)
            if c == Compare.Better:
                announce[i] = False
                break
            elif c == Compare.Same:
                announce[j] = False
    return [e for e, a in zip(entries, announce) if a]


# Random entries with many ties: few distinct loads and delays
def random_entries(rng, n, values=4):
    return [{'replica': 's{}'.format(k),
             'load': rng.randrange(values) / values,
             'delay': float(rng.randrange(values))} for k in range(n)]


def test_skyline_matches_pairwise():
    router = Router("r0")
    assert router.uses_default_comparisons()
    rng = random.Random(1)
    for _ in range(20000):
        entries = random_entries(rng, rng.randrange(1, 12), rng.choice((2, 3, 5)))
        expected = reference_decide(router, entries)
        assert router._decide_skyline(entries) == expected
        assert router._decide_pairwise(entries) == expected
        assert router.decide_announcements(entries) == expected


def test_margin_uses_pairwise():
    # the same within 0.1 in load: not transitive (0, 0.08, 0.16)
    def same_within(x, y):
        return abs(x - y) <= 0.1

    router = Router("r0")
    router.metric_list[0]['same'] = same_within
    assert not router.uses_default_comparisons()

    entries = [{'replica': 's0', 'load': 0.0, 'delay': 1.0},
               {'replica': 's1', 'load': 0.08, 'delay': 0.5},
               {'replica': 's2', 'load': 0.16, 'delay': 0.2}]
    assert router.decide_announcements(entries) == reference_decide(router, entries)

    rng = random.Random(2)
    for _ in range(5000):
        entries = random_entries(rng, rng.randrange(1, 10), 10)
        assert router.decide_announcements(entries) == reference_decide(router, entries)


# SwitchPort: arrival times at the far end

class Receiver(object):
    def __init__(self, env):
        self.env = env
        self.arrivals = []

    def recv(self, packet, link_end):
        self.arrivals.append((packet.id, self.env.now))


def make_port(rate=8.0, delay=5.0):
    env = simpy.Environment()
    receiver = Receiver(env)
    port = SwitchPort(env, rate=rate)
    port.out = LinkEnd(env, delay, None, receiver)
    return env, port, receiver


def put_at(env, port, when, size, pid):
    def send():
        yield env.timeout(when)
        port.put(Packet(env.now, size, pid, "a", "b"))
    env.process(send())


def test_port_queues_in_order():
    # rate 8 bits per ms: a 10-byte packet takes 10 ms to send
    env, port, receiver = make_port()
    put_at(env, port, 0, 10, 1)
    put_at(env, port, 0, 10, 2)    # waits for packet 1
    put_at(env, port, 15, 10, 3)   # waits for packet 2 (sent until 20)
    put_at(env, port, 50, 10, 4)   # port idle again
    env.run()
    assert receiver.arrivals == [(1, 15.0), (2, 25.0), (3, 35.0), (4, 65.0)]
    assert port.packets_rec == 4


def test_port_rejects_queue_limit():
    try:
        SwitchPort(simpy.Environment(), rate=8.0, qlimit=100)
    except ValueError:
        return
    assert False, "no ValueError for qlimit"


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

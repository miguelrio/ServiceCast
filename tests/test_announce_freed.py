# Tests for Router.announce_freed_entries (Nov 2026, T-12): after a
# withdrawal, a router announces the entries the withdrawn one was
# dominating. Two implementations must send the same messages:
#   - with the default comparisons, a sort-and-scan decision runs only when
#     the withdrawn one was at least as good as an unannounced entry;
#   - with any other comparison functions, the router decides again over
#     all remaining entries.
# The pre-check in incoming_server_metrics_packet_withdraw skips withdrawals
# of unannounced entries (they free nothing); a whole run with and without
# that skip must be the same.
# Checked on random RIBs, and on whole runs (Dfn with servers and clients),
# where the second path is forced with comparison functions that behave
# like the defaults but are not the same objects.
# The fix is off by default (Router.announce_freed_after_withdraw); the
# whole-run tests switch it on themselves.
# Run with:  PYTHONPATH=src python3 tests/test_announce_freed.py
# (also runs under pytest)

import contextlib
import random

from Router import Router
from Server import ServerMetricMessageType
from Verbose import Verbose
import test_tree_children

Announce = ServerMetricMessageType.Announce


@contextlib.contextmanager
def freed_fix(on):
    saved = Router.announce_freed_after_withdraw
    Router.announce_freed_after_withdraw = on
    try:
        yield
    finally:
        Router.announce_freed_after_withdraw = saved


def same_like_default(x, y):
    return x == y


def less_like_default(x, y):
    return x < y


def use_general_comparisons(router):
    for m in router.metric_list:
        m['same'] = same_like_default
        m['better'] = less_like_default
    assert not router.uses_default_comparisons()


def freed(router, withdrawn):
    """The messages announce_freed_entries sends, without sending them."""
    out = []
    router.announce_metrics = out.extend
    router.announce_freed_entries(withdrawn)
    del router.announce_metrics
    return [(e['replica'], t) for e, t in out]


def test_random_ribs():
    Verbose.level = -2
    rng = random.Random(12)
    fast, full = Router("r0"), Router("r1")
    use_general_comparisons(full)
    checked = 0
    for _ in range(20000):
        values = rng.choice((2, 3, 5))
        rib = [{'replica': 's{}'.format(k), 'neighbour': 'n',
                'load': rng.randrange(values) / values,
                'delay': float(rng.randrange(values))} for k in range(rng.randrange(1, 10))]
        # the state after a decision: the decided entries are announced
        # (some have no sent_table key: nobody to send them to)
        decided = fast.decide_announcements(rib)
        sent = {e['replica']: {} for e in decided if rng.random() < 0.8}
        withdrawn = rng.choice(rib)
        rest = {e['replica']: e for e in rib if e is not withdrawn}
        sent.pop(withdrawn['replica'], None)

        results = []
        for router in (fast, full):
            router.service_RIB = dict(rest)
            router.sent_table = dict(sent)
            results.append(freed(router, withdrawn))
        # every freed entry is decided, and none of them was announced
        again = [e['replica'] for e in fast.decide_announcements(list(rest.values()))]
        assert all(r in again and r not in sent for r, _ in results[0])
        # the same messages, apart from decided entries without a key, which
        # the full decision announces again (to nobody)
        no_key = {r for r in again if r not in sent}
        beaten_by_withdrawn = {r for r in no_key
                               if withdrawn['delay'] <= rest[r]['delay'] and withdrawn['load'] <= rest[r]['load']}
        assert [m for m in results[1] if m[0] not in no_key - beaten_by_withdrawn] == results[0]
        checked += bool(results[0])
    assert checked > 1000


def run_dfn(general):
    saved = (Router.same_as_fn_load, Router.better_than_fn_load,
             Router.same_as_fn_delay, Router.better_than_fn_delay)
    if general:
        Router.same_as_fn_load = Router.same_as_fn_delay = staticmethod(same_like_default)
        Router.better_than_fn_load = Router.better_than_fn_delay = staticmethod(less_like_default)
    try:
        with freed_fix(True):
            return test_tree_children.run(True)
    finally:
        (Router.same_as_fn_load, Router.better_than_fn_load,
         Router.same_as_fn_delay, Router.better_than_fn_delay) = saved


def test_whole_run_same_both_ways():
    fast = run_dfn(False)
    full = run_dfn(True)
    for key in ("recv", "not_sent", "fib", "outcomes"):
        assert fast[key] == full[key], key


def test_unannounced_withdrawal_frees_nothing():
    # the pre-check skips withdrawals of unannounced entries; run the freed
    # check on those as well (wrapping the withdrawal handler): the run must
    # be the same, so they never free anything
    with freed_fix(True):
        with_skip = test_tree_children.run(True)
    saved = Router.incoming_server_metrics_packet_withdraw
    skipped = [0]

    def withdraw_and_check(self, link_end, packet):
        entry = self.service_RIB.get(packet.replica)
        was_announced = packet.replica in self.sent_table
        saved(self, link_end, packet)
        if entry is not None and not was_announced:
            skipped[0] += 1
            self.announce_freed_entries(entry)

    Router.incoming_server_metrics_packet_withdraw = withdraw_and_check
    try:
        with freed_fix(True):
            without_skip = test_tree_children.run(True)
    finally:
        Router.incoming_server_metrics_packet_withdraw = saved
    assert skipped[0] > 100
    for key in ("recv", "not_sent", "fib", "outcomes"):
        assert with_skip[key] == without_skip[key], key


def test_freed_entries_change_the_run():
    # the fix does something on this network: more announcements
    with freed_fix(False):
        old = test_tree_children.run(True)
    with freed_fix(True):
        new = test_tree_children.run(True)
    assert new["recv"]['A'] > old["recv"]['A']


if __name__ == "__main__":
    test_random_ribs()
    test_whole_run_same_both_ways()
    test_unannounced_withdrawal_frees_nothing()
    test_freed_entries_change_the_run()
    print("ok")

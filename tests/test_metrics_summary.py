
# Tests for the end-of-run SUMMARY_ lines (Verbose.level >= -1) and how
# quick_stats.py uses them.
# Run with:  PYTHONPATH=scripts python3 tests/test_metrics_summary.py
# (also runs under pytest)

from log_syntax import parse_log_header, parse_metrics_summary
from quick_stats import parse_log_lines


# formats from Network.print_metrics_summary and
# Router.incoming_server_metrics_packet
SERVER_SUMMARY = "{:.3f}: {:5s} SUMMARY_SERVER_METRICS created: {} announce: {} withdraw: {}"
FIB_SUMMARY = "{:.3f}: {:5s} SUMMARY_FIB_ROUTER SET: {} KEEP: {} CHANGED: {} REMOVED: {}"
RECV = "{:.3f}: {:5s} RECV_PACKET  ServerMetric {} srv_001.1 (0.000) [srv_001.1] MT(0.000) managed in {} after 0.100"
CREATED = "{:.3f}: {:5s} PACKET_CREATED srv_001.{} (0.000) ServerMetric in srv_001 after 0.000"

OUTCOME_GAP = ("4.809: Net   OUTCOME_GAP 'srv_001' [client_Beijing.1] SELECTED: time: 4.809 "
               "server: srv_001 load: 0.0 latency: 0.651 utility: 0.99941 BEST: time: 4.809 "
               "server: srv_001 load: 0.0 latency: 0.651 utility: 0.99941 SAME 0.0")


def header(level):
    return """Simulation parameters:
    gml_file = test.gml
    until = 30.0
    Verbose.level = {}
    Router.hop_by_hop = False

load: gml 0.1s, from_graph 0.1s; 4 nodes (1 servers, 1 clients)
Client multi_client_event_generator parameters:
    arrival_lambda = 0.4
    size_lambda = 10
    size_scale_factor = 10

RUN ----------------------------------------------------------------
""".format(level).splitlines(keepends=True)


def lines(*body):
    return [line + "\n" for line in body]


def test_parse_server_summary():
    s = parse_metrics_summary("30.000: Net   SUMMARY_SERVER_METRICS created: 12 announce: 340 withdraw: 5")
    assert s.kind == "server_metrics"
    assert s.router is None
    assert s.counts == {"created": 12, "announce": 340, "withdraw": 5}


def test_parse_fib_summary():
    s = parse_metrics_summary("30.000: r17   SUMMARY_FIB_ROUTER SET: 1 KEEP: 20 CHANGED: 3 REMOVED: 0")
    assert s.kind == "fib_router"
    assert s.router == "r17"
    assert s.counts == {"SET": 1, "KEEP": 20, "CHANGED": 3, "REMOVED": 0}


def test_parse_non_summary():
    assert parse_metrics_summary(OUTCOME_GAP) is None


def metrics_log(with_fib=True):
    body = [OUTCOME_GAP, SERVER_SUMMARY.format(30, "Net ", 12, 340, 5)]
    if with_fib:
        body += [FIB_SUMMARY.format(30, "r1", 1, 20, 3, 2),
                 FIB_SUMMARY.format(30, "r2", 4, 0, 1, 0)]
    return header(-1) + lines(*body)


def test_level_minus_1_log():
    stats = parse_log_lines(metrics_log())
    assert stats["log_verbose_level"] == -1
    assert stats["has_summary"]
    assert stats["summary_mismatches"] == []
    assert stats["total"] == 1 and stats["same"] == 1
    assert stats["server_updates_created"] == 12
    assert stats["server_metrics_announce"] == 340
    assert stats["server_metrics_withdraw"] == 5
    assert stats["fib_totals"] == {"SET": 5, "KEEP": 20, "CHANGED": 4, "REMOVED": 2}
    assert stats["fib_router_counts"]["r1"] == {"SET": 1, "KEEP": 20, "CHANGED": 3, "REMOVED": 2}
    assert stats["fib_router_counts"]["r2"] == {"SET": 4, "KEEP": 0, "CHANGED": 1, "REMOVED": 0}


def test_level_minus_1_log_no_fib_actions():
    stats = parse_log_lines(metrics_log(with_fib=False))
    assert stats["has_summary"]
    assert stats["fib_totals"] == {"SET": 0, "KEEP": 0, "CHANGED": 0, "REMOVED": 0}
    assert len(stats["fib_router_counts"]) == 0
    assert stats["server_metrics_announce"] == 340


def test_level_0_recv_mismatch():
    # 2 RECV_PACKET A lines, but the summary says 3 announces
    log = header(0) + lines(
        CREATED.format(0, "srv_001", 1),
        RECV.format(0.1, "r1", "A", "r1"),
        RECV.format(0.2, "r2", "A", "r2"),
        SERVER_SUMMARY.format(30, "Net ", 1, 3, 0),
    )
    stats = parse_log_lines(log)
    assert ("announce", 2, 3) in stats["summary_mismatches"]
    assert stats["server_metrics_announce"] == 3


def test_level_1_fib_attributed_to_wrong_router():
    # the same totals (2 SET), but one SET is on r1 in the lines and on r2
    # in the summary
    log = header(1) + lines(
        "1.000: r1    SET_BEST_REPLICA srv_001 direct ",
        "2.000: r1    SET_BEST_REPLICA srv_001 via best neighbour r0 ",
        SERVER_SUMMARY.format(30, "Net ", 0, 0, 0),
        FIB_SUMMARY.format(30, "r1", 1, 0, 0, 0),
        FIB_SUMMARY.format(30, "r2", 1, 0, 0, 0),
    )
    stats = parse_log_lines(log)
    names = [m[0] for m in stats["summary_mismatches"]]
    assert "fib_router r1" in names
    assert "fib_router r2" in names
    assert stats["fib_totals"]["SET"] == 2


def test_header_without_terminator():
    # no size_scale_factor line before the first timestamped line: the
    # header is treated as malformed and gives no parameters (why
    # Generator prints its parameter block at level -1)
    log = lines("Simulation parameters:", "    Verbose.level = -1", "", OUTCOME_GAP)
    parameters, _ = parse_log_header(log)
    assert parameters is None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)

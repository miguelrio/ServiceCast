# Tests for scripts/log_syntax.py reading the log header written by
# experiments/main.py (5 Nov 2026): settings in config form with a "# source"
# comment, quoted strings, None, a comment line, the header ending at RUN when
# there is no client generator, and the note for a log with no final DONE.
# Run with:  PYTHONPATH=src:scripts python3 tests/test_log_header.py
# (also runs under pytest)

import contextlib
import io

from log_syntax import parse_log_header

HEADER = """Simulation parameters:
    command_line = experiments/main.py configs/x.py --set SERVER_CF=0.05
    config_file = 'configs/x.py'
    git_commit = 'abc1234+dirty'
    time_unit = 'ms'
    # Settings in config form: every value is fixed here, defaults included.
    GML_FILE = 'topologies/ready/x.gml'   # config
    UNTIL = 60000                         # default
    SERVER_CF = 0.05                      # command line
    CLIENTS = None                        # default
    ROUTER_HOP_BY_HOP = False             # default

"""

GENERATOR = """Client multi_client_event_generator parameters:
    arrival_lambda = 20
    size_lambda = 10000
    size_scale_factor = 10
"""

BODY = """RUN ----------------------------------------------------------------
10.000: s1    SUMMARY_SERVER_METRICS created: 0
run: 5.000ms wall; simulated 60000 ms (clock: ms)
"""


def parse(text):
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        parameters, body = parse_log_header(io.StringIO(text), "x.log")
        lines = list(body)
    return parameters, lines, err.getvalue()


def test_values_comments_and_quotes():
    parameters, _, _ = parse(HEADER + GENERATOR + BODY + "DONE\n")
    assert parameters["config_file"] == "configs/x.py"
    assert parameters["GML_FILE"] == "topologies/ready/x.gml"
    assert parameters["UNTIL"] == 60000
    assert parameters["SERVER_CF"] == 0.05
    assert parameters["CLIENTS"] is None
    assert parameters["ROUTER_HOP_BY_HOP"] is False
    assert parameters["time_unit"] == "ms"
    assert parameters["command_line"].endswith("--set SERVER_CF=0.05")
    assert parameters["size_scale_factor"] == 10


def test_done_present_no_note():
    _, lines, err = parse(HEADER + GENERATOR + BODY + "DONE\n")
    assert lines[-1].strip() == "DONE"
    assert err == ""


def test_done_missing_note():
    _, _, err = parse(HEADER + GENERATOR + BODY)
    assert "no final DONE line" in err


def test_header_ends_at_run_without_generator():
    # CLIENTS = 0: no client generator, so no size_scale_factor line
    parameters, lines, err = parse(HEADER + BODY + "DONE\n")
    assert parameters is not None and parameters["SERVER_CF"] == 0.05
    assert lines[0].startswith("RUN ---")
    assert err == ""


def test_old_header_no_done_note():
    old = """Simulation parameters:
    until = 60000.0
    time_unit = ms
    Server.slots = 50

"""
    parameters, _, err = parse(old + GENERATOR + BODY)
    assert parameters["Server.slots"] == 50 and parameters["time_unit"] == "ms"
    assert err == ""   # older logs never had DONE


if __name__ == "__main__":
    failed = []
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", name)
            except AssertionError as e:
                failed.append(name)
                print("FAIL", name, e)
    print("{} failed: {}".format(len(failed), failed))

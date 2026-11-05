# Tests for src/Importer.py: settings from code defaults, a config file and
# command-line overrides.
# Run with:  PYTHONPATH=src python3 tests/test_importer.py
# (also runs under pytest)

import os
import tempfile

from Importer import Importer, SETTINGS, BY_NAME, parse_value
from Graph import Graph
from MetricUtility import MetricUtility, linear, logarithmic
from Router import Router, greater_than
from Routing import Routing
from Run import Run
from Server import Server
from Verbose import Verbose
from Utility import Utility, user_utility_geometric


# Each test changes class attributes; put the defaults back afterwards.
DEFAULTS = {setting.name: setting.read() for setting in SETTINGS}


def restore():
    for setting in SETTINGS:
        setting.write(DEFAULTS[setting.name])


def write_config(text, suffix=".py"):
    f = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False)
    f.write(text)
    f.close()
    return f.name


def raises(fn, words):
    try:
        fn()
    except ValueError as e:
        assert words in str(e), str(e)
        return
    assert False, "no ValueError"


def test_precedence():
    path = write_config("SERVER_SLOTS = 50\nSERVER_CF = 0.01\n")
    try:
        config = Importer().load(path).override(["SERVER_CF=0.05"]).apply()
        assert Server.slots == 50                  # config
        assert Server.change_factor == 0.05        # command line beats config
        assert Router.hop_by_hop == DEFAULTS["ROUTER_HOP_BY_HOP"]   # default
        resolved = config.resolved()
        assert resolved["SERVER_SLOTS"] == (50, "config")
        assert resolved["SERVER_CF"] == (0.05, "command line")
        assert resolved["ROUTER_HOP_BY_HOP"][1] == "default"
    finally:
        os.unlink(path)
        restore()


def test_no_config():
    config = Importer().override(["UNTIL=500000"]).apply()
    try:
        assert Run.until == 500000
        assert config.config_file is None
    finally:
        restore()


def test_unknown_name_in_config():
    path = write_config("SERVER_SLOT = 50\n")
    try:
        raises(lambda: Importer().load(path), "did you mean SERVER_SLOTS")
    finally:
        os.unlink(path)


def test_unknown_name_on_command_line():
    raises(lambda: Importer().override(["ALHPA=0.3"]), "did you mean ALPHA")
    raises(lambda: Importer().override(["ALPHA"]), "NAME=VALUE")


def test_helpers_in_config_are_ignored():
    path = write_config("import math\nslots = 25\nSERVER_SLOTS = slots * 2\n_X = 1\n")
    try:
        Importer().load(path).apply()
        assert Server.slots == 50
    finally:
        os.unlink(path)
        restore()


def test_choices():
    raises(lambda: Importer().override(["ROUTING_POLICY=valley-free"]), "must be one of")
    Importer().override(["ROUTING_POLICY=shortest"]).apply()
    try:
        assert Routing.policy == "shortest"
    finally:
        restore()


def test_times_in_ms_unconverted():
    config = Importer().override(["GRAPH_DELAY=10", "CLIENT_ATTACH_DELAY=20", "UNTIL=500000"]).apply()
    try:
        assert Graph.default_propagation_delay == 10
        assert Graph.default_client_attachment_delay_ms == 20
        assert Run.until == 500000
        assert config.resolved()["GRAPH_DELAY"] == (10, "command line")
    finally:
        restore()


def test_functions_by_name():
    config = Importer().override(["METRIC_LOAD_FN=logarithmic", "USER_UTILITY_FN=geometric",
                                  "ROUTER_BETTER_THAN_FN_LOAD=greater_than"]).apply()
    try:
        assert MetricUtility.metric_utility_fn['load'] is logarithmic
        assert MetricUtility.metric_utility_fn['delay'] is linear
        assert Utility.user_utility_fn is user_utility_geometric
        assert Router.better_than_fn_load is greater_than
        resolved = config.resolved()
        assert resolved["METRIC_LOAD_FN"][0] == "logarithmic"
        assert resolved["USER_UTILITY_FN"][0] == "geometric"
        assert resolved["ROUTER_BETTER_THAN_FN_LOAD"][0] == "greater_than"
    finally:
        restore()
    raises(lambda: Importer().override(["METRIC_LOAD_FN=cubic"]), "must be one of")


def test_parse_value():
    assert parse_value("50") == 50
    assert parse_value("0.01") == 0.01
    assert parse_value("True") is True
    assert parse_value("None") is None
    assert parse_value("topologies/x.gml") == "topologies/x.gml"
    assert parse_value("'quoted'") == "quoted"


def test_config_lines_round_trip():
    # the header's settings block (and --dump-config) loads back as a config
    config = Importer().override(["SERVER_SLOTS=60", "METRIC_LOAD_FN=logarithmic",
                                  "GRAPH_DELAY=20", "CLIENTS=5"]).apply()
    lines = config.config_lines()
    assert len(lines) == len(SETTINGS)
    assert any(l.startswith("SERVER_SLOTS = 60 ") and l.endswith("# command line") for l in lines)
    saved = {n: v for n, (v, _) in config.resolved().items()}
    restore()
    path = write_config("\n".join(lines) + "\n")
    try:
        again = Importer().load(path).apply()
        assert Server.slots == 60
        assert MetricUtility.metric_utility_fn['load'] is logarithmic
        assert Graph.default_propagation_delay == 20
        assert Run.clients == 5
        assert {n: v for n, (v, _) in again.resolved().items()} == saved
    finally:
        os.unlink(path)
        restore()


def test_run_defaults():
    # Verbose.level stays 1 for other scripts; main.py's runs default to -1
    assert Verbose.level == 1
    config = Importer().use_run_defaults()
    try:
        assert Verbose.level == -1
        assert config.resolved()["VERBOSE_LEVEL"] == (-1, "default")
        Importer().use_run_defaults().override(["VERBOSE_LEVEL=0"]).apply()
        assert Verbose.level == 0
    finally:
        restore()


def test_no_json_config():
    path = write_config('{"SERVER_SLOTS": 50}', suffix=".json")
    try:
        raises(lambda: Importer().load(path), "not a Python config file")
    finally:
        os.unlink(path)


def test_value_types_and_ranges():
    # 5 Nov 2026: a typo or an impossible value stops before the run
    for bad, words in [("ROUTER_HOP_BY_HOP=yes", "True or False"),
                       ("UNTIL=abc", "a number above 0"),
                       ("SERVER_CF=0,05", "a number, 0 or more"),
                       ("ARRIVAL_MEAN=0", "a number above 0"),
                       ("SERVER_SLOTS=0", "a whole number above 0"),
                       ("SERVER_SLOTS=2.5", "a whole number above 0"),
                       ("ALPHA=2", "from 0 to 1"),
                       ("CLIENTS=-1", "0 or more"),
                       ("ROUTER_HOP_BY_HOP=1", "True or False")]:
        raises(lambda: Importer().override([bad]), words)
    Importer().override(["ROUTER_HOP_BY_HOP=False", "UNTIL=5000.5", "CLIENTS=None",
                         "SERVER_CF=0", "ALPHA=1", "GML_FILE=x.gml"])


def test_true_false_any_case():
    # 5 Nov 2026: true/false/none in any capitalisation, on the command line
    # and as text in a config
    config = Importer().override(["ROUTER_HOP_BY_HOP=true", "ROUTER_FORWARD_TO_TREE_CHILDREN_ONLY=FALSE",
                                  "SERVER_BACKGROUND_LOAD=False", "CLIENTS=none"]).apply()
    try:
        assert Router.hop_by_hop is True
        assert Router.forward_to_tree_children_only is False
        assert Run.clients is None
    finally:
        restore()
    path = write_config('ROUTER_HOP_BY_HOP = "true"\n')
    try:
        Importer().load(path).apply()
        assert Router.hop_by_hop is True
    finally:
        os.unlink(path)
        restore()
    assert parse_value("TRUE") is True and parse_value("false") is False and parse_value("None") is None


def test_old_names_point_to_new_settings():
    raises(lambda: Importer().override(["TAU=20"]), "it is now ARRIVAL_MEAN (in ms)")
    raises(lambda: Importer().override(["NOCLIENTS=1"]), "it is now CLIENTS=0")
    raises(lambda: Importer().override(["ANNOUNCE_FREED=1"]), "ROUTER_ANNOUNCE_FREED_AFTER_WITHDRAW")


def test_lower_case_name_suggestion():
    raises(lambda: Importer().override(["server_slots=5"]), "did you mean SERVER_SLOTS")


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

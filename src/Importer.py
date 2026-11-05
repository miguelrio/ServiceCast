# Importer -- run settings from a config file and the command line.
#
# Every setting is a class attribute that holds its default in the code
# (Server.slots, Router.hop_by_hop, Run.until, ...).  A value comes from, in
# order of precedence:
#
#   1. a command-line override        NAME=VALUE   (Importer.override)
#   2. the config file                NAME = value (Importer.load)
#   3. the default in the code        the class attribute
#
# SETTINGS below is the single table of settings: each config NAME, the
# class attribute it sets and how its value is read.  apply() writes the
# values onto the classes; resolved() reads every setting back with where its
# value came from, and config_lines() writes them in config form (the log
# header's settings block, and main.py --dump-config).
#
# A config file is a Python file: only its upper-case names are settings;
# lower-case names and imports are helpers.
#
# Typical use (see experiments/main.py):
#
#   config = Importer()
#   config.load("configs/precomputed_t1.py")
#   config.override(["SERVER_CF=0.05", "UNTIL=500000"])
#   config.apply()

import ast
import difflib
import importlib.util
import sys

from Graph import Graph
from Network import Network
from Server import Server
from Router import Router, COMPARATORS
from Routing import Routing, POLICIES, C2P_ORIENTATIONS
from Generator import Generator
from Verbose import Verbose
from Utility import Utility, FUNCTIONS as USER_UTILITY_FUNCTIONS
from MetricUtility import MetricUtility, FUNCTIONS as METRIC_FUNCTIONS
from Run import Run


# the classes a setting can name
CLASSES = {cls.__name__: cls for cls in
           (Graph, Network, Server, Router, Routing, Generator, Verbose, Utility, MetricUtility, Run)}


class Setting:
    """One setting: its config NAME, the attribute it sets and how its value
    is read.

    target   "Class.attr", or "Class.attr[key]" for an entry of a dict
             attribute (MetricUtility.metric_utility_fn['load'])
    names    the value is a name looked up in this dict (a function by name)
    choices  the value must be one of these
    run_default  a default for runs started by experiments/main.py that
             differs from the class attribute's (which other scripts and
             tests keep); applied by Importer.use_run_defaults()
    kind     the value's type and range, checked before a run (one of the
             KINDS below); None for names/choices settings
    """

    def __init__(self, name, target, kind=None, names=None, choices=None, run_default=None):
        self.name = name
        self.target = target
        self.kind = kind
        self.names = names
        self.choices = choices
        self.run_default = run_default

        cls_name, attr = target.split(".", 1)
        self.key = None
        if attr.endswith("]"):
            attr, key = attr[:-1].split("[", 1)
            self.key = ast.literal_eval(key)
        self.cls = CLASSES[cls_name]
        self.attr = attr

    # the attribute's value as it stands
    def read(self):
        value = getattr(self.cls, self.attr)
        if self.key is not None:
            value = value[self.key]
        return value

    def write(self, value):
        if self.key is not None:
            getattr(self.cls, self.attr)[self.key] = value
        else:
            setattr(self.cls, self.attr, value)

    def check(self, value):
        """Raise ValueError if the config value is not allowed"""
        if self.kind is not None:
            ok, wanted = KINDS[self.kind]
            if not ok(value):
                raise ValueError("{} = {!r}: must be {}".format(self.name, value, wanted))
        if self.names is not None and value not in self.names:
            raise ValueError("{} = {!r}: must be one of {}".format(self.name, value, sorted(self.names)))
        if self.choices is not None and value not in self.choices:
            raise ValueError("{} = {!r}: must be one of {}".format(self.name, value, list(self.choices)))

    # config value -> attribute value
    def to_attribute(self, value):
        if self.names is not None:
            value = self.names[value]
            # functions held on a class are stored as staticmethods
            if self.key is None:
                value = staticmethod(value)
        return value

    # attribute value -> config value (the inverse of to_attribute)
    def to_config(self, value):
        if self.names is not None:
            for name, fn in self.names.items():
                if fn is value:
                    return name
            return getattr(value, "__name__", repr(value))   # not a named function
        return value


# 5 Nov 2026: the type and range of each setting's value, checked before a
# run, so a typo ('false', '0,05') or an impossible value (0 slots) stops
# main.py with a message instead of running wrongly or failing mid-run.
def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _integer(v):
    return isinstance(v, int) and not isinstance(v, bool)


KINDS = {
    "bool": (lambda v: isinstance(v, bool), "True or False"),
    "str": (lambda v: isinstance(v, str), "a string"),
    "path": (lambda v: v is None or isinstance(v, str), "a file path"),
    "int": (_integer, "a whole number"),
    "int>0": (lambda v: _integer(v) and v > 0, "a whole number above 0"),
    "int>=0": (lambda v: _integer(v) and v >= 0, "a whole number, 0 or more"),
    "count": (lambda v: v is None or (_integer(v) and v >= 0), "None or a whole number, 0 or more"),
    "number>0": (lambda v: _number(v) and v > 0, "a number above 0"),
    "number>=0": (lambda v: _number(v) and v >= 0, "a number, 0 or more"),
    "0..1": (lambda v: _number(v) and 0 <= v <= 1, "a number from 0 to 1"),
}


# The settings.  Every time value is in milliseconds, in configs and on the
# command line as in the simulator (src/units.py), so none is converted.
SETTINGS = [
    # run
    Setting("GML_FILE", "Run.gml_file", kind="path"),
    Setting("UNTIL", "Run.until", kind="number>0"),
    Setting("SEED", "Run.seed", kind="int>=0"),
    # Verbose.level stays 1 for other scripts; main.py runs at -1 (5 Nov)
    Setting("VERBOSE_LEVEL", "Verbose.level", kind="int", run_default=-1),
    Setting("VERBOSE_TABLE", "Verbose.table", kind="int>=0"),

    # workload and clients
    Setting("SERVICE", "Run.service", kind="str"),
    Setting("ARRIVAL_MEAN", "Run.arrival_mean", kind="number>0"),
    Setting("SESSION_MEAN", "Run.session_mean", kind="number>0"),
    Setting("SESSION_SCALE", "Run.session_scale", kind="number>0"),
    Setting("CLIENTS", "Run.clients", kind="count"),
    Setting("SERVER_BACKGROUND_LOAD", "Run.server_background_load", kind="bool"),

    # routing
    Setting("ROUTING_POLICY", "Routing.policy", choices=POLICIES),
    Setting("ROUTING_C2P_ORIENTATION", "Routing.c2p_orientation", choices=("auto",) + C2P_ORIENTATIONS),
    Setting("ROUTING_OBSERVED_CONES", "Routing.observed_cones", kind="bool"),
    Setting("ROUTING_CROSSING_DELAY", "Routing.crossing_delay", kind="bool"),
    Setting("ROUTING_CHUNK_SIZE", "Routing.chunk_size", kind="int>0"),

    # link delays (ms)
    Setting("GRAPH_DELAY", "Graph.default_propagation_delay", kind="number>0"),
    Setting("SERVER_ATTACH_DELAY", "Graph.default_server_attachment_delay_ms", kind="number>0"),
    Setting("CLIENT_ATTACH_DELAY", "Graph.default_client_attachment_delay_ms", kind="number>0"),

    # servers
    Setting("SERVER_SLOTS", "Server.slots", kind="int>0"),
    Setting("SERVER_CF", "Server.change_factor", kind="number>=0"),
    Setting("SERVER_SEND_AT_SECOND_BOUNDARIES", "Server.send_at_second_boundaries", kind="bool"),

    # routers
    Setting("ROUTER_HOP_BY_HOP", "Router.hop_by_hop", kind="bool"),
    Setting("ROUTER_FIB_UPT", "Router.fib_utility_update_threshold", kind="number>=0"),
    Setting("ROUTER_FORWARD_TO_TREE_CHILDREN_ONLY", "Router.forward_to_tree_children_only", kind="bool"),
    Setting("ROUTER_REMOVE_FIB_ENTRY_WHEN_ALL_UTILITIES_ZERO", "Router.remove_fib_entry_when_all_utilities_zero", kind="bool"),
    Setting("ROUTER_ANNOUNCE_FREED_AFTER_WITHDRAW", "Router.announce_freed_after_withdraw", kind="bool"),
    Setting("ROUTER_BETTER_THAN_FN_LOAD", "Router.better_than_fn_load", names=COMPARATORS),
    Setting("ROUTER_BETTER_THAN_FN_DELAY", "Router.better_than_fn_delay", names=COMPARATORS),
    Setting("ROUTER_SAME_AS_FN_LOAD", "Router.same_as_fn_load", names=COMPARATORS),
    Setting("ROUTER_SAME_AS_FN_DELAY", "Router.same_as_fn_delay", names=COMPARATORS),

    # utility
    Setting("ALPHA", "Utility.alpha", kind="0..1"),
    Setting("USER_UTILITY_FN", "Utility.user_utility_fn", names=USER_UTILITY_FUNCTIONS),
    Setting("METRIC_LOAD_FN", "MetricUtility.metric_utility_fn['load']", names=METRIC_FUNCTIONS),
    Setting("METRIC_DELAY_FN", "MetricUtility.metric_utility_fn['delay']", names=METRIC_FUNCTIONS),
    Setting("METRIC_LOAD_SCALE", "MetricUtility.metric_scale['load']", kind="number>0"),
]

BY_NAME = {setting.name: setting for setting in SETTINGS}

# where a value came from
DEFAULT, CONFIG, COMMAND_LINE = "default", "config", "command line"


# 5 Nov 2026: true/false/none in any capitalisation (TRUE, false, ...)
WORDS = {"true": True, "false": False, "none": None}


def parse_value(text):
    """A command-line value: true, false or none in any capitalisation, a
    Python literal (50, 0.01, "x"), or else the text itself as a string
    (topologies/x.gml)"""
    if text.strip().lower() in WORDS:
        return WORDS[text.strip().lower()]
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return text


# 5 Nov 2026: the environment variables of the older run scripts
# (main_precomputed_t1.py and its test copies) and the setting that replaced
# each, named in the error when someone uses an old name
OLD_NAMES = {
    "TAU": "ARRIVAL_MEAN (in ms)",
    "ARRIVAL_LAMBDA": "ARRIVAL_MEAN (in ms)",
    "NOCLIENTS": "CLIENTS=0",
    "NCLIENTS_USE": "CLIENTS=N",
    "TREE_CHILDREN_ONLY": "ROUTER_FORWARD_TO_TREE_CHILDREN_ONLY (True or False)",
    "ANNOUNCE_FREED": "ROUTER_ANNOUNCE_FREED_AFTER_WITHDRAW (True or False)",
    "SIM_DURATION": "UNTIL (in ms)",
}


class Importer(object):

    def __init__(self):
        self.config_file = None
        # NAME -> value, and NAME -> source, for the names given
        self.values = {}
        self.sources = {}

    def _set(self, name, value, source):
        if name not in BY_NAME:
            if name.upper() in OLD_NAMES:
                raise ValueError("unknown setting {} (from the {}): it is now {}".format(
                    name, source, OLD_NAMES[name.upper()]))
            close = difflib.get_close_matches(name.upper(), BY_NAME, n=3)
            raise ValueError("unknown setting {} (from the {}){}".format(
                name, source, "; did you mean " + ", ".join(close) + "?" if close else ""))
        setting = BY_NAME[name]
        # a True/False setting given as text in a config ("false", "TRUE")
        if setting.kind == "bool" and isinstance(value, str) and value.strip().lower() in ("true", "false"):
            value = WORDS[value.strip().lower()]
        setting.check(value)
        self.values[name] = value
        self.sources[name] = source

    def use_run_defaults(self):
        """Give the settings that have a run default (see Setting) that
        value, as their default: main.py calls this before load()"""
        for setting in SETTINGS:
            if setting.run_default is not None:
                setting.write(setting.to_attribute(setting.run_default))
        return self

    def load(self, file_path):
        """Read a config file (a Python file of NAME = value lines)"""
        self.config_file = file_path
        spec = importlib.util.spec_from_file_location("config", file_path)
        if spec is None:
            raise ValueError(file_path + ": not a Python config file")
        module = importlib.util.module_from_spec(spec)
        # 5 Nov 2026: no __pycache__ folder beside the config
        write_bytecode, sys.dont_write_bytecode = sys.dont_write_bytecode, True
        try:
            spec.loader.exec_module(module)
        finally:
            sys.dont_write_bytecode = write_bytecode
        # only upper-case names are settings
        for name, value in vars(module).items():
            if name.isupper() and not name.startswith("_"):
                self._set(name, value, CONFIG)
        return self

    def override(self, assignments):
        """Command-line overrides, each "NAME=VALUE"; they win over the config"""
        for text in assignments:
            name, sep, value = text.partition("=")
            if not sep:
                raise ValueError("--set {}: expected NAME=VALUE".format(text))
            self._set(name.strip(), parse_value(value.strip()), COMMAND_LINE)
        return self

    def apply(self):
        """Write the given values onto the classes; the rest keep their defaults"""
        for name, value in self.values.items():
            setting = BY_NAME[name]
            setting.write(setting.to_attribute(value))
        return self

    def resolved(self):
        """Every setting as NAME -> (value, source), read back from the classes"""
        return {setting.name: (setting.to_config(setting.read()), self.sources.get(setting.name, DEFAULT))
                for setting in SETTINGS}

    def config_lines(self):
        """Every setting in config form, one valid Python line each, with
        where its value came from as a comment:
            SERVER_CF = 0.05                     # command line
        Loading these lines as a config gives the same run."""
        rows = [("{} = {!r}".format(name, value), source)
                for name, (value, source) in self.resolved().items()]
        width = max(len(text) for text, _ in rows)
        return ["{:<{}}   # {}".format(text, width, source) for text, source in rows]

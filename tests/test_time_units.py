# Regression checks for the milliseconds-only time contract.
# Run with: PYTHONPATH=src python3 tests/test_time_units.py

import math

import numpy as np
import simpy

from Client import Client
from Generator import Generator
from Graph import Graph
from Importer import Importer
from Network import Network
from Server import Server, Request
from Verbose import Verbose
from units import MS_PER_S, ms_to_s, s_to_ms


Verbose.level = -2


def test_network_start_uses_ms_directly():
    env = simpy.Environment()
    network = Network(env)
    network.start(until=250)
    assert env.now == 250


def test_importer_does_not_rescale_ms():
    importer = Importer({"Graph": Graph})
    importer.GRAPH_DELAY = 100
    importer.update("Graph.default_propagation_delay", "GRAPH_DELAY")
    assert Graph.default_propagation_delay == 100


def test_session_duration_and_packet_size_are_independent():
    seed = 15112022
    network = Network(simpy.Environment())
    network.clients["c"] = Client("c", network)
    generated = Generator.multi_client_event_generator(
        network, ["c"], "§a", arrival_lambda=400,
        size_lambda=10000, size_scale_factor=10, seed=seed)

    packet_size, duration = generated.generator.sdist()
    legacy_seconds = np.random.RandomState(seed + 1).exponential(10) * 10
    assert packet_size == int(legacy_seconds)
    assert duration == int(legacy_seconds * MS_PER_S)
    assert duration != packet_size


def test_server_timeout_uses_request_duration_ms():
    env = simpy.Environment()
    server = Server("s")
    server.env = env
    server.used_slots = 1
    server.no_of_flows = 1
    server.send_load_change = lambda time, service_name: None
    request = Request("c", "§a", 1, 100, 250)

    env.process(server.decrease_load(request))
    env.run(until=249)
    assert server.used_slots == 1
    env.run(until=251)
    assert server.used_slots == 0
    assert request.size == 100
    assert request.duration == 250


def test_external_wall_clock_converters():
    assert s_to_ms(0.4) == 400
    assert ms_to_s(400) == 0.4


def test_exact_load_calibration_uses_integer_ms_sessions():
    mean_session = 1 / math.expm1(1 / 100000)
    arrival = 399.9980000033333
    offered_load = (1 / arrival) * mean_session / (5 * 50)
    assert math.isclose(offered_load, 1.0, rel_tol=0, abs_tol=1e-12)


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

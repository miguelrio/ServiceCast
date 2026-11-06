"""Tests for the main.py-based sweep driver and matrix aggregation.

Run from the repository root:
    PYTHONPATH=src:scripts python3 tests/test_sweep.py
"""

import importlib.util
import os
import subprocess
import tempfile
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = importlib.util.spec_from_file_location(
    "sweep", os.path.join(REPO, "experiments", "sweep.py"))
sweep = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sweep)

from log_metrics import LogMetrics
from sweep_metrics import build_matrix_data, cell_from_metrics


class SweepTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.definition = sweep.load_definition("experiments/sweeps/dfn_thresholds.py")
        cls.settings = sweep.resolved_settings(cls.definition)

    def test_dfn_definition_generates_nine_matrix_ordered_cells(self):
        cells, delays, server_cfs, router_cfs = sweep.make_cells(self.definition, self.settings)
        self.assertEqual(len(cells), 9)
        self.assertEqual(delays, [self.settings["GRAPH_DELAY"]])
        self.assertEqual(server_cfs, [0.001, 0.01, 0.05])
        self.assertEqual(router_cfs, [0.0001, 0.001, 0.01])
        self.assertEqual(cells[0]["overrides"]["SERVER_CF"], 0.001)
        self.assertEqual(cells[0]["overrides"]["ROUTER_FIB_UPT"], 0.0001)
        self.assertEqual(cells[-1]["overrides"]["SERVER_CF"], 0.05)
        self.assertEqual(cells[-1]["overrides"]["ROUTER_FIB_UPT"], 0.01)
        self.assertEqual(self.settings["UNTIL"], 360000)
        self.assertEqual(self.settings["VERBOSE_LEVEL"], 1)

    def test_optional_delay_axis_expands_the_matrix(self):
        definition = dict(self.definition)
        definition["AXES"] = {**self.definition["AXES"], "GRAPH_DELAY": [10, 20]}
        cells, delays, _, _ = sweep.make_cells(definition, self.settings)
        self.assertEqual(len(cells), 18)
        self.assertEqual(delays, [10, 20])
        self.assertEqual(cells[0]["overrides"]["GRAPH_DELAY"], 10)
        self.assertEqual(cells[9]["overrides"]["GRAPH_DELAY"], 20)

    def test_log_metrics_keep_established_cell_and_matrix_shape(self):
        parsed = LogMetrics(
            created=3, recv_total=8, recv_announce=6, recv_withdraw=2,
            fib_updates=4, blocked=1,
            records=[(0.4, 0.5, 0.3, 0.5), (0.6, 0.6, 0.7, 0.7)],
            per_server_served={},
        )
        metrics = cell_from_metrics(parsed)
        self.assertEqual(metrics["created"], 3)
        self.assertEqual(metrics["accuracy"], 50.0)
        self.assertAlmostEqual(metrics["mean_err_all"], 0.05)
        self.assertAlmostEqual(metrics["mean_err_arrival"], 0.1)
        self.assertAlmostEqual(metrics["blocked_rate"], 100 / 3)

        cells, delays, server_cfs, router_cfs = sweep.make_cells(self.definition, self.settings)
        for cell in cells:
            cell["metrics"] = {name: cell["index"] for name in self.definition["METRICS"]}
        data = build_matrix_data(
            cells, delays, server_cfs, router_cfs, self.definition["METRICS"],
            False, "test-commit", "2026-11-06T00:00:00",
        )
        self.assertEqual(data["source"], "log")
        self.assertEqual(data["delay_unit"], "ms")
        self.assertEqual(data["matrix_created"], [[[0.0, 1.0, 2.0],
                                                   [3.0, 4.0, 5.0],
                                                   [6.0, 7.0, 8.0]]])

    def test_nonzero_cell_exit_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            cell = {"index": 0, "overrides": {}}
            result = subprocess.CompletedProcess([], 1)
            with mock.patch.object(sweep.subprocess, "run", return_value=result):
                outcome = sweep.execute_cell(cell, self.definition["BASE_CONFIG"], directory)
            self.assertEqual(outcome["returncode"], 1)
            self.assertEqual(outcome["status"], "failed")
            self.assertIn("exited 1", outcome["error"])
            self.assertNotIn("returncode", cell)

    def test_missing_done_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            cell = {"index": 0, "overrides": {}}
            result = subprocess.CompletedProcess([], 0)
            with mock.patch.object(sweep.subprocess, "run", return_value=result):
                outcome = sweep.execute_cell(cell, self.definition["BASE_CONFIG"], directory)
            self.assertEqual(outcome["status"], "failed")
            self.assertIn("no final DONE", outcome["error"])

    def test_parallel_manifest_has_no_worker_mutation_race(self):
        def complete_immediately(command, cwd, stdout, stderr):
            stdout.write("DONE\n")
            return subprocess.CompletedProcess(command, 0)

        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(sweep.subprocess, "run", side_effect=complete_immediately):
                for attempt in range(5):
                    cells = [
                        {"index": index, "overrides": {}, "status": "pending"}
                        for index in range(32)
                    ]
                    manifest = {"cells": cells}
                    manifest_path = os.path.join(directory, f"manifest-{attempt}.json")
                    sweep.run_cells(cells, self.definition["BASE_CONFIG"], directory,
                                    8, manifest, manifest_path)
                    self.assertTrue(all(cell["status"] == "complete" for cell in cells))
                    self.assertTrue(all("command" in cell and "returncode" in cell for cell in cells))


if __name__ == "__main__":
    unittest.main()

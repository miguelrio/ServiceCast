#!/usr/bin/env python3
"""Run a change-factor matrix as independent experiments/main.py subprocesses.

A sweep definition names a normal main.py config, fixed overrides, the SERVER_CF
and ROUTER_FIB_UPT axes, and optionally a GRAPH_DELAY axis. This script never
builds a network or changes simulator globals: main.py owns every single run.
"""

import argparse
import ast
import concurrent.futures
from datetime import datetime
import importlib.util
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))

from log_metrics import parse_log_file
from sweep_metrics import METRIC_FIELDS, build_matrix_data, cell_from_metrics

MAIN = "experiments/main.py"
MATRIX_AXES = {"SERVER_CF", "ROUTER_FIB_UPT", "GRAPH_DELAY"}
DEFINITION_FIELDS = {"BASE_CONFIG", "FIXED", "AXES", "METRICS"}


def find_file(path):
    """Find a path relative to the current directory or the repository root."""
    for candidate in (path, os.path.join(REPO, path)):
        if os.path.isfile(candidate):
            return os.path.abspath(candidate)
    raise ValueError("no such file: " + path)


def repo_path(path):
    """Use a repository-relative path in commands and manifests when possible."""
    absolute = os.path.abspath(path)
    try:
        if os.path.commonpath([absolute, REPO]) == REPO:
            return os.path.relpath(absolute, REPO)
    except ValueError:
        pass
    return absolute


def load_definition(path):
    """Read and validate one sweep definition without importing simulator code."""
    path = find_file(path)
    spec = importlib.util.spec_from_file_location("sweep_definition", path)
    if spec is None:
        raise ValueError(path + ": not a Python sweep definition")
    module = importlib.util.module_from_spec(spec)
    write_bytecode, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = write_bytecode

    unknown = {name for name in vars(module)
               if name.isupper() and not name.startswith("_")} - DEFINITION_FIELDS
    if unknown:
        raise ValueError(f"unknown sweep definition fields: {sorted(unknown)}")
    missing = DEFINITION_FIELDS - {name for name in vars(module) if name.isupper()}
    if missing:
        raise ValueError(f"missing sweep definition fields: {sorted(missing)}")

    definition = {name: getattr(module, name) for name in DEFINITION_FIELDS}
    definition["path"] = path
    definition["BASE_CONFIG"] = find_file(definition["BASE_CONFIG"])
    if not isinstance(definition["FIXED"], dict) or not isinstance(definition["AXES"], dict):
        raise ValueError("FIXED and AXES must be dictionaries")
    if not isinstance(definition["METRICS"], (list, tuple)) or not definition["METRICS"]:
        raise ValueError("METRICS must be a non-empty list")

    fixed = definition["FIXED"]
    axes = definition["AXES"]
    if set(fixed) & set(axes):
        raise ValueError(f"settings cannot be both fixed and swept: {sorted(set(fixed) & set(axes))}")
    unsupported = set(axes) - MATRIX_AXES
    if unsupported:
        raise ValueError(f"unsupported matrix axes: {sorted(unsupported)}")
    missing_axes = {"SERVER_CF", "ROUTER_FIB_UPT"} - set(axes)
    if missing_axes:
        raise ValueError(f"missing required axes: {sorted(missing_axes)}")
    for name, values in axes.items():
        if not isinstance(values, (list, tuple)) or not values:
            raise ValueError(f"axis {name} must be a non-empty list")
        if any(not isinstance(value, (str, int, float, bool)) and value is not None for value in values):
            raise ValueError(f"axis {name} contains a non-scalar value")
        if len(set(values)) != len(values):
            raise ValueError(f"axis {name} contains duplicate values")

    invalid_metrics = set(definition["METRICS"]) - set(METRIC_FIELDS)
    if invalid_metrics:
        raise ValueError(f"unknown metrics: {sorted(invalid_metrics)}")
    if len(set(definition["METRICS"])) != len(definition["METRICS"]):
        raise ValueError("METRICS contains duplicates")
    definition["AXES"] = {name: list(values) for name, values in axes.items()}
    definition["METRICS"] = list(definition["METRICS"])
    return definition


def main_command(base_config, overrides, dump_config=False):
    command = [sys.executable, MAIN, repo_path(base_config)]
    for name, value in overrides.items():
        command.extend(["--set", f"{name}={value!r}"])
    if dump_config:
        command.append("--dump-config")
    return command


def resolved_settings(definition):
    """Let main.py validate the config and every override before starting cells."""
    first_values = {name: values[0] for name, values in definition["AXES"].items()}
    overrides = {**definition["FIXED"], **first_values}
    result = subprocess.run(
        main_command(definition["BASE_CONFIG"], overrides, dump_config=True),
        cwd=REPO, capture_output=True, text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr + result.stdout).strip()
        raise ValueError("main.py rejected the sweep configuration:\n" + detail)

    settings = {}
    for line in result.stdout.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        body = line.split("   # ", 1)[0].rstrip()
        name, separator, value = body.partition(" = ")
        if not separator:
            raise ValueError("cannot parse main.py --dump-config line: " + line)
        settings[name] = ast.literal_eval(value)
    if settings["VERBOSE_LEVEL"] < 1:
        raise ValueError("VERBOSE_LEVEL must be at least 1 for the selected log metrics")
    return settings


def make_cells(definition, settings):
    """Create cells in matrix order: delay, router threshold, server threshold."""
    axes = definition["AXES"]
    delays = axes.get("GRAPH_DELAY", [settings["GRAPH_DELAY"]])
    server_cfs = axes["SERVER_CF"]
    router_cfs = axes["ROUTER_FIB_UPT"]
    cells = []
    for delay in delays:
        for router_cf in router_cfs:
            for server_cf in server_cfs:
                overrides = dict(definition["FIXED"])
                if "GRAPH_DELAY" in axes:
                    overrides["GRAPH_DELAY"] = delay
                overrides["ROUTER_FIB_UPT"] = router_cf
                overrides["SERVER_CF"] = server_cf
                cells.append({
                    "index": len(cells),
                    "axes": {
                        "GRAPH_DELAY": delay,
                        "ROUTER_FIB_UPT": router_cf,
                        "SERVER_CF": server_cf,
                    },
                    "overrides": overrides,
                    "status": "pending",
                })
    return cells, delays, server_cfs, router_cfs


def current_git_commit():
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO, capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def write_json(path, data):
    """Atomically write JSON so an interrupted manifest is not half a line."""
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as output:
        json.dump(data, output, indent=2)
        output.write("\n")
    os.replace(temporary, path)


def ends_with_done(path):
    last_line = ""
    with open(path, encoding="utf-8", errors="replace") as log:
        for line in log:
            last_line = line.strip()
    return last_line == "DONE"


def execute_cell(cell, base_config, logs_dir):
    """Run one cell and return its outcome without mutating the shared cell."""
    stem = f"cell_{cell['index']:03d}"
    log_path = os.path.join(logs_dir, stem + ".log")
    stderr_path = os.path.join(logs_dir, stem + ".stderr")
    outcome = {
        "command": main_command(base_config, cell["overrides"]),
        "log": repo_path(log_path),
        "stderr": repo_path(stderr_path),
    }
    try:
        with open(log_path, "w", encoding="utf-8") as out, open(stderr_path, "w", encoding="utf-8") as err:
            result = subprocess.run(outcome["command"], cwd=REPO, stdout=out, stderr=err)
        outcome["returncode"] = result.returncode
        if result.returncode != 0:
            raise RuntimeError(f"{stem}: main.py exited {result.returncode}; see {stderr_path}")
        if not ends_with_done(log_path):
            raise RuntimeError(f"{stem}: log has no final DONE; see {log_path}")
        outcome["metrics"] = cell_from_metrics(parse_log_file(log_path))
    except Exception as error:
        outcome["status"] = "failed"
        outcome["error"] = str(error)
    else:
        outcome["status"] = "complete"
    return outcome


def resolve_jobs(jobs):
    if jobs < 0:
        raise ValueError("--jobs must be zero (auto) or a positive integer")
    if jobs == 0:
        return max(1, (os.cpu_count() or 2) - 2)
    return jobs


def run_cells(cells, base_config, logs_dir, jobs, manifest, manifest_path):
    """Run cells in independent subprocesses; store results in matrix order."""
    total = len(cells)
    completed = 0
    errors = []

    def record_outcome(cell, outcome):
        # Only the coordinating thread mutates cells or serializes the manifest.
        nonlocal completed
        cell.update(outcome)
        if cell["status"] == "complete":
            completed += 1
            print(f"[{completed}/{total}] cell_{cell['index']:03d} complete", file=sys.stderr)
        else:
            errors.append(cell["error"])
        write_json(manifest_path, manifest)

    if jobs == 1:
        for cell in cells:
            cell["status"] = "running"
            write_json(manifest_path, manifest)
            try:
                outcome = execute_cell(cell, base_config, logs_dir)
            except Exception as error:
                outcome = {"status": "failed", "error": str(error)}
            record_outcome(cell, outcome)
            if errors:
                raise RuntimeError(errors[0])
        return

    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {}
        for cell in cells:
            cell["status"] = "running"
            futures[pool.submit(execute_cell, cell, base_config, logs_dir)] = cell
        write_json(manifest_path, manifest)
        for future in concurrent.futures.as_completed(futures):
            cell = futures[future]
            try:
                outcome = future.result()
            except Exception as error:
                outcome = {"status": "failed", "error": str(error)}
            record_outcome(cell, outcome)
        if errors:
            raise RuntimeError(f"{len(errors)} of {total} cells failed: {errors[0]}")


def parse_args():
    parser = argparse.ArgumentParser(description="Run a matrix sweep through experiments/main.py.")
    parser.add_argument("definition", help="Python sweep definition file")
    parser.add_argument("-j", "--jobs", type=int, default=1,
                        help="concurrent main.py processes; 0 selects cores minus two (default: 1)")
    parser.add_argument("-o", "--output",
                        help="new output directory (default: results/sweep-<timestamp>)")
    return parser.parse_args()


def main():
    args = parse_args()
    output_root = None
    manifest = None
    manifest_path = None
    try:
        definition = load_definition(args.definition)
        settings = resolved_settings(definition)
        jobs = resolve_jobs(args.jobs)
        cells, delays, server_cfs, router_cfs = make_cells(definition, settings)
        output_root = os.path.abspath(args.output or os.path.join(
            REPO, "results", "sweep-" + datetime.now().strftime("%Y%m%d-%H%M%S")))
        if os.path.exists(output_root):
            raise ValueError("output directory already exists: " + output_root)
        logs_dir = os.path.join(output_root, "logs")
        os.makedirs(logs_dir)

        manifest_path = os.path.join(output_root, "manifest.json")
        manifest = {
            "status": "running",
            "definition": repo_path(definition["path"]),
            "base_config": repo_path(definition["BASE_CONFIG"]),
            "code_commit": current_git_commit(),
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "jobs": jobs,
            "settings": settings,
            "cells": cells,
        }
        write_json(manifest_path, manifest)
        print(f"Running {len(cells)} cells with {jobs} workers; output: {output_root}", file=sys.stderr)
        run_cells(cells, definition["BASE_CONFIG"], logs_dir, jobs, manifest, manifest_path)

        data = build_matrix_data(
            cells, delays, server_cfs, router_cfs, definition["METRICS"],
            settings["ROUTER_HOP_BY_HOP"], current_git_commit(),
            datetime.now().isoformat(timespec="seconds"),
        )
        matrix_dir = os.path.join(output_root, "matrix_data")
        os.makedirs(matrix_dir)
        mode = "hop_by_hop" if settings["ROUTER_HOP_BY_HOP"] else "first_decide"
        output_path = os.path.join(matrix_dir, f"sweep_data_log_{mode}.json")
        write_json(output_path, data)
        manifest["status"] = "complete"
        manifest["completed_at"] = datetime.now().isoformat(timespec="seconds")
        manifest["matrix_data"] = repo_path(output_path)
        write_json(manifest_path, manifest)
        print(output_path)
    except (ValueError, OSError, RuntimeError) as error:
        if manifest is not None:
            manifest["status"] = "failed"
            manifest["error"] = str(error)
            write_json(manifest_path, manifest)
        sys.exit("experiments/sweep.py: " + str(error))


if __name__ == "__main__":
    main()

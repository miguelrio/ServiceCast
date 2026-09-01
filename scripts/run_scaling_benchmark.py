#!/usr/bin/env python3
"""Run the scaling-benchmark matrix.

One job: enumerate the matrix from `constants_scaling`, spawn `measure_one` per
cell, collect the JSON rows, and write the CSV + manifest. No simulation code
lives here -- every run is a fresh subprocess for clean isolation, honest
peak_rss (RUSAGE_SELF in the child), and a per-run timeout so one runaway cell
cannot stall the matrix.

Matrix groups (see constants_scaling):
  A. factorial core -- 2 topologies x 4 arrival rates x 4 server counts = 32
     configs, each run PAIRED (verbose 1 / file  AND  verbose -1 / null),
     FACTORIAL_REPEATS times.
  B. one-at-a-time axes from baseline, OFAT_REPEATS times each (file mode).
  C. confirmation points, CONFIRMATION_REPEATS times (file mode).
  D. noise floor -- baseline x NOISE_FLOOR_REPEATS (file mode).

CLI:
  -c/--config   experiment-declaration module to load by path; it must define
                every attribute constants_scaling.py defines and keep the
                fixed invariants SERVICE/SERVER_LOAD_LAMBDA at their default
                values (default scripts/setup/constants_scaling.py)
  -o/--output   results dir (default results/scaling-<timestamp>)
  --axes a,b,c  subset of axis names to run
                (factorial | <ofat axis> | confirmation | noise_floor)
  --dry-run     print the matrix and the estimated count without running
  --timeout     per-run subprocess seconds (default the config's DEFAULT_TIMEOUT)
  --repeats     override every group's repeat count (quick runs)

Data flow: this script -> (measure_one -> placement) -> CSV ->
quick_look plots.
"""

import os
import sys
import csv
import json
import copy
import importlib.util
import time
import shutil
import socket
import platform
import argparse
import subprocess
from datetime import datetime
from itertools import product

# --- config loading -----------------------------------------------------------
#
# Everything downstream -- enumerate_cells, write_manifest, and the config
# copy in the results dir -- reads the one module load_config returns, so
# the provenance records cannot disagree with what ran.

# The benchmark wires exactly one fixed service, so SERVICE/SERVER_LOAD_LAMBDA
# are invariants rather than knobs: load_config pins every -c config to the
# default file's values (measure_one reads them from its own import).
from setup import constants_scaling as default_constants

FIXED_ATTRS = ("SERVICE", "SERVER_LOAD_LAMBDA")

REQUIRED_ATTRS = (
    "SERVICE", "SERVER_LOAD_LAMBDA",
    "BASELINE", "FACTORIAL_AXES", "FACTORIAL_REPEATS",
    "OFAT_AXES", "OFAT_REPEATS",
    "CONFIRMATION_CONFIGS", "CONFIRMATION_REPEATS",
    "NOISE_FLOOR_REPEATS", "DEFAULT_TIMEOUT",
    "FACTORIAL_FILE_VERBOSE", "FACTORIAL_NULL_VERBOSE",
)


def load_config(path):
    """Load the experiment-declaration module from `path`, validating that it
    defines every attribute constants_scaling.py defines (a custom config is a
    copy of that file with edited values) and keeps the fixed invariants."""
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise SystemExit(f"config file not found: {path}")
    spec = importlib.util.spec_from_file_location("scaling_config", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load a config module from {path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise SystemExit(f"config {path} failed to import: {exc}") from exc
    missing = [attr for attr in REQUIRED_ATTRS if not hasattr(module, attr)]
    if missing:
        raise SystemExit(
            f"config {path} is missing required attributes: "
            f"{', '.join(missing)}. A config module must define everything "
            f"constants_scaling.py defines.")
    changed = [attr for attr in FIXED_ATTRS
               if getattr(module, attr) != getattr(default_constants, attr)]
    if changed:
        details = ", ".join(
            f"{a}={getattr(module, a)!r} (must stay "
            f"{getattr(default_constants, a)!r})" for a in changed)
        raise SystemExit(
            f"config {path} changes fixed invariants: {details}. A custom "
            f"config may vary the matrix (BASELINE, axes, repeats, timeout) "
            f"but not SERVICE/SERVER_LOAD_LAMBDA: the benchmark wires a "
            f"single fixed service, and a differing value would be silently "
            f"ignored by measure_one.")
    return module


# --- local git helper ---------------------------------------------------------

def current_git_commit():
    project_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=project_path, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except Exception:
        return "unknown"


# --- matrix enumeration ------------------------------------------------------
#
# Each cell is a complete knob dict for measure_one: the baseline config plus
# the axis overrides plus log_mode/verbose_level (the factorial's paired
# file/null runs) plus identity (axis, run_id, repeat_idx).

def _base_knobs(cfg):
    return copy.deepcopy(cfg.BASELINE)


def _cell(knobs, axis, run_id, repeat_idx, log_mode, verbose_level):
    cell = copy.deepcopy(knobs)
    cell["axis"] = axis
    cell["run_id"] = run_id
    cell["repeat_idx"] = repeat_idx
    cell["log_mode"] = log_mode
    cell["verbose_level"] = verbose_level
    return cell


# These five axes sweep a knob the base format below does not carry; they
# append it so every config point gets a distinct run_id.
_RUN_ID_EXTRA = {
    "session_length": "_sl{session_lambda}",
    "change_factor":  "_cf{server_cf}",
    "prop_delay":     "_pd{prop_delay}",
    "hop_by_hop":     "_hh{hop_by_hop}",
    "verbosity":      "_v{verbose_level}",
}


def _run_id(axis, knobs):
    """A short, descriptive, filesystem-safe id for one config point."""
    rid = "{axis}_{top}_{s}srv_{c}cli_a{al}_k{k}slot_d{dur}".format(
        axis=axis,
        top=knobs["topology"],
        s=knobs["num_servers"], c=knobs["num_clients"],
        al=knobs["arrival_lambda"], k=knobs["slots"], dur=knobs["sim_duration"])
    extra = _RUN_ID_EXTRA.get(axis)
    if extra:
        rid += extra.format(**knobs)
    return rid


def enumerate_cells(cfg, axes_filter=None, repeats_override=None):
    """Yield every cell in the matrix as a knob dict.

    cfg              the loaded experiment-declaration module (load_config).
    axes_filter     set of axis names to keep (None = all).
    repeats_override if set, every group's repeat count becomes this value.
    """
    fr = repeats_override if repeats_override is not None else cfg.FACTORIAL_REPEATS
    orr = repeats_override if repeats_override is not None else cfg.OFAT_REPEATS
    cr = repeats_override if repeats_override is not None else cfg.CONFIRMATION_REPEATS
    nr = repeats_override if repeats_override is not None else cfg.NOISE_FLOOR_REPEATS

    def keep(axis):
        return axes_filter is None or axis in axes_filter

    # --- Group A: factorial core (paired file/null runs) ----------------------
    if keep("factorial"):
        for topo, al, ns in product(cfg.FACTORIAL_AXES["topology"],
                                     cfg.FACTORIAL_AXES["arrival_lambda"],
                                     cfg.FACTORIAL_AXES["num_servers"]):
            knobs = _base_knobs(cfg)
            knobs["topology"] = topo
            knobs["arrival_lambda"] = al
            knobs["num_servers"] = ns
            rid = _run_id("factorial", knobs)
            for r in range(fr):
                yield _cell(knobs, "factorial", rid, r, "file",
                            cfg.FACTORIAL_FILE_VERBOSE)
                yield _cell(knobs, "factorial", rid, r, "null",
                            cfg.FACTORIAL_NULL_VERBOSE)

    # --- Group B: one-at-a-time axes ----------------------------------------
    for axis_name, overrides in cfg.OFAT_AXES.items():
        if not keep(axis_name):
            continue
        for override in overrides:
            knobs = _base_knobs(cfg)
            knobs.update(override)
            # total_slots -> per-server slots, mirrored from measure_one.run so
            # run_ids below see the resolved capacity (several load_curve cells
            # share an arrival_lambda at different totals; slots disambiguates).
            if knobs.get("total_slots") is not None:
                knobs["slots"] = knobs["total_slots"] // knobs["num_servers"]
            rid = _run_id(axis_name, knobs)
            # The verbosity axis varies verbose_level itself; every other axis
            # runs at the baseline verbose level (1) in file mode.
            verbose_level = knobs["verbose_level"]
            for r in range(orr):
                yield _cell(knobs, axis_name, rid, r, "file", verbose_level)

    # --- Group C: confirmation points ---------------------------------------
    if keep("confirmation"):
        for override in cfg.CONFIRMATION_CONFIGS:
            knobs = _base_knobs(cfg)
            knobs.update(override)
            rid = _run_id("confirmation", knobs)
            for r in range(cr):
                yield _cell(knobs, "confirmation", rid, r, "file",
                            cfg.BASELINE["verbose_level"])

    # --- Group D: noise floor (baseline x N) --------------------------------
    if keep("noise_floor"):
        knobs = _base_knobs(cfg)
        rid = _run_id("noise_floor", knobs)
        for r in range(nr):
            yield _cell(knobs, "noise_floor", rid, r, "file",
                        cfg.BASELINE["verbose_level"])


# --- per-cell subprocess run -------------------------------------------------

def run_one(cell, timeout):
    """Spawn measure_one for one cell; return (row_dict, parent_wall_s).

    The parent measures wall_s (subprocess wall, includes ~0.15 s startup) and
    merges it into the child's row, overriding the child's own wall_s. A
    subprocess.TimeoutExpired is recorded as status=timeout.
    """
    knobs_json = json.dumps(cell)
    env = {**os.environ, "PYTHONPATH": "src"}
    # sys.executable so the child uses the same interpreter (one that has the
    # simulator's deps). The orchestrator must be launched with that interpreter.
    cmd = [sys.executable, os.path.join("scripts", "measure_one.py"), knobs_json]

    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        parent_wall = time.perf_counter() - t0
        row = _empty_row(cell)
        row["status"] = "timeout"
        row["wall_s"] = parent_wall
        row["child_wall_s"] = parent_wall
        return row, parent_wall

    parent_wall = time.perf_counter() - t0
    if proc.returncode != 0:
        row = _empty_row(cell)
        row["status"] = f"error:exit{proc.returncode}"
        row["error"] = (proc.stderr or "").strip()[:500]
        row["wall_s"] = parent_wall
        row["child_wall_s"] = parent_wall
        return row, parent_wall

    out = proc.stdout.strip()
    if not out:
        row = _empty_row(cell)
        row["status"] = "error:empty_stdout"
        row["error"] = (proc.stderr or "").strip()[:500]
        row["wall_s"] = parent_wall
        row["child_wall_s"] = parent_wall
        return row, parent_wall

    try:
        row = json.loads(out.splitlines()[-1])
    except json.JSONDecodeError as exc:
        row = _empty_row(cell)
        row["status"] = "error:bad_json"
        row["error"] = f"{exc}: {out[:200]}"
        row["wall_s"] = parent_wall
        row["child_wall_s"] = parent_wall
        return row, parent_wall

    # Override wall_s with the parent-measured subprocess wall.
    row["wall_s"] = parent_wall
    return row, parent_wall


def _empty_row(cell):
    """A row shell for failed/timeout cells, so a gap is visible in the data."""
    row = {k: None for k in CSV_COLUMNS}
    row["axis"] = cell.get("axis")
    row["run_id"] = cell.get("run_id")
    row["repeat_idx"] = cell.get("repeat_idx", 0)
    row["log_mode"] = cell.get("log_mode")
    row["verbose_level"] = cell.get("verbose_level")
    for k in ("topology", "num_servers", "num_clients", "arrival_lambda",
              "session_lambda", "session_scale", "slots", "total_slots",
              "sim_duration", "server_cf", "router_cf", "prop_delay",
              "hop_by_hop", "alpha", "seed"):
        row[k] = cell.get(k)
    return row


# --- CSV columns -------------------------------------------------------------

CSV_COLUMNS = [
    # identity
    "axis", "run_id", "repeat_idx", "log_mode", "verbose_level",
    # config (the config_key components, in order)
    "topology", "num_servers", "num_clients", "arrival_lambda",
    "session_lambda", "session_scale", "slots", "total_slots", "sim_duration",
    "server_cf", "router_cf", "prop_delay", "hop_by_hop", "alpha", "seed",
    "config_key",
    # cost
    "build_s", "sim_s", "parse_s", "wall_s", "child_wall_s",
    "log_bytes", "log_lines", "peak_rss_mb", "status",
    # workload counters (file-mode rows only; blank for null)
    "created", "recv_total", "recv_announce", "recv_withdraw",
    "fib_updates", "served", "blocked_rate",
    "per_server_served", "offered_load_pct",
    # diagnostics
    "error",
]


def write_csv(rows, path):
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS,
                                extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            # config_key as a pipe-joined string for readable joins
            ck = row.get("config_key")
            if isinstance(ck, list):
                row["config_key"] = "|".join(str(x) for x in ck)
            writer.writerow(row)


def write_manifest(path, cfg, started_at, ended_at, n_cells, n_ok, axes_filter,
                   repeats_override, timeout):
    manifest = {
        "code_commit": current_git_commit(),
        "generated_at": ended_at,
        "started_at": started_at,
        "ended_at": ended_at,
        "platform": platform.platform(),
        "hostname": socket.gethostname(),
        "python_version": sys.version.split()[0],
        "cpu_count": os.cpu_count(),
        "interpreter": sys.executable,
        "total_cells": n_cells,
        "ok_cells": n_ok,
        "axes_filter": sorted(axes_filter) if axes_filter else "all",
        "repeats_override": repeats_override,
        "per_run_timeout_s": timeout,
        "constants": {
            "BASELINE": cfg.BASELINE,
            "FACTORIAL_AXES": cfg.FACTORIAL_AXES,
            "OFAT_AXES": cfg.OFAT_AXES,
            "CONFIRMATION_CONFIGS": cfg.CONFIRMATION_CONFIGS,
            "FACTORIAL_REPEATS": cfg.FACTORIAL_REPEATS,
            "OFAT_REPEATS": cfg.OFAT_REPEATS,
            "CONFIRMATION_REPEATS": cfg.CONFIRMATION_REPEATS,
            "NOISE_FLOOR_REPEATS": cfg.NOISE_FLOOR_REPEATS,
        },
    }
    with open(path, "w") as fh:
        json.dump(manifest, fh, indent=2)


# --- CLI ---------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Run the scaling-benchmark matrix.")
    p.add_argument("-c", "--config", default="scripts/setup/constants_scaling.py",
                   help="Experiment-declaration module to load by path; must "
                        "define every attribute constants_scaling.py defines "
                        "(default: scripts/setup/constants_scaling.py).")
    p.add_argument("-o", "--output", default=None,
                   help="Output directory (default results/scaling-<timestamp>).")
    p.add_argument("--axes", default=None,
                   help="Comma-separated subset of axis names to run "
                        "(factorial | <ofat axis> | confirmation | noise_floor).")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the matrix and the estimated count without running.")
    p.add_argument("--timeout", type=float, default=None,
                   help="Per-run subprocess timeout in seconds "
                        "(default: the config's DEFAULT_TIMEOUT).")
    p.add_argument("--repeats", type=int, default=None,
                   help="Override every group's repeat count (for quick runs).")
    return p.parse_args()


def main():
    args = parse_args()

    cfg = load_config(args.config)
    timeout = args.timeout if args.timeout is not None else cfg.DEFAULT_TIMEOUT

    axes_filter = None
    if args.axes:
        axes_filter = set(a.strip() for a in args.axes.split(",") if a.strip())

    # Enumerate once up front (dry-run or real).
    cells = list(enumerate_cells(cfg, axes_filter, args.repeats))

    if args.dry_run:
        print(f"Matrix enumeration ({len(cells)} cells):")
        by_axis = {}
        for c in cells:
            by_axis.setdefault(c["axis"], 0)
            by_axis[c["axis"]] += 1
        for axis in sorted(by_axis):
            print(f"  {axis:28s} {by_axis[axis]:>5d}")
        print(f"  {'TOTAL':28s} {len(cells):>5d}")
        # rough time estimate using the calibration range (0.5-5.5 s/run)
        print(f"\nEstimated serial runtime: "
              f"{len(cells) * 0.5:.0f}-{len(cells) * 5.5:.0f} s "
              f"(plus {len(cells) * 0.15:.0f} s subprocess startup).")
        return

    # Output directory.
    if args.output:
        output_root = args.output
    else:
        output_root = os.path.join(
            "results", "scaling-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    os.makedirs(output_root, exist_ok=True)

    csv_path = os.path.join(output_root, "scaling_runtime.csv")
    manifest_path = os.path.join(output_root, "manifest.json")
    config_copy_path = os.path.join(output_root, "config.py")

    # Copy the config module into the results dir (provenance), mirroring the
    # sweep's behaviour.
    shutil.copyfile(args.config, config_copy_path)

    started_at = datetime.now().isoformat(timespec="seconds")
    print(f"Scaling benchmark: {len(cells)} cells -> {csv_path}",
          file=sys.stderr)
    print(f"  axes_filter={axes_filter or 'all'}, "
          f"repeats_override={args.repeats}, timeout={timeout}s",
          file=sys.stderr)

    rows = []
    n_ok = 0
    for i, cell in enumerate(cells, 1):
        row, _ = run_one(cell, timeout)
        rows.append(row)
        if row.get("status") == "ok":
            n_ok += 1
        status = row.get("status", "?")
        sim_s = row.get("sim_s")
        log_mb = (row.get("log_bytes") or 0) / (1024.0 * 1024.0)
        sim_str = f"{sim_s:.3f}s" if sim_s is not None else "    -"
        print(f"  [{i:>4d}/{len(cells)}] {cell['axis']:>22s} "
              f"{cell['run_id']:<28s} r{cell['repeat_idx']} "
              f"{cell['log_mode']:>4s} v{cell['verbose_level']:>2} "
              f"-> {status:>10s}  sim={sim_str}  log={log_mb:6.2f}MB",
              file=sys.stderr)

    ended_at = datetime.now().isoformat(timespec="seconds")

    write_csv(rows, csv_path)
    write_manifest(manifest_path, cfg, started_at, ended_at, len(cells), n_ok,
                   axes_filter, args.repeats, timeout)

    print(f"\nWrote {csv_path} ({n_ok}/{len(cells)} ok)", file=sys.stderr)
    print(f"Wrote {manifest_path}", file=sys.stderr)
    print(f"Wrote {config_copy_path}", file=sys.stderr)
    # The CSV path to stdout so a downstream pipe can consume it.
    print(csv_path)


if __name__ == "__main__":
    main()

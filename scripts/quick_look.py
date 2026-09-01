#!/usr/bin/env python3
"""Simple, self-describing plots straight from the benchmark CSV.

Reads ONLY scaling_runtime.csv — no simulator, no fitting. Each plot carries
its own context (what's held fixed, what varies, the median values) in plain
English, so you don't need a separate table to know what you're looking at.

Outputs (into the CSV's directory):
  quick_plots/  runtime and log size vs each swept knob, with a multi-line
                context block and median values annotated on the points. The
                capacity axes (load_curve, capacity_90) add a third blocked-rate
                panel, plus quick_blocking.png overlays every capacity's
                blocked rate on one shared offered-load axis.

CLI:  python3 scripts/quick_look.py -d results/scaling-full/scaling_runtime.csv
"""

import os
import sys
import csv
import textwrap
import argparse
import statistics
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

INK = "#1e293b"
MUTED = "#475569"

# axis -> the knob it sweeps. None = not plotted vs a knob.
AXIS_KNOB = {
    "duration": "sim_duration",
    "session_length": "session_lambda",
    "capacity_90": "total_slots",
    "prop_delay": "prop_delay",
    "clients_fixed_total": "num_clients",
    "arrival_sweep": "arrival_lambda",
    "load_curve": "arrival_lambda",
    "verbosity": "verbose_level",
    "change_factor": "server_cf",
    "hop_by_hop": "hop_by_hop",
    "noise_floor": None,
    "confirmation": None,
}

# Full human-readable names (no code identifiers in the plots).
LABEL = {
    "topology": "topology", "num_servers": "number of servers",
    "num_clients": "number of clients", "arrival_lambda": "request arrival rate",
    "session_lambda": "mean session length", "slots": "server slots",
    "total_slots": "total network slots",
    "sim_duration": "simulated duration", "verbose_level": "verbose level",
    "server_cf": "server change factor", "router_cf": "router FIB threshold",
    "prop_delay": "propagation delay", "hop_by_hop": "hop-by-hop forwarding",
}
UNIT = {
    "sim_duration": " (s)", "arrival_lambda": " (s)", "session_lambda": " (s)",
    "prop_delay": " (s)",
}

# Readable axis title (the prefix before the colon).
AXIS_TITLE = {
    "duration": "simulated duration",
    "session_length": "session length",
    "capacity_90": "capacity scaling at 90% offered load",
    "prop_delay": "propagation delay",
    "clients_fixed_total": "clients at fixed total load",
    "arrival_sweep": "arrival rate sweep (clients fixed per facet)",
    "load_curve": "load curve (one row per total capacity)",
    "verbosity": "verbose level",
    "change_factor": "change factor",
    "hop_by_hop": "hop-by-hop forwarding",
}


def _x_label(axis, knob):
    """Honest x-axis label. For the two client axes the client count alone is
    NOT the driver, so the label must say what's actually varying."""
    if axis == "clients_fixed_total":
        return "number of clients  (total request rate held constant)"
    if axis in ("arrival_sweep", "load_curve"):
        return "offered load %  =  (1/λ) × 100 s mean session ÷ total slots   ·   λ per tick"
    if axis == "capacity_90":
        return "total network slots  (each point's λ co-varied → 90% offered load)"
    if axis == "session_length":
        return "mean session length (s)  =  session_lambda × session_scale"
    if axis == "verbosity":
        return "verbose level  (−1 = logging off)"
    if axis == "change_factor":
        return "server change factor  (router FIB threshold co-varies)"
    return _axis_label(knob)
_FIXED_COLS = list(LABEL.keys())


def _offered_load_pct(row):
    """Compute offered load % from a CSV row's config fields.

    Formula: (1/λ) × (session_lambda × session_scale) / (num_servers × slots) × 100
    This is deterministic: it depends only on the config knobs.
    """
    lam = _f(row["arrival_lambda"])
    sl = _f(row["session_lambda"])
    ss = _f(row["session_scale"])
    ns = _f(row["num_servers"])
    slots = _f(row["slots"])
    if not lam or not ns or not slots:
        return None
    mean_session = (sl or 10) * (ss or 10)
    capacity = ns * slots
    return (1.0 / lam) * mean_session / capacity * 100


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def load_rows(path):
    with open(path, "rb") as fh:
        if fh.read(4).startswith(b"PK"):
            raise SystemExit(
                f"{path} is an XLSX (ZIP), not a CSV — this happens when Excel "
                f"saves the file. The machine-readable seam must stay a real CSV.")
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def _axis_label(knob):
    return LABEL.get(knob, knob) + UNIT.get(knob, "")


def _held_fixed_pairs(rows, swept_knob):
    """[('topology','Dfn'), ('number of servers','5'), ...] for constant cols."""
    pairs = []
    for c in _FIXED_COLS:
        if c == swept_knob:
            continue
        vals = {r[c] for r in rows}
        # skip empty columns (e.g. total_slots is blank on rows from axes that
        # don't use it) -- a blank "held fixed" pair would be noise
        if len(vals) == 1 and next(iter(vals), "") not in ("", None):
            v = next(iter(vals))
            if c == "session_lambda":
                # λ is the exponential's parameter, not seconds: show the mean
                # session it produces (λ × scale) so the value reads in real time
                sc = {r["session_scale"] for r in rows}
                if len(sc) == 1:
                    pairs.append(("mean session length",
                                  f"{float(v) * float(next(iter(sc))):g}s"
                                  f"  (session_lambda {v} × scale {next(iter(sc))})"))
                    continue
            pairs.append((LABEL[c], v))
    return pairs


def _context_block(fig, pairs, varying_line):
    """Multi-line context block under the title, filling the title space."""
    fixed_str = "  ·  ".join(f"{k}: {v}" for k, v in pairs)
    wrapped = textwrap.wrap("Held fixed:  " + fixed_str, width=105)
    lines = wrapped + [varying_line]
    y_top = 0.93
    for i, ln in enumerate(lines):
        fig.text(0.5, y_top - i * 0.024, ln, ha="center", fontsize=9.5, color=MUTED)
    return len(lines)


def _style(ax, xlabel, ylabel):
    ax.set_xlabel(xlabel, fontsize=11, color=INK)
    ax.set_ylabel(ylabel, fontsize=11, color=INK)
    ax.tick_params(labelsize=9, colors=MUTED)
    ax.grid(True, linestyle=":", linewidth=0.5, color="#cbd5e1")


def _save(out_dir, name):
    p = os.path.join(out_dir, name)
    plt.savefig(p, dpi=130, bbox_inches="tight")
    plt.close()
    print(f"  {p}", file=sys.stderr)


def _ofat_plot(rows, axis, knob, out_dir):
    """runtime and log size vs the swept knob: repeat points + median line,
    with a multi-line context block and median values annotated."""
    sub = [r for r in rows if r["axis"] == axis and r["status"] == "ok" and r["log_mode"] == "file"]
    if not sub:
        return
    # group rows by the knob value. The knob may be numeric OR categorical
    # (e.g. hop_by_hop is boolean: "False"/"True"), so don't assume float().
    groups = defaultdict(list)
    for r in sub:
        groups[r[knob]].append(r)
    try:
        order = sorted(groups, key=lambda k: float(k))
        x_of = {k: float(k) for k in order}
        categorical = False
        # session_lambda is the size distribution's parameter, not seconds; the
        # honest x is the mean session it produces: lambda x session_scale.
        if knob == "session_lambda":
            scale = float(sub[0]["session_scale"])
            x_of = {k: float(k) * scale for k in order}
    except ValueError:
        order = sorted(groups)
        x_of = {k: i for i, k in enumerate(order)}
        categorical = True
    xs = [x_of[k] for k in order]
    sim_med = [statistics.median([_f(r["sim_s"]) for r in groups[k]]) for k in order]
    log_med = [statistics.median([_f(r["log_bytes"]) for r in groups[k]]) / 1048576 for k in order]
    pairs = _held_fixed_pairs(sub, knob)
    n_rep = max(len(groups[k]) for k in order) if order else 0

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 5.2))
    fig.suptitle(f"{AXIS_TITLE.get(axis, axis)}: how runtime & log size vary with {LABEL[knob]}",
                 fontsize=13, fontweight="bold", color=INK, y=1.0)
    _context_block(fig, pairs,
                   f"Varying: {_x_label(axis, knob)}   ·   points = {n_rep} repeats, line = median")

    for k in order:
        x = x_of[k]
        a1.scatter([x] * len(groups[k]), [_f(r["sim_s"]) for r in groups[k]],
                   s=24, color="#378ADD", alpha=0.45, zorder=2)
        a2.scatter([x] * len(groups[k]), [_f(r["log_bytes"]) / 1048576 for r in groups[k]],
                   s=24, color="#EF9F27", alpha=0.45, zorder=2)
    a1.plot(xs, sim_med, color="#1d4ed8", linewidth=2, marker="o", markersize=6, zorder=3)
    a2.plot(xs, log_med, color="#b45309", linewidth=2, marker="o", markersize=6, zorder=3)

    for x, s in zip(xs, sim_med):
        a1.annotate(f"{s:.2f}s", (x, s), textcoords="offset points", xytext=(0, 7),
                    ha="center", fontsize=8.5, color="#1d4ed8")
    for x, l in zip(xs, log_med):
        a2.annotate(f"{l:.1f}MB", (x, l), textcoords="offset points", xytext=(0, 7),
                    ha="center", fontsize=8.5, color="#b45309")

    _style(a1, _x_label(axis, knob), "runtime (s)")
    _style(a2, _x_label(axis, knob), "log size (MB)")
    a1.set_ylim(bottom=0)
    a2.set_ylim(bottom=0)
    if categorical:
        for ax in (a1, a2):
            ax.set_xticks(xs)
            ax.set_xticklabels(order)
    elif knob == "session_lambda":
        # per-point ticks (25 / 50 / 100 / 200 / 400 s); auto ticks would
        # suggest intermediate session lengths that were never run
        for ax in (a1, a2):
            ax.set_xticks(xs)
            ax.set_xticklabels([f"{x:g}" for x in xs])
    fig.tight_layout(rect=[0, 0.01, 1, 0.82])
    _save(out_dir, f"quick_{axis}.png")


def _arrival_sweep_plot(rows, out_dir):
    """arrival_sweep: one 2-column facet per num_clients value.

    Each facet shows runtime and log size vs offered load % (left = lighter,
    right = heavier), with λ under each tick (25% → 400%). Points = repeats,
    line = median.
    """
    sub = [r for r in rows if r["axis"] == "arrival_sweep" and r["status"] == "ok" and r["log_mode"] == "file"]
    if not sub:
        return

    # group by num_clients
    by_n = defaultdict(list)
    for r in sub:
        by_n[r["num_clients"]].append(r)
    n_vals = sorted(by_n, key=lambda k: float(k))

    # one row of subplots, 2 cols (runtime, log size) per N facet
    n_facets = len(n_vals)
    fig, axes = plt.subplots(n_facets, 2, figsize=(13, 3.2 * n_facets),
                             squeeze=False)
    fig.suptitle("arrival rate sweep: runtime & log size vs λ, one row per client count N",
                 fontsize=13, fontweight="bold", color=INK, y=1.0)

    # context block: what's fixed, what the rows are, what varies inside a row
    pairs = _held_fixed_pairs(sub, "arrival_lambda")
    fixed_str = "  ·  ".join(f"{k}: {v}" for k, v in pairs)
    wrapped = textwrap.wrap("Held fixed:  " + fixed_str, width=105)
    lams = sorted({float(r["arrival_lambda"]) for r in sub})
    loads = [lp for lp in (_offered_load_pct(r) for r in sub) if lp is not None]
    by_cell = defaultdict(list)
    for r in sub:
        by_cell[(r["num_clients"], r["arrival_lambda"])].append(r)
    n_rep = max(map(len, by_cell.values())) if by_cell else 0
    rows_line = (f"Rows: number of clients N = {', '.join(n_vals)}   ·   "
                 f"each row sweeps λ {lams[0]:g}–{lams[-1]:g} s "
                 f"(offered load {min(loads):.0f}–{max(loads):.0f}%)")
    vary_line = (f"Varying: offered load % (λ per tick; left = lighter, right = heavier)"
                 f"   ·   points = {n_rep} repeats, line = median")
    y = 0.96
    for ln in wrapped:
        fig.text(0.5, y, ln, ha="center", fontsize=9, color=MUTED)
        y -= 0.012
    for ln in (rows_line, vary_line):
        fig.text(0.5, y, ln, ha="center", fontsize=9.5, color=MUTED)
        y -= 0.012

    for row_i, n_val in enumerate(n_vals):
        grp = by_n[n_val]
        # group by arrival_lambda within this N, x-ordered by offered load %
        by_lam = defaultdict(list)
        for r in grp:
            by_lam[r["arrival_lambda"]].append(r)
        order = sorted(by_lam, key=lambda k: _offered_load_pct(by_lam[k][0]))
        xs = [_offered_load_pct(by_lam[k][0]) for k in order]
        sim_med = [statistics.median([_f(r["sim_s"]) for r in by_lam[k]]) for k in order]
        log_med = [statistics.median([_f(r["log_bytes"]) for r in by_lam[k]]) / 1048576 for k in order]

        a1, a2 = axes[row_i]

        # scatter repeats at the offered-load % position
        for k in order:
            x = _offered_load_pct(by_lam[k][0])
            a1.scatter([x] * len(by_lam[k]), [_f(r["sim_s"]) for r in by_lam[k]],
                       s=20, color="#378ADD", alpha=0.45, zorder=2)
            a2.scatter([x] * len(by_lam[k]), [_f(r["log_bytes"]) / 1048576 for r in by_lam[k]],
                       s=20, color="#EF9F27", alpha=0.45, zorder=2)
        a1.plot(xs, sim_med, color="#1d4ed8", linewidth=2, marker="o", markersize=5, zorder=3)
        a2.plot(xs, log_med, color="#b45309", linewidth=2, marker="o", markersize=5, zorder=3)

        # two stacked rows: % on the tick row, λ on a lower row at alternating
        # depths -- the 25%/50% pair sits only ~6% of the axis apart, so same-
        # depth λ labels would overlap (same treatment as capacity_90's tiers)
        for ax in (a1, a2):
            ax.set_xticks(xs)
            ax.set_xticklabels([f"{_offered_load_pct(by_lam[k][0]):.0f}%"
                                for k in order], fontsize=8)
            for i, (k, x) in enumerate(zip(order, xs)):
                ax.annotate(f"λ={float(k):.4g}", xy=(x, 0),
                            xycoords=("data", "axes fraction"),
                            xytext=(0, -17 if i % 2 == 0 else -36),
                            textcoords="offset points",
                            ha="center", va="top", fontsize=8, color=MUTED,
                            annotation_clip=False)
            ax.set_ylim(bottom=0)

        _style(a1, "", "")
        _style(a2, "", "")
        a1.set_xlabel("")
        a2.set_xlabel("")
        # after _style, which resets the axis labels
        a1.set_title(f"N = {n_val} clients", loc="left", fontsize=11,
                     fontweight="bold", color=INK)
        a1.set_ylabel("runtime (s)", fontsize=10, color=INK)
        a2.set_ylabel("log size (MB)", fontsize=10, color=INK)

        # annotate medians
        for x, s in zip(xs, sim_med):
            a1.annotate(f"{s:.2f}s", (x, s), textcoords="offset points", xytext=(0, 6),
                        ha="center", fontsize=7.5, color="#1d4ed8")
        for x, l in zip(xs, log_med):
            a2.annotate(f"{l:.1f}MB", (x, l), textcoords="offset points", xytext=(0, 6),
                        ha="center", fontsize=7.5, color="#b45309")

    # extra row spacing: the λ row sits ~27pt below each panel, and tight_layout's
    # default inter-row gap would drop it onto the next facet's title
    fig.subplots_adjust(top=y - 0.08, bottom=0.03, left=0.07, right=0.985,
                        hspace=0.55, wspace=0.2)
    _save(out_dir, "quick_arrival_sweep.png")


def _load_curve_plot(rows, out_dir):
    """load_curve: one 3-column facet per total capacity T.

    Each facet shows runtime, log size and blocked rate vs offered load %
    (30% → 150%, left = lighter, right = heavier), with λ under each tick.
    The 90% tick in every facet is the capacity_90 operating point shared with
    that axis. Points = repeats, line = median; blocked-rate panels share a fixed
    0-100% scale so facets are comparable (sub-saturation zeros are real zeros).
    """
    sub = [r for r in rows if r["axis"] == "load_curve" and r["status"] == "ok" and r["log_mode"] == "file"]
    if not sub:
        return

    # group by total_slots
    by_t = defaultdict(list)
    for r in sub:
        by_t[r["total_slots"]].append(r)
    t_vals = sorted(by_t, key=lambda k: float(k))

    # one row of subplots, 3 cols (runtime, log size, blocked rate) per T facet
    n_facets = len(t_vals)
    fig, axes = plt.subplots(n_facets, 3, figsize=(18, 3.2 * n_facets),
                             squeeze=False)
    fig.suptitle("load curve: runtime, log size & blocked rate vs λ, one row per total capacity T",
                 fontsize=13, fontweight="bold", color=INK, y=1.0)

    # context block: what's fixed, what the rows are, what varies inside a row
    pairs = _held_fixed_pairs(sub, "arrival_lambda")
    fixed_str = "  ·  ".join(f"{k}: {v}" for k, v in pairs)
    wrapped = textwrap.wrap("Held fixed:  " + fixed_str, width=105)
    loads = [lp for lp in (_offered_load_pct(r) for r in sub) if lp is not None]
    by_cell = defaultdict(list)
    for r in sub:
        by_cell[(r["total_slots"], r["arrival_lambda"])].append(r)
    n_rep = max(map(len, by_cell.values())) if by_cell else 0
    rows_line = (f"Rows: total network capacity T = {', '.join(t_vals)} slots   ·   "
                 f"each row sweeps its own λ range "
                 f"(offered load {min(loads):.0f}–{max(loads):.0f}%)")
    vary_line = (f"Varying: offered load % (λ per tick; left = lighter, right = heavier)"
                 f"   ·   points = {n_rep} repeats, line = median")
    y = 0.96
    for ln in wrapped:
        fig.text(0.5, y, ln, ha="center", fontsize=9, color=MUTED)
        y -= 0.012
    for ln in (rows_line, vary_line):
        fig.text(0.5, y, ln, ha="center", fontsize=9.5, color=MUTED)
        y -= 0.012

    for row_i, t_val in enumerate(t_vals):
        grp = by_t[t_val]
        # group by arrival_lambda within this T, x-ordered by offered load %
        by_lam = defaultdict(list)
        for r in grp:
            by_lam[r["arrival_lambda"]].append(r)
        order = sorted(by_lam, key=lambda k: _offered_load_pct(by_lam[k][0]))
        xs = [_offered_load_pct(by_lam[k][0]) for k in order]
        sim_med = [statistics.median([_f(r["sim_s"]) for r in by_lam[k]]) for k in order]
        log_med = [statistics.median([_f(r["log_bytes"]) for r in by_lam[k]]) / 1048576 for k in order]
        blk_med = []
        for k in order:
            vals = [v for v in (_f(r["blocked_rate"]) for r in by_lam[k]) if v is not None]
            blk_med.append(statistics.median(vals) if vals else 0.0)

        a1, a2, a3 = axes[row_i]

        # scatter repeats at the offered-load % position
        for k in order:
            x = _offered_load_pct(by_lam[k][0])
            a1.scatter([x] * len(by_lam[k]), [_f(r["sim_s"]) for r in by_lam[k]],
                       s=20, color="#378ADD", alpha=0.45, zorder=2)
            a2.scatter([x] * len(by_lam[k]), [_f(r["log_bytes"]) / 1048576 for r in by_lam[k]],
                       s=20, color="#EF9F27", alpha=0.45, zorder=2)
            bvals = [v for v in (_f(r["blocked_rate"]) for r in by_lam[k]) if v is not None]
            a3.scatter([x] * len(bvals), bvals,
                       s=20, color="#34D399", alpha=0.45, zorder=2)
        a1.plot(xs, sim_med, color="#1d4ed8", linewidth=2, marker="o", markersize=5, zorder=3)
        a2.plot(xs, log_med, color="#b45309", linewidth=2, marker="o", markersize=5, zorder=3)
        a3.plot(xs, blk_med, color="#059669", linewidth=2, marker="o", markersize=5, zorder=3)

        # % on the tick row, λ on one fixed lower row (3 s.f. so neighbours at
        # the 15%-load steps never touch); needs the extra row spacing below
        for ax in (a1, a2, a3):
            ax.set_xticks(xs)
            ax.set_xticklabels([f"{_offered_load_pct(by_lam[k][0]):.0f}%"
                                for k in order], fontsize=8)
            for k, x in zip(order, xs):
                ax.annotate(f"λ={float(k):.3g}", xy=(x, 0),
                            xycoords=("data", "axes fraction"),
                            xytext=(0, -17), textcoords="offset points",
                            ha="center", va="top", fontsize=8, color=MUTED,
                            annotation_clip=False)
            ax.set_ylim(bottom=0)

        _style(a1, "", "")
        _style(a2, "", "")
        _style(a3, "", "")
        a1.set_xlabel("")
        a2.set_xlabel("")
        a3.set_xlabel("")
        # after _style, which resets the axis labels
        a1.set_title(f"T = {t_val} total slots", loc="left", fontsize=11,
                     fontweight="bold", color=INK)
        a1.set_ylabel("runtime (s)", fontsize=10, color=INK)
        a2.set_ylabel("log size (MB)", fontsize=10, color=INK)
        a3.set_ylabel("blocked rate (%)", fontsize=10, color=INK)
        a3.set_ylim(0, 100)   # fixed scale: comparable facets, real zeros stay honest

        # annotate medians
        for x, s in zip(xs, sim_med):
            a1.annotate(f"{s:.2f}s", (x, s), textcoords="offset points", xytext=(0, 6),
                        ha="center", fontsize=7.5, color="#1d4ed8")
        for x, l in zip(xs, log_med):
            a2.annotate(f"{l:.1f}MB", (x, l), textcoords="offset points", xytext=(0, 6),
                        ha="center", fontsize=7.5, color="#b45309")
        for x, b in zip(xs, blk_med):
            a3.annotate(f"{b:.1f}%", (x, b), textcoords="offset points", xytext=(0, 6),
                        ha="center", fontsize=7.5, color="#059669")

    # extra row spacing: the λ row sits ~27pt below each panel; tight_layout's
    # default inter-row gap would drop it onto the next facet's title
    fig.subplots_adjust(top=y - 0.08, bottom=0.03, left=0.05, right=0.985,
                        hspace=0.32, wspace=0.18)
    _save(out_dir, "quick_load_curve.png")


def _capacity_90_plot(rows, out_dir):
    """capacity_90: runtime, log size and blocked rate vs total capacity T.

    Four points at constant 90% offered load (each point's λ co-varied as
    111.1/T), linear x-axis: points at their true positions,
    tick labels on alternating tiers because 100/250 land ~3% apart.
    Points = repeats, line = median; the blocked-rate panel shares the fixed
    0-100% scale of the load curves.
    """
    sub = [r for r in rows if r["axis"] == "capacity_90" and r["status"] == "ok" and r["log_mode"] == "file"]
    if not sub:
        return
    groups = defaultdict(list)
    for r in sub:
        groups[r["total_slots"]].append(r)
    order = sorted(groups, key=float)
    xs = [float(k) for k in order]

    def _med(k, col):
        vals = [v for v in (_f(r[col]) for r in groups[k]) if v is not None]
        return statistics.median(vals) if vals else 0.0

    sim_med = [_med(k, "sim_s") for k in order]
    log_med = [_med(k, "log_bytes") / 1048576 for k in order]   # bytes -> MB
    blk_med = [_med(k, "blocked_rate") for k in order]
    pairs = _held_fixed_pairs(sub, "total_slots")
    n_rep = max(len(groups[k]) for k in order) if order else 0

    fig, (a1, a2, a3) = plt.subplots(1, 3, figsize=(16.5, 5.2))
    fig.suptitle("capacity scaling at 90% offered load: runtime, log size & blocked rate vs total capacity",
                 fontsize=13, fontweight="bold", color=INK, y=1.0)
    _context_block(fig, pairs,
                   f"Varying: {_x_label('capacity_90', 'total_slots')}   ·   points = {n_rep} repeats, line = median")

    for x, k in zip(xs, order):
        a1.scatter([x] * len(groups[k]), [_f(r["sim_s"]) for r in groups[k]],
                   s=24, color="#378ADD", alpha=0.45, zorder=2)
        a2.scatter([x] * len(groups[k]), [_f(r["log_bytes"]) / 1048576 for r in groups[k]],
                   s=24, color="#EF9F27", alpha=0.45, zorder=2)
        bvals = [v for v in (_f(r["blocked_rate"]) for r in groups[k]) if v is not None]
        a3.scatter([x] * len(bvals), bvals, s=24, color="#34D399", alpha=0.45, zorder=2)
    a1.plot(xs, sim_med, color="#1d4ed8", linewidth=2, marker="o", markersize=6, zorder=3)
    a2.plot(xs, log_med, color="#b45309", linewidth=2, marker="o", markersize=6, zorder=3)
    a3.plot(xs, blk_med, color="#059669", linewidth=2, marker="o", markersize=6, zorder=3)

    # Label the middle panel only: three full-length x labels collide at the
    # figure bottom; the λ co-variation story stays in the context line above.
    lam_of = {k: float(groups[k][0]["arrival_lambda"]) for k in order}
    for a, ms, fmt, c in ((a1, sim_med, "{:.2f}s", "#1d4ed8"),
                          (a2, log_med, "{:.1f}MB", "#b45309"),
                          (a3, blk_med, "{:.1f}%", "#059669")):
        for i, (x, m) in enumerate(zip(xs, ms)):
            a.annotate(fmt.format(m), (x, m), textcoords="offset points",
                       xytext=(0, 7 if i % 2 == 0 else 21),
                       ha="center", fontsize=8.5, color=c)

    # Linear x: 100/250 land ~3% apart, so the per-point tick labels go on
    # alternating tiers (even upper, odd lower) and the annotations above
    # are staggered vertically.
    _style(a1, "", "runtime (s)")
    _style(a2, _x_label("capacity_90", "total_slots"), "log size (MB)")
    _style(a3, "", "blocked rate (%)")
    # tight_layout ignores the manual tier annotations below the axes, so the
    # xlabel needs explicit padding to clear the lower tier (~50pt deep)
    a2.set_xlabel(a2.get_xlabel(), labelpad=54)
    a1.set_ylim(0, max(sim_med) * 1.18)   # headroom for the raised annotations
    a2.set_ylim(0, max(log_med) * 1.18)
    a3.set_ylim(0, 100)
    for ax in (a1, a2, a3):
        ax.set_xticks(xs)
        ax.set_xticklabels([])
        for i, (x, k) in enumerate(zip(xs, order)):
            ax.annotate(f"{int(x):,}\nλ={lam_of[k]:.4f}s",
                        xy=(x, 0), xycoords=("data", "axes fraction"),
                        xytext=(0, -3 if i % 2 == 0 else -27),
                        textcoords="offset points", ha="center", va="top",
                        fontsize=8.5, color=MUTED, annotation_clip=False)
    fig.tight_layout(rect=[0, 0.01, 1, 0.82])
    _save(out_dir, "quick_capacity_90.png")


# The overlay shows only the informative knee: <=60% load is a flat 0% for
# every capacity and 150% re-bunches the lines (both remain in the CSV and in
# quick_load_curve). WINDOW_SLACK absorbs the ~±0.05% drift that round(λ, 6)
# introduces when load% is recomputed (e.g. T=1000 "120%" is really 120.048%)
# -- a hard cut would silently drop lines at the window edges.
BLOCKING_LOAD_WINDOW = (75.0, 120.0)
BLOCKING_WINDOW_SLACK = 1.0
# Within that window the data tops out near 21%; 25 hugs it instead of dead room.
BLOCKING_YMAX = 25


def _blocking_overlay_plot(rows, out_dir):
    """All capacities on one load axis: blocked rate vs offered load %.

    One line per total capacity T (load_curve rows); capacity_90's independent
    repeats at exactly 90% offered load are marked with stars. This is the view
    where the Erlang-B signature reads instantly: at the same offered load, a
    bigger slot pool blocks less. Only the knee is shown: load levels outside
    BLOCKING_LOAD_WINDOW stay in the CSV but are not drawn.
    """
    lc = [r for r in rows if r["axis"] == "load_curve" and r["status"] == "ok" and r["log_mode"] == "file"]
    windowed = []
    lo, hi = BLOCKING_LOAD_WINDOW
    for r in lc:
        lp = _offered_load_pct(r)
        if lp is not None and lo - BLOCKING_WINDOW_SLACK <= lp <= hi + BLOCKING_WINDOW_SLACK:
            windowed.append(r)
    lc = windowed
    c90 = [r for r in rows if r["axis"] == "capacity_90" and r["status"] == "ok" and r["log_mode"] == "file"]
    if not lc and not c90:
        return

    fig, ax = plt.subplots(figsize=(9.5, 6))
    fig.suptitle("blocking: blocked rate vs offered load, one line per total capacity T",
                 fontsize=13, fontweight="bold", color=INK, y=1.0)
    pairs = _held_fixed_pairs(lc or c90, "arrival_lambda")
    _context_block(fig, pairs,
                   "Varying: offered load % (knee window 75-120% shown; CSV also holds 30-150%)   ·   points = repeats, line = median   ·   ★ = capacity_90 repeats at 90%")

    palette = ("#1d4ed8", "#dc2626", "#059669", "#7c3aed", "#d97706", "#0f766e")

    # load_curve lines: T -> load% -> blocked values
    by_t = defaultdict(lambda: defaultdict(list))
    for r in lc:
        lp = _offered_load_pct(r)
        b = _f(r["blocked_rate"])
        if lp is None or b is None:
            continue
        by_t[r["total_slots"]][round(lp)].append(b)
    t_vals = sorted(by_t, key=float)
    for i, t in enumerate(t_vals):
        color = palette[i % len(palette)]
        loads = sorted(by_t[t])
        med = [statistics.median(by_t[t][lp]) for lp in loads]
        for lp in loads:
            vals = by_t[t][lp]
            ax.scatter([lp] * len(vals), vals, s=20, color=color, alpha=0.45, zorder=2)
        ax.plot(loads, med, color=color, linewidth=2, marker="o", markersize=5,
                label=f"T={t} total slots")
        # annotate only non-trivial medians; the flat-zero region stays clean
        for x, m in zip(loads, med):
            if m >= 0.05:
                ax.annotate(f"{m:.1f}%", (x, m), textcoords="offset points",
                            xytext=(0, 6), ha="center", fontsize=7.5, color=color)

    # capacity_90 stars: independent repeats at exactly 90% offered load
    star_t = defaultdict(list)
    for r in c90:
        b = _f(r["blocked_rate"])
        if b is not None:
            star_t[r["total_slots"]].append(b)
    for t in sorted(star_t, key=float):
        color = palette[t_vals.index(t) % len(palette)] if t in t_vals else "#475569"
        vals = star_t[t]
        ax.scatter([90.0] * len(vals), vals, marker="*", s=140, color=color,
                   edgecolors=INK, linewidths=0.5, zorder=4,
                   label="capacity_90 (90% load)" if t == sorted(star_t, key=float)[0] else None)

    # Knee window only: within 75-120% the medians top out near 21%, so 25
    # hugs the data instead of leaving dead room (see BLOCKING_YMAX above).
    ax.set_ylim(0, BLOCKING_YMAX)
    _style(ax, "offered load %  =  (1/λ) × 100 s mean session ÷ total slots", "blocked rate (%)")
    ax.legend(fontsize=8.5, loc="best", framealpha=0.9)
    fig.tight_layout(rect=[0, 0.01, 1, 0.80])
    _save(out_dir, "quick_blocking.png")


def make_plots(rows, out_dir):
    plots_dir = os.path.join(out_dir, "quick_plots")
    os.makedirs(plots_dir, exist_ok=True)
    for axis, knob in AXIS_KNOB.items():
        if knob is None:
            continue
        if axis == "arrival_sweep":
            _arrival_sweep_plot(rows, plots_dir)
            continue
        if axis == "load_curve":
            _load_curve_plot(rows, plots_dir)
            continue
        if axis == "capacity_90":
            _capacity_90_plot(rows, plots_dir)
            continue
        _ofat_plot(rows, axis, knob, plots_dir)
    _blocking_overlay_plot(rows, plots_dir)


def main():
    p = argparse.ArgumentParser(description="Simple self-describing plots from the CSV.")
    p.add_argument("-d", "--data", required=True, help="scaling_runtime.csv path")
    args = p.parse_args()

    rows = load_rows(args.data)
    out_dir = os.path.dirname(os.path.abspath(args.data))
    print("Plots:", file=sys.stderr)
    make_plots(rows, out_dir)


if __name__ == "__main__":
    main()

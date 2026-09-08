#!/usr/bin/env python3
"""Plot the static scaling probe results (results/probe-static-*.jsonl).

Default (no arguments): the two legacy figures from probe-static-build.jsonl +
probe-static-tables.jsonl:
  results/probe-static-plots-loglog.png   (log-log; growth-rate reading)
  results/probe-static-plots-linear.png   (linear; growth-form reading)

Per-version figures (--version NAME --build ... --tables ...): the same two figures
for one Dijkstra engine, written to probe-static-plots-{mode}--{NAME}.png. Used to
compare the original min-scan engine against the fast engines in
src/dijkstra_fast.py:
  python3 scripts/plot_probe_static.py --version c --build probe-static-build-c.jsonl --tables probe-static-tables-c.jsonl

Comparison figure (--compare): tables cost across both engines in one
figure, probe-static-compare-{mode}.png.

Panels (per-version figures):
  (a) phase time vs N, censor mark where a run was cut off
  (b) peak RSS vs N, machine / guard lines as legend entries
  (c) from_graph memory per router vs N (flat = linear in N)
  (d) mean shortest-path hops vs N

Every measured value is readable two ways: per-point labels on the curves
(all points in log-log; in linear only the sizes that are visually separable,
since small-N points compress into the left edge there), and a complete
data table printed at the bottom of both figures.

Annotation placement rules (learned the hard way): no floating text shares a
corner with the legend; limit/guard explanations live in the legend as dummy
entries; every panel reserves right margin for the green target label.
"""

import os
import sys
import json
import platform
import subprocess

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET_N = 400000  # Internet-scale goal: 400K routers / 80K ASes
XLIM_RIGHT = TARGET_N * 1.45  # room for the green target label

ENGINES = ["old", "python"]
ENGINE_LABELS = {
    "old": "original engine (min-scan Dijkstra, unchanged code)",
    "python": "new Python engine (binary-heap Dijkstra)",
}
ENGINE_COLORS = {"old": "tab:gray", "python": "tab:blue"}


def load(path):
    """Load a JSONL from results/ (default) or any repo-relative/absolute path."""
    for cand in (os.path.join(PROJECT, "results", path),
                 os.path.join(PROJECT, path),
                 path):
        if os.path.exists(cand):
            return [json.loads(l) for l in open(cand)]
    raise FileNotFoundError(
        f"no such file: {path} (looked in results/ and the repo root)")


def phase(r, name, field):
    for p in r.get("phases", []):
        if p["name"] == name:
            return p[field]
    return None


def slope(n, y):
    if len(n) < 3:
        return float("nan")
    return np.polyfit(np.log(n), np.log(y), 1)[0]


def fmt_k(n):
    return f"{n / 1000:g}K" if n >= 1000 else str(n)


def fmt_t(v):
    if v < 0.1:
        return f"{v:.3f}"
    if v < 1:
        return f"{v:.2f}"
    if v < 10:
        return f"{v:.1f}"
    return f"{v:,.0f}"


def fmt_m(v_mb):
    if v_mb < 1024:
        return f"{v_mb:.0f} MB"
    return f"{v_mb / 1024:.1f} GB"


def label_points(a, xs, ys, fmt, dy, color, min_n=None, fontsize=6.5):
    for x, y in zip(xs, ys):
        if min_n is not None and x < min_n:
            continue
        a.annotate(fmt(y), xy=(x, y), xytext=(0, dy),
                   textcoords="offset points", fontsize=fontsize,
                   color=color, ha="center")


def target_line(a, y_frac):
    a.axvline(TARGET_N, ls=":", lw=1.4, color="darkgreen")
    lo, hi = a.get_ylim()
    a.text(TARGET_N * 1.05, lo + (hi - lo) * y_frac,
           "Internet-scale\ntarget:\n400K routers",
           fontsize=8, color="darkgreen", va="center")


def censor_kind(r):
    status = str(r.get("status", ""))
    if status.startswith("censored:memguard"):
        return "memguard"
    if status.startswith("censored"):
        return "timeout"
    return None


def engine_note(version):
    if version is None:
        return None
    if version == "old":
        return ("Dijkstra engine: original min-scan (the code as it was) "
                "-- this is the baseline")
    return (f"Dijkstra engine: {ENGINE_LABELS[version]} -- verified to build "
            f"routing tables identical to the original's")


def data_table_text(build_rows, tables_ok, censors):
    by_n = {r["n_routers"]: r for r in tables_ok}
    cen_n = {r["n_routers"]: censor_kind(r) for r in censors}
    hdr = (f"{'routers':>9} | {'create routers & links':>21} | "
           f"{'forwarding tables':>19} | {'memory: after':>13} | "
           f"{'after tables':>12} | {'per router':>9} | {'mean':>5}")
    hdr2 = (f"{'':>9} | {'time (s)':>21} | {'time (s)':>19} | "
            f"{'creating links':>13} | {'':>12} | {'':>9} | {'hops':>5}")
    sep = "-" * len(hdr)
    lines = [hdr, hdr2, sep]
    for r in build_rows:
        n = r["n_routers"]
        fg_t = phase(r, "from_graph", "s")
        fg_m = phase(r, "from_graph", "rss_mb_hwm")
        b = by_n.get(n)
        if b:
            tb_t = fmt_t(phase(b, "tables", "s"))
            tb_m = fmt_m(phase(b, "tables", "rss_mb_hwm"))
        elif n in cen_n:
            wall = next(r["wall_s"] for r in censors if r["n_routers"] == n)
            tb_t, tb_m = f">{wall / 60:.0f} min", "stopped"
        else:
            tb_t, tb_m = "-", "-"
        hops = (f"{by_n[n]['mean_hops']:.1f}"
                if b and by_n[n].get("mean_hops") else "-")
        lines.append(f"{n:>9,} | {fmt_t(fg_t):>21} | {tb_t:>19} | "
                     f"{fmt_m(fg_m):>13} | {tb_m:>12} | "
                     f"{fg_m * 1024 / n:>6.1f} KB | {hops:>5}")
    lines.append(sep)
    kinds = {censor_kind(r) for r in censors}
    why = []
    if "timeout" in kinds:
        wall = max(r["wall_s"] for r in censors if censor_kind(r) == "timeout")
        why.append(f"'{max(r['wall_s'] for r in censors if censor_kind(r) == 'timeout') / 60:.0f}-minute"
                   f" limit' applies to a run cut off by the time cap")
    if "memguard" in kinds:
        why.append("'memory guard' = run stopped before it could fill the machine")
    note = ("single runs (one seed); '-' = not measured at that size; "
            "'stopped' = run cut off")
    lines.append(note)
    return "\n".join(lines)


def make_figure(build_rows, tables_ok, censors, mode, table_text,
                version=None, out_name=None, note=None, suffix=""):
    loglog = (mode == "loglog")

    Na = np.array([r["n_routers"] for r in build_rows], float)
    Nb = np.array([r["n_routers"] for r in tables_ok], float)
    Ncen = [r for r in censors]

    timeout_wall = max([r["wall_s"] for r in Ncen
                        if censor_kind(r) == "timeout"], default=None)
    memguard = any(censor_kind(r) == "memguard" for r in Ncen)

    fig, ax = plt.subplots(2, 2, figsize=(13, 12.4))
    # linear axes crowd every small-N point into the left edge; there, label
    # only the sizes that are visually separable (all values in the table)
    lab_min = 1 if loglog else 4000

    # ---------------- (a) build time vs network size ----------------
    a = ax[0][0]
    t_gen = np.array([phase(r, "gen", "s") for r in build_rows], float)
    t_fg = np.array([phase(r, "from_graph", "s") for r in build_rows], float)
    t_tb = np.array([phase(r, "tables", "s") for r in tables_ok], float)
    a.plot(Na, t_gen, "o-", color="tab:green", label="generate topology")
    a.plot(Na, t_fg, "o-", color="tab:blue", label="create routers & links")
    lab = "forwarding tables"
    if loglog and len(Nb) >= 3 and not np.isnan(slope(Nb, t_tb)):
        lab += f"  (slope {slope(Nb, t_tb):.1f} = ~{2 ** slope(Nb, t_tb):.0f}x per doubling)"
    a.plot(Nb, t_tb, "o-", color="tab:red", label=lab)
    for r in Ncen:
        a.plot([r["n_routers"]], [r["wall_s"]], "x", color="tab:red",
               mew=2.5, ms=11)
    if Ncen:
        kinds = {censor_kind(r) for r in Ncen}
        if "timeout" in kinds:
            a.plot([], [], "x", color="tab:red", mew=2.5, ms=11,
                   label=f"stopped at {timeout_wall / 60:.0f}-minute limit")
        if "memguard" in kinds:
            a.plot([], [], "x", color="tab:red", mew=2.5, ms=11,
                   label="stopped at the 20 GB memory guard")
    label_points(a, Na, t_fg, fmt_t, -11, "tab:blue", min_n=lab_min)
    label_points(a, Nb, t_tb, fmt_t, 9, "tab:red", min_n=lab_min)
    y_top = 2700.0
    if timeout_wall:
        y_top = max(y_top, timeout_wall * 1.6)
    if loglog:
        a.set_xscale("log"); a.set_yscale("log")
        a.set_ylim(top=y_top)
    if timeout_wall:
        a.axhline(timeout_wall, ls="--", lw=0.8, color="gray")
        if loglog:
            a.text(200, timeout_wall * 0.75,
                   f"{timeout_wall / 60:.0f}-minute limit", fontsize=8,
                   color="gray", va="top")
    if not loglog:
        # headroom so the top point's +9pt label stays inside the axes
        y_lin_top = max(t_tb.max() if len(t_tb) else 0,
                        max((r["wall_s"] for r in Ncen), default=0),
                        t_fg.max() if len(t_fg) else 0) * 1.18
        a.set_ylim(top=y_lin_top)
        max_ok = int(Nb.max()) if len(Nb) else 0
        a.axvspan(0, max(Ncen, key=lambda r: r["wall_s"])["n_routers"]
                  if Ncen else 0, color="tab:red", alpha=0.06)
        if max_ok:
            a.text(max(max_ok, max((r["n_routers"] for r in Ncen), default=0)) * 1.3,
                   0.60 * y_lin_top,
                   f"forwarding tables were only\nmeasured up to {fmt_k(max_ok)} routers",
                   fontsize=8, color="tab:red")
    a.set_xlabel("number of routers in the simulated network")
    a.set_ylabel("time (seconds)")
    a.set_title("(a) Time to build the network — before any traffic is simulated")
    a.legend(fontsize=8, loc="lower right" if loglog else "center right",
             ncol=2, columnspacing=1.0, handlelength=1.6, framealpha=0.95)
    a.grid(True, alpha=0.25)
    a.set_xlim(180 if loglog else 0, XLIM_RIGHT)
    target_line(a, 0.10 if loglog else 0.78)

    # ---------------- (b) peak memory ----------------
    a = ax[0][1]
    m_fg = np.array([phase(r, "from_graph", "rss_mb_hwm") for r in build_rows], float)
    m_tb = np.array([phase(r, "tables", "rss_mb_hwm") for r in tables_ok], float)
    lab = "create routers & links"
    if loglog:
        s = slope(Na, m_fg)
        lab += f"  (slope {s:.1f} = linear)" if not np.isnan(s) else "  (linear)"
    a.plot(Na, m_fg / 1024.0, "o-", color="tab:blue", label=lab)
    lab = "+ compute all forwarding tables"
    if loglog:
        s = slope(Nb, m_tb)
        lab += f"  (slope {s:.1f})" if not np.isnan(s) else ""
    a.plot(Nb, m_tb / 1024.0, "o-", color="tab:red", label=lab)
    mem_censors = [r for r in Ncen if censor_kind(r) == "memguard"]
    time_censors = [r for r in Ncen if censor_kind(r) == "timeout"]
    for r in mem_censors:
        a.plot([r["n_routers"]], [20], "x", color="tab:red", mew=2.5, ms=11)
    for r in time_censors:
        a.plot([r["n_routers"]], [24], "x", color="tab:red", mew=2.5, ms=11)
    if mem_censors:
        a.plot([], [], "x", color="tab:red", mew=2.5, ms=11,
               label="stopped at the 20 GB guard "
                     f"({fmt_k(mem_censors[0]['n_routers'])} routers)")
    if time_censors:
        a.plot([], [], "x", color="tab:red", mew=2.5, ms=11,
               label=f"stopped at the {timeout_wall / 60:.0f}-minute limit "
                     f"(memory not reached)")
    a.plot([], [], ls="--", lw=0.8, color="black",
           label="this machine's total memory (24 GB)")
    a.plot([], [], ls="--", lw=0.8, color="gray",
           label="runs stopped if memory passed 20 GB")
    label_points(a, Na, m_fg / 1024.0, lambda v: fmt_m(v * 1024), -11,
                 "tab:blue", min_n=lab_min)
    label_points(a, Nb, m_tb / 1024.0, lambda v: fmt_m(v * 1024), 9,
                 "tab:red", min_n=lab_min)
    a.axhline(24, ls="--", lw=0.8, color="black")
    a.axhline(20, ls="--", lw=0.8, color="gray")
    if loglog:
        a.set_xscale("log"); a.set_yscale("log")
        a.set_ylim(bottom=0.014, top=36)
    a.set_xlabel("number of routers in the simulated network")
    a.set_ylabel("peak memory use (GB)")
    a.set_title("(b) Peak memory while building the network")
    a.legend(fontsize=8, loc="lower right" if loglog else "center left",
             framealpha=0.95)
    a.grid(True, alpha=0.25)
    a.set_xlim(180 if loglog else 0, XLIM_RIGHT)
    target_line(a, 0.06 if loglog else 0.10)

    # ---------------- (c) memory per router ----------------
    a = ax[1][0]
    per_router = [phase(r, "from_graph", "rss_mb_hwm") * 1024.0 / r["n_routers"]
                  for r in build_rows]
    a.plot(Na, per_router, "o-", color="tab:blue")
    label_points(a, Na, per_router, lambda v: f"{v:.0f}", 9, "tab:blue",
                 min_n=lab_min)
    if loglog:
        a.set_xscale("log")
    a.set_xlabel("number of routers in the simulated network")
    a.set_ylabel("memory per router (KB)")
    a.set_title("(c) Memory per router after creating routers & links\n"
                "a flat line = network cost grows in proportion to size\n"
                "(the early decline is the ~20 MB startup cost spreading "
                "over more routers)")
    a.grid(True, alpha=0.25)
    a.set_xlim(180 if loglog else 0, XLIM_RIGHT)
    target_line(a, 0.55)

    # ---------------- (d) average path length ----------------
    a = ax[1][1]
    hops = [(r["n_routers"], r["mean_hops"]) for r in tables_ok if r.get("mean_hops")]
    if hops:
        a.plot([h[0] for h in hops], [h[1] for h in hops], "o-",
               color="tab:purple",
               label=f"measured (up to {fmt_k(max(h[0] for h in hops))} routers)")
        label_points(a, [h[0] for h in hops], [h[1] for h in hops],
                     lambda v: f"{v:.1f}", 9, "tab:purple")
        a.legend(fontsize=8, loc="lower right")
    a.set_xlabel("number of routers in the simulated network")
    a.set_ylabel("average shortest path (router hops)")
    a.set_title("(d) Average path length of the generated topologies\n"
                "(grows slowly, ~like log of size, as intended)")
    a.grid(True, alpha=0.25)

    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                cwd=PROJECT, capture_output=True, text=True
                                ).stdout.strip()
    except Exception:
        commit = "?"
    title = ("How the simulator's network-building cost grows with network size\n"
             "no traffic simulated yet — only constructing the network and "
             "its forwarding tables")
    if version is not None:
        short = ENGINE_LABELS[version].split(" (")[0]
        if note:
            line2 = note + "   "
        elif version == "old":
            line2 = ("the original min-scan Dijkstra -- the baseline the "
                     "faster engines are measured against   ")
        else:
            line2 = ("identical routing tables to the original engine "
                     "(verified) -- only the speed differs   ")
        title = (f"Network-building cost with the {short}\n"
                 f"{line2}[{'log-log axes' if loglog else 'linear axes'}]")
        fig.suptitle(title, fontsize=12.5)
        fig.tight_layout(rect=(0, 0.235, 1, 0.925))
    else:
        title += f"   [{'log-log axes' if loglog else 'linear axes'}]"
        fig.suptitle(title, fontsize=13)
        fig.tight_layout(rect=(0, 0.235, 1, 0.945))

    fig.text(0.06, 0.222, "Measured values behind the plots (all sizes, both figures):",
             fontsize=9)
    fig.text(0.06, 0.213, table_text, fontsize=6.7, family="monospace",
             va="top", color="black", linespacing=1.32)
    footer = (f"Each point: one fresh process on a MacBook M4 Pro (24 GB), python "
              f"{sys.version.split()[0]}, code commit {commit}. Generated topology: routers grouped "
              f"into ASes of 5 (fully linked inside each AS); ASes connected in a ring plus random "
              f"extra links (~5 AS neighbours each); link weights: intra-AS 1-10, inter-AS 10-50. "
              f"One topology seed, one repeat per point.")
    if version is not None and version != "old":
        footer = ("The forwarding tables and all other behaviour are identical to the "
                  "original engine's (verified entry by entry); only the speed differs. "
                  + footer)
    fig.text(0.01, 0.002, footer, fontsize=7, color="dimgray", wrap=True)

    vtag = f"--{version}" if version else ""
    out = os.path.join(PROJECT, "results", out_name or
                       f"probe-static-plots-{mode}{vtag}{suffix}.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


# --- comparison figure -------------------------------------------

def compare_figure(per_version, mode, note=None, suffix=""):
    """per_version: {engine: (build_rows_rows, tables_ok, censors)}"""
    loglog = (mode == "loglog")
    fig, ax = plt.subplots(1, 2, figsize=(13.5, 6.2))

    # ---------- (a) forwarding-table time ----------
    a = ax[0]
    t_max = 0.0
    for engine in ENGINES:
        build_rows, ok, cens = per_version[engine]
        if not ok and not cens:
            continue
        Nb = np.array([r["n_routers"] for r in ok], float)
        t_tb = np.array([phase(r, "tables", "s") for r in ok], float)
        a.plot(Nb, t_tb, "o-", color=ENGINE_COLORS[engine],
               label=ENGINE_LABELS[engine].replace(" engine", ""))
        t_max = max(t_max, t_tb.max() if len(t_tb) else 0)
        for r in cens:
            a.plot([r["n_routers"]], [r["wall_s"]], "x",
                   color=ENGINE_COLORS[engine], mew=2, ms=9)
    # speed-up callout at the largest size the old engine completed
    old_ok = per_version["old"][1]
    if old_ok:
        n_ref = max(r["n_routers"] for r in old_ok)
        t_old = phase(old_ok[-1], "tables", "s")
        best = None
        for engine in ENGINES[1:]:
            for r in per_version[engine][1]:
                if r["n_routers"] == n_ref:
                    best = (engine, phase(r, "tables", "s"))
        if best:
            a.annotate(f"at {fmt_k(n_ref)} routers: "
                       f"{fmt_t(t_old)}s -> {fmt_t(best[1])}s  "
                       f"({t_old / best[1]:.0f}x faster)",
                       xy=(n_ref, best[1]),
                       xytext=(n_ref * 0.30, best[1] * 0.02),
                       fontsize=9,
                       arrowprops=dict(arrowstyle="->", color="black", lw=0.8))
    if loglog:
        a.set_xscale("log"); a.set_yscale("log")
        a.set_ylim(top=max(2700, t_max * 4))
        if t_max > 1400:
            a.axhline(1500, ls="--", lw=0.8, color="gray")
            a.text(200, 1150, "25-minute limit", fontsize=8, color="gray",
                   va="top")
    a.set_xlabel("number of routers in the simulated network")
    a.set_ylabel("time to compute all forwarding tables (seconds)")
    a.set_title("(a) Forwarding-table build time — the implementations\n"
                "of the same routing algorithm (x = run stopped at a limit)")
    a.legend(fontsize=8, loc="upper left", framealpha=0.95)
    a.grid(True, alpha=0.25)
    a.set_xlim(180, 1.2e4)

    # ---------- (b) forwarding-table memory ----------
    a = ax[1]
    for engine in ENGINES:
        build_rows, ok, cens = per_version[engine]
        if not ok:
            continue
        Nb = np.array([r["n_routers"] for r in ok], float)
        m_tb = np.array([phase(r, "tables", "rss_mb_hwm") for r in ok], float)
        a.plot(Nb, m_tb / 1024.0, "o-", color=ENGINE_COLORS[engine],
               label=ENGINE_LABELS[engine].replace(" engine", ""))
        for r in cens:
            if censor_kind(r) == "memguard":
                a.plot([r["n_routers"]], [20], "x",
                       color=ENGINE_COLORS[engine], mew=2, ms=9)
    a.axhline(24, ls="--", lw=0.8, color="black")
    a.axhline(20, ls="--", lw=0.8, color="gray")
    if loglog:
        a.set_xscale("log"); a.set_yscale("log")
        a.set_ylim(bottom=0.014, top=36)
    a.set_xlabel("number of routers in the simulated network")
    a.set_ylabel("peak memory use (GB)")
    a.set_title("(b) Peak memory while building the network\n"
                "(values wobble a little between runs — the tables "
                "themselves are the cost)")
    a.legend(fontsize=8, loc="lower right", framealpha=0.95)
    a.grid(True, alpha=0.25)
    a.set_xlim(180, 1.2e4)

    # ---------- data table ----------
    lines = ["", "Forwarding tables: time (s) / peak memory, per engine",
             "-" * 100]
    ns = sorted({int(r["n_routers"]) for engine in ENGINES
                 for r in (per_version[engine][1] + per_version[engine][2])})
    hdr = f"{'routers':>9} |"
    for engine in ENGINES:
        hdr += f" {ENGINE_LABELS[engine].split(' (')[0]:>22} |"
    lines.append(hdr)
    for n in ns:
        row = f"{n:>9,} |"
        for engine in ENGINES:
            match = [r for r in per_version[engine][1]
                     if r["n_routers"] == n]
            cens = [r for r in per_version[engine][2]
                    if r["n_routers"] == n]
            if match:
                r = match[0]
                row += (f" {fmt_t(phase(r, 'tables', 's')):>10s} / "
                        f"{fmt_m(phase(r, 'tables', 'rss_mb_hwm')):>10s} |")
            elif cens:
                row += f" {'stopped':>22} |"
            else:
                row += f" {'-':>22} |"
        lines.append(row)
    lines.append("-" * 100)
    sub = ("all implementations build identical tables; simulated traffic behaviour "
           "is unchanged")
    if note:
        sub = note
    fig.suptitle("Forwarding-table cost: the original Dijkstra vs the faster "
                 "implementation of the same algorithm\n"
                 + sub +
                 f"   [{'log-log axes' if loglog else 'linear axes'}]",
                 fontsize=12)
    fig.text(0.05, 0.055, "\n".join(lines), fontsize=7, family="monospace",
             va="bottom", linespacing=1.3)
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                cwd=PROJECT, capture_output=True, text=True
                                ).stdout.strip()
    except Exception:
        commit = "?"
    fig.text(0.05, 0.012,
             f"MacBook M4 Pro (24 GB), one fresh process per point, topology seed "
             f"15112022, code commit {commit}. 'stopped' = cut off at the "
             f"25-minute time cap or the 20 GB memory guard.",
             fontsize=7, color="dimgray")
    fig.tight_layout(rect=(0, 0.24, 1, 0.9))
    out = os.path.join(PROJECT, "results",
                       f"probe-static-compare{suffix}-{mode}.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def split_tables_rows(rows):
    ok = [r for r in rows if r["status"] == "ok"]
    censors = [r for r in rows if str(r["status"]).startswith("censored")]
    return ok, censors


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", choices=ENGINES, default=None,
                    help="engine tag for output filenames and titles")
    ap.add_argument("--build", default="probe-static-build.jsonl")
    ap.add_argument("--tables", default="probe-static-tables.jsonl")
    ap.add_argument("--compare", action="store_true",
                    help="build the comparison figures instead")
    ap.add_argument("--suffix", default="",
                    help="extra output-filename suffix for per-version figures")
    ap.add_argument("--note", default=None,
                    help="extra second title line for per-version figures")
    ap.add_argument("--compare-suffix", default="",
                    help="file suffix for the tables-run inputs and outputs of "
                         "--compare (e.g. '-hoist' reads probe-static-tables-<e>-hoist)")
    args = ap.parse_args()

    if args.compare:
        note = None
        if args.compare_suffix:
            note = ("with the diameter computed once after the build "
                    "(routing state verified identical)")
        files = {engine: (f"probe-static-build-{engine}.jsonl",
                          f"probe-static-tables-{engine}{args.compare_suffix}.jsonl")
                 for engine in ENGINES}
        per_version = {}
        for engine, (fa, fb) in files.items():
            build_rows = [r for r in load(fa) if r["status"] == "ok"]
            ok, cens = split_tables_rows(load(fb))
            per_version[engine] = (build_rows, ok, cens)
        for mode in ("loglog", "linear"):
            print(compare_figure(per_version, mode, note=note,
                                 suffix=args.compare_suffix))
        return

    build_rows = [r for r in load(args.build) if r["status"] == "ok"]
    ok, cens = split_tables_rows(load(args.tables))
    table_text = data_table_text(build_rows, ok, cens)
    for mode in ("loglog", "linear"):
        print(make_figure(build_rows, ok, cens, mode, table_text,
                          version=args.version, note=args.note,
                          suffix=args.suffix))


if __name__ == "__main__":
    main()

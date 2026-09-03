#!/usr/bin/env python3
"""Plot the static scaling probe results (results/probe-l0a.jsonl, probe-l0b.jsonl).

Emits two figures with identical panels, differing only in axis scale:
  results/probe-l0-plots-loglog.png   (log-log; growth-rate reading)
  results/probe-l0-plots-linear.png   (linear; growth-form reading)

Panels:
  (a) phase time vs N, censor mark at the timeout
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


def load(path):
    return [json.loads(l) for l in open(os.path.join(PROJECT, "results", path))]


def phase(r, name, field):
    for p in r.get("phases", []):
        if p["name"] == name:
            return p[field]
    return None


def slope(n, y):
    if len(n) < 3:
        return float("nan")
    return np.polyfit(np.log(n), np.log(y), 1)[0]


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


def data_table_text(l0a, l0b_ok, censors):
    by_n = {r["n_routers"]: r for r in l0b_ok}
    cen_n = {r["n_routers"] for r in censors}
    hdr = (f"{'routers':>9} | {'create routers & links':>21} | "
           f"{'forwarding tables':>19} | {'memory: after':>13} | "
           f"{'after tables':>12} | {'per router':>9} | {'mean':>5}")
    hdr2 = (f"{'':>9} | {'time (s)':>21} | {'time (s)':>19} | "
            f"{'creating links':>13} | {'':>12} | {'':>9} | {'hops':>5}")
    sep = "-" * len(hdr)
    lines = [hdr, hdr2, sep]
    for r in l0a:
        n = r["n_routers"]
        fg_t = phase(r, "from_graph", "s")
        fg_m = phase(r, "from_graph", "rss_mb_hwm")
        b = by_n.get(n)
        if b:
            tb_t = fmt_t(phase(b, "tables", "s"))
            tb_m = fmt_m(phase(b, "tables", "rss_mb_hwm"))
        elif n in cen_n:
            tb_t, tb_m = ">25 min", "stopped"
        else:
            tb_t, tb_m = "-", "-"
        hops = (f"{by_n[n]['mean_hops']:.1f}"
                if b and by_n[n].get("mean_hops") else "-")
        lines.append(f"{n:>9,} | {fmt_t(fg_t):>21} | {tb_t:>19} | "
                     f"{fmt_m(fg_m):>13} | {tb_m:>12} | "
                     f"{fg_m * 1024 / n:>6.1f} KB | {hops:>5}")
    lines.append(sep)
    lines.append("single runs (one seed); '-' = not measured at that size; "
                 "'stopped' = exceeded the 25-minute limit")
    return "\n".join(lines)


def make_figure(l0a, l0b_ok, censors, mode, table_text):
    loglog = (mode == "loglog")

    Na = np.array([r["n_routers"] for r in l0a], float)
    Nb = np.array([r["n_routers"] for r in l0b_ok], float)
    Ncen = [r["n_routers"] for r in censors]

    fig, ax = plt.subplots(2, 2, figsize=(13, 12.4))
    # linear axes crowd every small-N point into the left edge; there, label
    # only the sizes that are visually separable (all values in the table)
    lab_min = 1 if loglog else 4000

    # ---------------- (a) build time vs network size ----------------
    a = ax[0][0]
    t_gen = np.array([phase(r, "gen", "s") for r in l0a], float)
    t_fg = np.array([phase(r, "from_graph", "s") for r in l0a], float)
    t_tb = np.array([phase(r, "tables", "s") for r in l0b_ok], float)
    a.plot(Na, t_gen, "o-", color="tab:green", label="generate topology")
    a.plot(Na, t_fg, "o-", color="tab:blue", label="create routers & links")
    lab = "forwarding tables"
    if loglog:
        lab += "  (slope 2.8 = ~7x per doubling)"
    a.plot(Nb, t_tb, "o-", color="tab:red", label=lab)
    for r in censors:
        a.plot([r["n_routers"]], [r["wall_s"]], "x", color="tab:red",
               mew=2.5, ms=11)
    if censors:
        a.plot([], [], "x", color="tab:red", mew=2.5, ms=11,
               label="stopped at 25-minute limit")
    label_points(a, Na, t_fg, fmt_t, -11, "tab:blue", min_n=lab_min)
    label_points(a, Nb, t_tb, fmt_t, 9, "tab:red", min_n=lab_min)
    if loglog:
        a.set_xscale("log"); a.set_yscale("log")
        a.set_ylim(top=2700)
        a.axhline(1500, ls="--", lw=0.8, color="gray")
        a.text(200, 1150, "25-minute limit", fontsize=8, color="gray",
               va="top")
    else:
        a.axvspan(0, max(Ncen) if Ncen else 0, color="tab:red", alpha=0.06)
        a.text(max(Ncen) * 1.3 if Ncen else 0, 0.68 * 1500,
               "forwarding tables were only\nmeasured up to 4K routers",
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
    m_fg = np.array([phase(r, "from_graph", "rss_mb_hwm") for r in l0a], float)
    m_tb = np.array([phase(r, "tables", "rss_mb_hwm") for r in l0b_ok], float)
    lab = "create routers & links"
    if loglog:
        lab += "  (slope 0.7 = linear)"
    a.plot(Na, m_fg / 1024.0, "o-", color="tab:blue", label=lab)
    lab = "+ compute all forwarding tables"
    if loglog:
        lab += f"  (slope {slope(Nb, m_tb):.1f})"
    a.plot(Nb, m_tb / 1024.0, "o-", color="tab:red", label=lab)
    for r in censors:
        a.plot([r["n_routers"]], [20], "x", color="tab:red", mew=2.5, ms=11)
    a.plot([], [], "x", color="tab:red", mew=2.5, ms=11,
           label="stopped at the 20 GB guard (8K routers)")
    a.plot([], [], ls="--", lw=0.8, color="black",
           label="this machine's total memory (24 GB)")
    a.plot([], [], ls="--", lw=0.8, color="gray",
           label="runs stopped if memory passed 20 GB")
    label_points(a, Na, m_fg, fmt_m, -11, "tab:blue", min_n=lab_min)
    label_points(a, Nb, m_tb, fmt_m, 9, "tab:red", min_n=lab_min)
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
                  for r in l0a]
    a.plot(Na, per_router, "o-", color="tab:blue")
    label_points(a, Na, per_router, lambda v: f"{v:.0f}", 9, "tab:blue",
                 min_n=lab_min)
    if loglog:
        a.set_xscale("log")
    a.set_xlabel("number of routers in the simulated network")
    a.set_ylabel("memory per router (KB)")
    a.set_title("(c) Memory per router after creating routers & links\n"
                "a flat line = network cost grows in proportion to size\n"
                "(KB per router; the early decline is the fixed ~20 MB "
                "startup cost spreading over more routers)")
    a.grid(True, alpha=0.25)
    a.set_xlim(180 if loglog else 0, XLIM_RIGHT)
    target_line(a, 0.55)

    # ---------------- (d) average path length ----------------
    a = ax[1][1]
    hops = [(r["n_routers"], r["mean_hops"]) for r in l0b_ok if r.get("mean_hops")]
    a.plot([h[0] for h in hops], [h[1] for h in hops], "o-",
           color="tab:purple", label="measured (up to 2K routers)")
    label_points(a, [h[0] for h in hops], [h[1] for h in hops],
                 lambda v: f"{v:.1f}", 9, "tab:purple")
    if loglog:
        a.set_xscale("log")
    a.set_xlabel("number of routers in the simulated network")
    a.set_ylabel("average shortest path (router hops)")
    a.set_title("(d) Average path length of the generated topologies\n"
                "(grows slowly, ~like log of size, as intended)")
    a.legend(fontsize=8, loc="lower right")
    a.grid(True, alpha=0.25)

    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                cwd=PROJECT, capture_output=True, text=True
                                ).stdout.strip()
    except Exception:
        commit = "?"
    fig.suptitle("How the simulator's network-building cost grows with network size\n"
                 "no traffic simulated yet — only constructing the network and "
                 f"its forwarding tables   [{'log-log axes' if loglog else 'linear axes'}]",
                 fontsize=13)
    fig.text(0.06, 0.222, "Measured values behind the plots (all sizes, both figures):",
             fontsize=9)
    fig.text(0.06, 0.213, table_text, fontsize=6.7, family="monospace",
             va="top", color="black", linespacing=1.32)
    fig.text(0.01, 0.002,
             f"Each point: one fresh process on a MacBook M4 Pro (24 GB), python "
             f"{sys.version.split()[0]}, code commit {commit}. Generated topology: routers grouped "
             f"into ASes of 5 (fully linked inside each AS); ASes connected in a ring plus random "
             f"extra links (~5 AS neighbours each); link weights: intra-AS 1-10, inter-AS 10-50. "
             f"One topology seed, one repeat per point.",
             fontsize=7, color="dimgray")
    fig.tight_layout(rect=(0, 0.235, 1, 0.945))

    out = os.path.join(PROJECT, "results", f"probe-l0-plots-{mode}.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def main():
    l0a = [r for r in load("probe-l0a.jsonl") if r["status"] == "ok"]
    l0b = load("probe-l0b.jsonl")
    l0b_ok = [r for r in l0b if r["status"] == "ok"]
    censors = [r for r in l0b if r["status"].startswith("censored")]
    table_text = data_table_text(l0a, l0b_ok, censors)
    for mode in ("loglog", "linear"):
        print(make_figure(l0a, l0b_ok, censors, mode, table_text))


if __name__ == "__main__":
    main()

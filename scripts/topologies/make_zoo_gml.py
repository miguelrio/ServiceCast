#!/usr/bin/env python3
"""Topology Zoo GML -> simulator-ready GML: link delays, and randomly placed
servers and clients on low-degree routers.

PLACEHOLDER (5 Nov 2026), to be revised soon. Copied unchanged in its logic
from a scratch script written on 27 Oct 2026 and used for the Topology Zoo
runs since; not yet reviewed. Points the review is to settle:
  - the delay rule, 0.2 ms + 0.007 ms/km (copied from build_caida_topology.py),
    differs from the simulator's own fallback for a link with no delayMs
    (0.009 ms/km, doc/Topology.md); pick one rule for both
  - placement on random routers of degree <= 3 (inherited from
    experiments/main_dfn_2.py): the rule for the paper's zoo runs, or not
  - one script, or a conversion step and a separate placement step (as the
    CAIDA scripts are split), so one converted network serves many
    placements
Until then the output is usable by experiments/main.py: it has a provenance
block and the mark simulatorReady 1.

- external nodes (Internal 0) are dropped, with their links; duplicate
  links are merged
- router links get delayMs = 0.2 + 0.007 * great-circle km; a link with an
  end that has no coordinates gets the median of the computed delays
- servers and clients go on distinct random routers of degree <= MAX_DEGREE
  (after dropping external nodes); if there are too few, servers and
  clients may share a router but never two of a kind
- access links: 1 ms for servers ("hosts"), 10 ms for clients ("access"),
  the agreed defaults
- the output carries a provenance block (provenance.py: the input file and
  its sha256, every option, the script's sha256) and simulatorReady 1

usage: make_zoo_gml.py IN.gml OUT.gml N_SERVERS N_CLIENTS [--max-degree 3] [--seed 15112022]
e.g., from the repository root:
       python3 scripts/topologies/make_zoo_gml.py topologies/gml/Dfn.gml topologies/ready/dfn_s5_c5.gml 5 5
"""

import argparse
import math
import random
import re
import statistics

import provenance


def great_circle_km(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("servers", type=int)
    ap.add_argument("clients", type=int)
    ap.add_argument("--max-degree", type=int, default=3)
    ap.add_argument("--seed", type=int, default=15112022)
    args = ap.parse_args()
    provenance.options(args)

    text = open(provenance.use(args.inp, "topology-zoo"), encoding="utf-8").read()
    nodes = {}
    for block in re.findall(r"node \[(.*?)\n  \]", text, re.S):
        nid = int(re.search(r"^\s*id (\d+)", block, re.M).group(1))
        label = re.search(r'label "([^"]*)"', block).group(1)
        internal = re.search(r"Internal (\d)", block)
        lat = re.search(r"Latitude (-?[\d.]+)", block)
        lon = re.search(r"Longitude (-?[\d.]+)", block)
        nodes[nid] = {"label": label, "internal": internal is None or internal.group(1) == "1",
                      "coord": (float(lat.group(1)), float(lon.group(1))) if lat and lon else None}
    links = set()
    for block in re.findall(r"edge \[(.*?)\n  \]", text, re.S):
        s = int(re.search(r"source (\d+)", block).group(1))
        t = int(re.search(r"target (\d+)", block).group(1))
        if s != t and nodes[s]["internal"] and nodes[t]["internal"]:
            links.add((min(s, t), max(s, t)))

    routers = sorted(i for i, n in nodes.items() if n["internal"])
    delay = {}
    for s, t in links:
        a, b = nodes[s]["coord"], nodes[t]["coord"]
        if a and b:
            delay[(s, t)] = 0.2 + 0.007 * great_circle_km(a, b)
    fallback = statistics.median(delay.values())
    n_fallback = 0
    for link in links:
        if link not in delay:
            delay[link] = fallback
            n_fallback += 1

    degree = {r: 0 for r in routers}
    for s, t in links:
        degree[s] += 1
        degree[t] += 1
    isolated = [r for r in routers if degree[r] == 0]
    low = [r for r in routers if 0 < degree[r] <= args.max_degree]

    rng = random.Random(args.seed)
    if len(low) >= args.servers + args.clients:
        chosen = rng.sample(low, args.servers + args.clients)
        server_at, client_at = chosen[:args.servers], chosen[args.servers:]
        shared = 0
    else:
        server_at = rng.sample(low, args.servers)
        client_at = rng.sample(low, args.clients)
        shared = len(set(server_at) & set(client_at))

    summary = {"routers": len(routers), "externalDropped": len(nodes) - len(routers), "links": len(links),
               "linksWithoutCoordinates": n_fallback, "lowDegreeRouters": len(low),
               "servers": args.servers, "clients": args.clients, "routersWithBoth": shared}

    new_id = {r: k for k, r in enumerate(routers)}
    out = ["graph [\n", "  directed 0\n",
           # 5 Nov 2026: servers and clients are placed, so experiments/main.py may run it
           "  simulatorReady 1\n",
           provenance.block(__file__, provenance.DEFAULT_DATA_DIR, summary=summary)]
    for r in routers:
        n = nodes[r]
        out.append(f"  node [\n    id {new_id[r]}\n    label \"{n['label']}\"\n")
        if n["coord"]:
            out.append(f"    Latitude {n['coord'][0]}\n    Longitude {n['coord'][1]}\n")
        out.append("    Internal 1\n    type \"router\"\n  ]\n")
    for (s, t) in sorted(links):
        out.append(f"  edge [\n    source {new_id[s]}\n    target {new_id[t]}\n    delayMs {delay[(s, t)]:.3f}\n  ]\n")
    nid = len(routers)
    for kind, places, ms, etype in (("server", server_at, 1, "hosts"), ("client", client_at, 10, "access")):
        for k, r in enumerate(places, start=1):
            name = f"srv_{k:03d}" if kind == "server" else f"client_{k:05d}"
            out.append(f"  node [\n    id {nid}\n    label \"{name}\"\n    Internal 0\n    type \"{kind}\"\n  ]\n")
            out.append(f"  edge [\n    source {nid}\n    target {new_id[r]}\n    type \"{etype}\"\n    delayMs {ms}\n  ]\n")
            nid += 1
    out.append("]\n")
    open(args.out, "w", encoding="utf-8").writelines(out)

    d = sorted(delay.values())
    print(f"{args.out}: {len(routers)} routers ({len(nodes) - len(routers)} external dropped), "
          f"{len(links)} links; delay ms min {d[0]:.2f} median {statistics.median(d):.2f} max {d[-1]:.2f}; "
          f"{n_fallback} links without coordinates set to the median")
    print(f"  degree <= {args.max_degree}: {len(low)} routers; isolated after dropping externals: {len(isolated)}; "
          f"{args.servers} servers + {args.clients} clients, {shared} routers with both")


if __name__ == "__main__":
    main()

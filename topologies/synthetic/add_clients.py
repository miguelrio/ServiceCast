#!/usr/bin/env python3
"""
Tag routers of eyeball ASes with the approximate number of clients (users)
behind them.

Users come from APNIC's per-AS estimates of Internet users (users of each AS
in each country, so each AS's share of its country's Internet population is
preserved). They are spread over routers by place_servers.load_users, the
same weighting place_servers.py uses:
  - eyeball AS = at least --min-users APNIC users, and not PeeringDB type
    "Content" (whose "users" are mostly VPN / relay traffic, e.g.
    Cloudflare WARP); other PeeringDB types are ignored because big ISPs are
    often labelled NSP, Enterprise or Network Services;
  - an AS's users in a country go to its routers in that country, in
    proportion to their geolocated IPv4 addresses (ipv4Addrs + 1); if the AS
    has no router in that country, to all its routers.

With --total-clients the counts are scaled to that total (e.g. the number of
clients a simulation can afford), rounded so they sum to it exactly
(largest remainder); routers left with 0 are not tagged. Without it, counts
are the estimated real users.

Output: the input GML unchanged except for one line in each tagged router:
    clientCount <n>
(any previous clientCount lines in routers are replaced). Works on the
output of build_caida_topology.py or place_servers.py. Existing client nodes
are left untouched.

Usage:
  .venv/bin/python3 add_clients.py caida_servers_100.gml -o caida_servers_100_clients.gml
  .venv/bin/python3 add_clients.py caida_real.gml -o caida_clients.gml --total-clients 1000000
"""
import argparse
import collections
import os
import re
import sys
import time

import numpy as np

from build_caida_topology import Gazetteer, log
from place_servers import Topology, load_users

CLIENT_LINE = re.compile(r"^\s*clientCount\s")


def scale(router_users, total):
    """Integer counts summing exactly to total, proportional to users."""
    routers = sorted(router_users)
    w = np.array([router_users[r] for r in routers])
    exact = w / w.sum() * total
    counts = np.floor(exact).astype(np.int64)
    short = int(total - counts.sum())
    counts[np.argsort(-(exact - counts), kind="stable")[:short]] += 1
    return dict(zip(routers, counts.tolist()))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("topology", help="GML from build_caida_topology.py or place_servers.py")
    ap.add_argument("-o", "--output", required=True, help="output GML path (input is never modified)")
    ap.add_argument("--total-clients", type=int,
                    help="scale client counts to this total (default: estimated real users)")
    ap.add_argument("--min-users", type=int, default=1000,
                    help="min APNIC users for an AS to count as eyeball (default 1000)")
    ap.add_argument("--data-dir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
    ap.add_argument("--metro-pop", type=int, default=500_000, help="must match build_caida_topology.py (default 500000)")
    ap.add_argument("--metro-radius-km", type=float, default=50.0, help="must match build_caida_topology.py (default 50)")
    args = ap.parse_args()
    t0 = time.perf_counter()

    if os.path.abspath(args.output) == os.path.abspath(args.topology):
        log("Refusing to overwrite the input file; pass a different -o path.")
        sys.exit(1)

    gaz = Gazetteer(args.data_dir, args.metro_pop, args.metro_radius_km)
    topo = Topology(args.topology, gaz)
    router_users, _ = load_users(args.data_dir, topo, gaz, min_users=args.min_users)

    if args.total_clients is not None:
        counts = scale(router_users, args.total_clients)
    else:
        counts = {r: int(round(u)) for r, u in router_users.items()}
    counts = {r: c for r, c in counts.items() if c > 0}

    # Splice "clientCount n" before each tagged router's closing "]", and
    # drop old clientCount lines inside router blocks.
    insert_at, router_spans = {}, []
    for r in topo.router_metro:
        start, end = topo.node_blocks[r]
        router_spans.append((start, end))
        if r in counts:
            insert_at[end] = f"    clientCount {counts[r]}\n"
    in_router = np.zeros(len(topo.lines) + 1, dtype=np.int8)
    for start, end in router_spans:
        in_router[start] += 1
        in_router[end + 1] -= 1
    in_router = np.cumsum(in_router)[:-1].astype(bool)
    with open(args.output, "w") as f:
        for i, line in enumerate(topo.lines):
            if i in insert_at:
                f.write(insert_at[i])
            if in_router[i] and CLIENT_LINE.match(line):
                continue
            f.write(line)

    total = sum(counts.values())
    ases = {str(topo.nodes[r]["asId"]) for r in counts}
    by_country = collections.Counter()
    for r, c in counts.items():
        by_country[topo.nodes[r].get("Country", "?")] += c
    top = ", ".join(f"{k} {v / total:.1%}" for k, v in by_country.most_common(8))
    biggest = sorted(counts, key=counts.get, reverse=True)[:5]
    log(f"Tagged {len(counts)} routers in {len(ases)} eyeball ASes with {total:,} clients; top countries: {top}")
    log("Largest: " + ", ".join(f"{topo.nodes[r]['label']} ({topo.nodes[r]['city']}) {counts[r]:,}" for r in biggest))
    log(f"Wrote {args.output} in {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main()

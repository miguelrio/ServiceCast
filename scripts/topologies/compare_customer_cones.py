#!/usr/bin/env python3
"""
Compare each AS's recursive customer cone (what build_caida_topology.py and
add_routing_tables_valley_free.py use: every AS reachable by following c2p
links in as-rel) with the cone CAIDA observes on BGP paths (ppdc-ases).

Prints the figures quoted in the "CAIDA topology generator: proposed
changes" doc (proposal E): named ASes, non-tier-1 ASes with a large cone,
non-tier-1 ASes at the 8-PoP cap under each cone, and route-server ASes
(PeeringDB info_type "Route Server") that have customers in as-rel.
With -o, writes one row per AS: asn, recursive, observed.

Data: CAIDA serial-1 files of the same date, from
  https://publicdata.caida.org/datasets/as-relationships/serial-1/
  (YYYYMMDD.as-rel.txt.bz2 and YYYYMMDD.ppdc-ases.txt.bz2).

Usage:
  .venv/bin/python3 compare_customer_cones.py 20260801.as-rel.txt data/caida_ppdc/20260801.ppdc-ases.txt.bz2 \\
      --peeringdb data/peeringdb_2_dump_2026_08_01.json -o cones_20260801.csv
"""
import argparse
import bz2
import collections
import json

import numpy as np

from build_caida_topology import customer_cone_sizes

NAMED = {"1000": "Link American", "264329": "AS1000's customer", "13335": "Cloudflare", "60068": "CDN77",
         "286": "GTT (ex-KPN)", "3356": "Lumen"}


def read_as_rel(path):
    """(provider, customer, 'c2p') links and the clique, as build_caida_topology.read_relationships reads them."""
    links, clique = [], set()
    opener = bz2.open if path.endswith(".bz2") else open
    with opener(path, "rt") as f:
        for line in f:
            if line.startswith("# input clique:"):
                clique = set(line.split(":", 1)[1].split())
            if line.startswith("#"):
                continue
            a, b, rel = line.strip().split("|")[:3]
            if rel == "-1":
                links.append((a, b, "c2p"))
    return links, clique


def read_ppdc(path):
    """Observed cone size per AS, excluding the AS itself."""
    observed = {}
    opener = bz2.open if path.endswith(".bz2") else open
    with opener(path, "rt") as f:
        for line in f:
            if line.startswith("#"):
                continue
            asn, *members = line.split()
            observed[asn] = len(set(members) - {asn})
    return observed


def pop_cap(cone, max_pops=8):
    return min(max_pops, max(1, int(np.ceil(np.log2(cone + 1)))))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("as_rel")
    ap.add_argument("ppdc")
    ap.add_argument("--peeringdb", help="PeeringDB dump, to list route-server ASes with customers")
    ap.add_argument("-o", "--output", help="CSV of asn, recursive, observed")
    args = ap.parse_args()

    links, clique = read_as_rel(args.as_rel)
    recursive = customer_cone_sizes(links)
    observed = read_ppdc(args.ppdc)

    print(f"{'AS':>8}  {'name':<20}{'recursive':>10}{'observed':>10}")
    for asn, name in NAMED.items():
        print(f"{asn:>8}  {name:<20}{recursive.get(asn, 0):>10,}{observed.get(asn, 0):>10,}")

    non_t1 = [a for a in recursive if a not in clique]
    big_r = sum(recursive[a] >= 1000 for a in non_t1)
    big_o = sum(observed.get(a, 0) >= 1000 for a in non_t1)
    print(f"\nnon-tier-1 ASes with a cone of 1,000+: {big_r:,} recursive, {big_o:,} observed")
    cap_r = sum(pop_cap(recursive[a]) == 8 for a in non_t1)
    cap_o = sum(pop_cap(observed.get(a, 0)) == 8 for a in non_t1)
    print(f"non-tier-1 ASes at the 8-PoP cap: {cap_r:,} from the recursive cone, {cap_o:,} from the observed cone")

    if args.peeringdb:
        with open(args.peeringdb) as f:
            nets = json.load(f)["net"]["data"]
        rs = {str(n["asn"]): n["name"] for n in nets if n.get("info_type") == "Route Server"}
        with_customers = sorted((a for a in rs if recursive.get(a, 0) > 0), key=lambda a: -recursive[a])
        print(f"route-server ASes with customers in as-rel: {len(with_customers)}")
        for a in with_customers[:10]:
            print(f"  AS{a} {rs[a][:40]}: recursive {recursive[a]:,}, observed {observed.get(a, 0):,}")

    if args.output:
        with open(args.output, "w") as f:
            f.write("asn,recursive,observed\n")
            for a in sorted(set(recursive) | set(observed), key=int):
                f.write(f"{a},{recursive.get(a, 0)},{observed.get(a, 0)}\n")
        print("wrote", args.output)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Cut a topology built by build_caida_topology.py down to about N ASes, for
quick tests, keeping what matters to ServiceCast: the tier-1s with their
curated footprints, every cloud provider and CDN PoP, the eyeball ASes
with most users, and the provider chains that connect them.

Which ASes are kept:
  1. all tier-1s, every AS in providers.py (CLOUD_AS, CDN_AS), and every AS
     whose observed customer cone contains one of them;
  2. eyeball ASes (APNIC users, as place_servers.load_users counts them)
     in an order drawn by weighted sampling without replacement, weight =
     users. Each comes with every AS whose observed cone contains it, so
     its provider chains up to the tier-1s are kept. Drawing stops at the
     first eyeball AS that would take the total past --ases.
Observed cones are not transitive, so an AS added in this way can still
have none of its own providers in the subset. Such an AS also brings its
providers, each with the ASes whose observed cone contains it, until every
kept AS other than a tier-1 has a provider (2 ASes at 10K, none at 1K, seed 1).
The order depends on --seed alone, so for one seed a smaller subset is
contained in a larger one.

What is kept of them: every router of a kept AS, with its attributes, and
every edge between two kept routers, so PoPs, backbones, inter-AS links
and delays are exactly those of the input. Inter-AS links to dropped ASes
are lost: an AS keeps only the neighbours that are in the subset. Other
nodes (servers, clients) are kept when every router they link to is kept;
the usual order is to cut the base topology, then run place_servers.py
and add_clients.py on the subset. Node ids are renumbered from 0.

The observed cones are restricted to the kept ASes and written to the
sidecar <output>.cones.txt, named in the output's observedCones graph
attribute; each router's observedCone is recomputed the same way. Graph
attributes subsetOf, subsetAses and subsetSeed record how the file was
made. A router's tier is kept from the input.

Usage:
  .venv/bin/python3 subset_caida_topology.py caida_real.gml -o caida_1k.gml --ases 1000
  .venv/bin/python3 subset_caida_topology.py caida_real.gml -o caida_10k.gml --ases 10000
"""
import argparse
import collections
import os
import re
import sys
import time

import numpy as np

from gml_lines import graph_attrs, observed_cones_path, parse_gml, read_cones
from build_caida_topology import Gazetteer, gml_value, log, write_cones
from place_servers import load_users
import provenance
import providers


class Base:
    """The routers of a parsed GML and their metros, as load_users needs them."""

    def __init__(self, nodes, gaz):
        self.nodes = nodes
        rids = [nid for nid, a in nodes.items() if a.get("type") == "router"]
        metros = gaz.snap([nodes[r]["Latitude"] for r in rids], [nodes[r]["Longitude"] for r in rids])
        self.router_metro = dict(zip(rids, metros.tolist()))


def with_providers(ases, known, as_tier, ancestors, as_providers):
    """The ASes to add for ases, given the ASes already kept (known): ases,
    every AS whose observed cone contains one of them, and the providers
    (each with its observed ancestors) of any AS that would otherwise have
    no provider kept."""
    out = set(ases) - known
    for a in list(out):
        out |= ancestors.get(a, set()) - known
    todo = list(out)
    while todo:
        a = todo.pop()
        if as_tier[a] == "tier1" or as_providers.get(a, set()) & (out | known):
            continue
        for p in as_providers.get(a, ()):
            for x in {p} | ancestors.get(p, set()):
                if x not in out and x not in known:
                    out.add(x)
                    todo.append(x)
    return out


def choose_ases(target, seed, as_tier, ancestors, as_providers, as_users):
    """Kept ASes, the eyeball ASes drawn, and the size of the fixed base."""
    keep = with_providers({a for a, t in as_tier.items() if t == "tier1"} | (providers.provider_ases() & set(as_tier)),
                          set(), as_tier, ancestors, as_providers)
    base = len(keep)
    if base > target:
        sys.exit(f"--ases {target} is below the {base} ASes every subset keeps (tier-1s, providers and their providers)")

    eyeballs = sorted(as_users, key=int)
    weights = np.array([as_users[a] for a in eyeballs])
    rng = np.random.default_rng(seed)
    order = np.argsort(-(np.log(rng.random(len(eyeballs))) / weights))  # Efraimidis-Spirakis
    drawn = []
    for i in order:
        new = with_providers({eyeballs[i]}, keep, as_tier, ancestors, as_providers)
        if len(keep) + len(new) > target:
            break
        keep |= new
        drawn.append(eyeballs[i])
    return keep, drawn, base


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("topology", help="GML from build_caida_topology.py (e.g. caida_real.gml)")
    ap.add_argument("-o", "--output", required=True, help="output GML path; the sidecar <output>.cones.txt is written next to it")
    ap.add_argument("--ases", type=int, required=True, help="maximum number of ASes to keep (e.g. 1000 or 10000)")
    ap.add_argument("--seed", type=int, default=1, help="random seed for the eyeball draw (default 1)")
    ap.add_argument("--min-users", type=int, default=1000, help="as in place_servers.py (default 1000)")
    ap.add_argument("--data-dir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
    ap.add_argument("--metro-pop", type=int, default=500_000, help="must match build_caida_topology.py (default 500000)")
    ap.add_argument("--metro-radius-km", type=float, default=50.0, help="must match build_caida_topology.py (default 50)")
    args = ap.parse_args()
    t0 = time.time()

    lines, nodes, edges, _ = parse_gml(provenance.use(args.topology, "topology"))
    attrs = graph_attrs(lines)
    prior = provenance.earlier_steps(lines)
    cones_path = observed_cones_path(args.topology, attrs)
    if not cones_path:
        sys.exit(f"{args.topology} names no observedCones sidecar; rebuild it with build_caida_topology.py")
    cones = read_cones(cones_path)
    ancestors = collections.defaultdict(set)
    for p, members in cones.items():
        for c in members:
            ancestors[c].add(p)

    routers = {nid: a for nid, a in nodes.items() if a.get("type") == "router"}
    as_tier = {str(a["asId"]): a.get("tier", "") for a in routers.values()}
    as_providers = collections.defaultdict(set)
    for e in edges:  # c2p edges are written provider -> customer
        if e.get("type") == "c2p":
            as_providers[str(routers[e["target"]]["asId"])].add(str(routers[e["source"]]["asId"]))
    gaz = Gazetteer(args.data_dir, args.metro_pop, args.metro_radius_km)
    router_users, _ = load_users(args.data_dir, Base(nodes, gaz), gaz, args.min_users)
    as_users = collections.Counter()
    for r, u in router_users.items():
        as_users[str(nodes[r]["asId"])] += u

    keep_as, drawn, base = choose_ases(args.ases, args.seed, as_tier, ancestors, as_providers, as_users)
    kept_users = sum(as_users[a] for a in keep_as)
    log(f"ASes: {len(keep_as)} of {len(as_tier)} ({base} fixed: tier-1s, providers and their providers; "
        f"{len(drawn)} eyeball ASes drawn); users {kept_users / sum(as_users.values()):.1%} of the input's")
    log("Kept ASes by tier: " + ", ".join(f"{t} {n}" for t, n in
                                       collections.Counter(as_tier[a] for a in keep_as).most_common()))

    keep = {nid for nid, a in routers.items() if str(a["asId"]) in keep_as}
    router_nbrs = collections.defaultdict(set)
    for e in edges:
        for u, v in ((e["source"], e["target"]), (e["target"], e["source"])):
            if u not in routers and v in routers:
                router_nbrs[u].add(v)
    others = [nid for nid in nodes if nid not in routers]
    keep |= {nid for nid in others if router_nbrs[nid] and router_nbrs[nid] <= keep}
    kept_edges = [e for e in edges if e["source"] in keep and e["target"] in keep]
    new_id = {nid: i for i, nid in enumerate(sorted(keep))}

    def ext_links(edge_list, node_set):
        n = collections.Counter()
        for e in edge_list:
            if e.get("type") in ("c2p", "p2p"):
                n[e["source"]] += 1
                n[e["target"]] += 1
        return sum(1 for r in node_set if r in routers and n[r] == 0)
    kept_routers = keep & routers.keys()
    log(f"Routers: {len(kept_routers)} of {len(routers)}; other nodes {len(keep) - len(kept_routers)} of {len(others)}; "
        "edges " + ", ".join(f"{t} {n}" for t, n in collections.Counter(e.get("type") for e in kept_edges).most_common()))
    log(f"Routers with no inter-AS link: {ext_links(kept_edges, kept_routers)} "
        f"(the same routers in the input: {ext_links(edges, kept_routers)})")

    cones_name = re.sub(r"\.gml$", "", os.path.basename(args.output)) + ".cones.txt"
    out_dir = os.path.dirname(os.path.abspath(args.output))
    n_entries = write_cones(os.path.join(out_dir, cones_name), cones, sorted(keep_as, key=int))
    attrs["observedCones"] = cones_name
    attrs["subsetOf"] = os.path.basename(args.topology)
    attrs["subsetAses"] = args.ases
    attrs["subsetSeed"] = args.seed
    summary = {"ases": len(keep_as), "routers": len(kept_routers), "otherNodes": len(keep) - len(kept_routers),
               "edges": len(kept_edges), "observedConeEntries": n_entries}
    with open(args.output, "w") as f:
        f.write("graph [\n  directed 0\n")
        for k, v in attrs.items():
            f.write(f"  {k} {gml_value(v)}\n")
        f.write(provenance.block(__file__, args.data_dir, prior, outputs=[os.path.join(out_dir, cones_name)],
                                 summary=summary))
        for nid in sorted(keep):
            a = dict(nodes[nid])
            if nid in routers and "observedCone" in a:
                a["observedCone"] = len(cones.get(str(a["asId"]), set()) & keep_as)
            f.write(f"  node [\n    id {new_id[nid]}\n")
            for k, v in a.items():
                if k != "id":
                    f.write(f"    {k} {gml_value(v)}\n")
            f.write("  ]\n")
        for e in kept_edges:
            f.write(f"  edge [\n    source {new_id[e['source']]}\n    target {new_id[e['target']]}\n")
            for k, v in e.items():
                if k not in ("source", "target"):
                    f.write(f"    {k} {gml_value(v)}\n")
            f.write("  ]\n")
        f.write("]\n")
    log(f"Observed cones: {n_entries} entries in {cones_name}")
    log(f"Wrote {args.output} in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()

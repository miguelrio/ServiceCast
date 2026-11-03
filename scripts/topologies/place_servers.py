#!/usr/bin/env python3
"""
Place N servers at realistic locations on a topology built by
build_caida_topology.py, one output GML per N.

Each N maps to a deployment scenario (override with --scenario):

  N <= 5      centralized  one hyperscaler (AWS): its regions;
  N <= 10     multi-cloud  AWS, Azure and GCP regions;
  N <= 100    cloud-cdn    cloud regions plus the metros of major CDNs;
  N <= 1000   cdn          (CDN AS, metro) sites of major CDNs, from their
                           PeeringDB facilities and IXPs;
  N >  1000   edge         routers of access ISPs: servers inside eyeball
                           networks, next to their users;
  --scenario  mixed        a share --embedded-share of the servers embedded
                           in eyeball ISPs, drawn as in edge, the rest at CDN
                           sites, drawn as in cdn. Each embedded server
                           belongs to a content provider (Google, Meta,
                           Netflix, Akamai) drawn in proportion to its
                           off-net footprint (providers.OFFNET_ISPS) and
                           carries embedded 1; the simulator limits its
                           announcements to the host AS's observed cone.

Site selection follows Internet users, from APNIC's per-AS user estimates
of eyeball ASes, spread over their routers exactly as add_clients.py does
(see load_users).
  - centralized / multi-cloud / cloud-cdn: greedy k-median over candidate
    metros, i.e. each new site is the one that most reduces the user-
    weighted great-circle distance to the nearest server. This is
    deterministic: the seed only breaks ties between providers in a
    metro. --site-selection sample draws the metros instead, weighted by
    their user catchment, as cdn does;
  - cdn: weighted sampling without replacement, weight = users in the site
    metro's catchment (users whose nearest CDN metro it is);
  - edge: weighted sampling without replacement among routers with users,
    weight = the router's users.
Sampling is seeded by --seed alone, so runs are reproducible, and within
one scenario the sites drawn for a smaller N are a subset of those for a
larger N (pass --scenario to keep one scenario across N).

A server is hosted by its operator's router in the site metro. The builder
already has a router at every candidate site (providers.py), so the
network is the same for every N and seed; a missing router is an error.

Output per N: <prefix>_<N>.gml = the topology with any existing servers,
hosts and demand edges removed, plus server nodes (at the metro centre,
attributes operator / hostAs / scenario / embedded) and one hosts edge per server. No demand edges are written. The observedCones graph attribute
is kept, rewritten relative to the output's directory.

Usage:
  .venv/bin/python3 place_servers.py caida_real.gml -o caida_servers --servers 5 10 100 1000 10000
"""
import argparse
import collections
import glob
import os
import re
import sys
import time

import numpy as np
from scipy.spatial import cKDTree

from gml_lines import graph_attrs, observed_cones_path, parse_gml
from build_caida_topology import Gazetteer, gml_value, haversine_km, load_peeringdb, log, to_xyz
import provenance
import providers
from providers import CDN_AS, CLOUD_AS

SCENARIO_LIMITS = [(5, "centralized"), (10, "multi-cloud"), (100, "cloud-cdn"), (1000, "cdn")]
FAR_KM = 20040.0  # more than half the Earth's circumference


def scenario_for(n):
    for limit, name in SCENARIO_LIMITS:
        if n <= limit:
            return name
    return "edge"


def kmedian(gaz, cand_metros, k, users):
    """Greedy k-median: candidate metros (subset of cand_metros) minimizing
    the user-weighted distance to the nearest one. users: metro -> users.
    Returns the chosen metros in pick order."""
    cand = np.array(sorted(set(cand_metros)))
    if k > len(cand):
        raise ValueError(f"only {len(cand)} candidate metros for {k} servers")
    dm = np.array(sorted(users))
    d = haversine_km(gaz.lat[cand][:, None], gaz.lon[cand][:, None], gaz.lat[dm][None, :], gaz.lon[dm][None, :])
    w = np.array([users[m] for m in dm])
    cur = np.full(len(w), FAR_KM)
    taken = np.zeros(len(cand), dtype=bool)
    picks = []
    for _ in range(k):
        gain = np.maximum(cur[None, :] - d, 0) @ w
        gain[taken] = -1
        i = int(np.argmax(gain))
        taken[i] = True
        cur = np.minimum(cur, d[i])
        picks.append(int(cand[i]))
    return picks


def weighted_sample(rng, weights, k):
    """Indices of k items drawn without replacement with probability
    proportional to weight (Efraimidis-Spirakis)."""
    weights = np.asarray(weights, dtype=float)
    ok = np.flatnonzero(weights > 0)
    if k > len(ok):
        raise ValueError(f"only {len(ok)} candidate sites for {k} servers")
    keys = np.log(rng.random(len(ok))) / weights[ok]
    return ok[np.argsort(-keys)[:k]]


class Topology:
    """Base topology (routers, clients, inter-AS adjacency) and the metro
    of each router."""

    def __init__(self, path, gaz):
        self.lines, nodes, edges, self.node_blocks = parse_gml(path)
        self.path = path
        self.graph_attrs = graph_attrs(self.lines)
        self.provenance = provenance.earlier_steps(self.lines)
        provenance.use(path, "topology")
        drop = {nid for nid, a in nodes.items() if a.get("type") == "server"}
        self.nodes = {nid: a for nid, a in nodes.items() if nid not in drop}
        self.edges = [e for e in edges if e.get("type") not in ("hosts", "demand")
                      and e["source"] not in drop and e["target"] not in drop]
        if drop:
            log(f"Removed {len(drop)} existing servers and their hosts/demand edges")
        self.next_id = max(self.nodes) + 1

        self.as_routers = collections.defaultdict(dict)  # asn -> {metro: router id}
        self.metro_routers = collections.defaultdict(list)
        rids = [nid for nid, a in self.nodes.items() if a.get("type") == "router"]
        metros = gaz.snap([self.nodes[r]["Latitude"] for r in rids], [self.nodes[r]["Longitude"] for r in rids])
        self.router_metro = {}
        for r, m in zip(rids, metros.tolist()):
            asn = str(self.nodes[r]["asId"])
            self.as_routers[asn].setdefault(m, r)
            self.metro_routers[m].append(r)
            self.router_metro[r] = m

        log(f"Topology: {len(rids)} routers in {len(self.metro_routers)} metros, "
            f"{len(self.as_routers)} ASes, {len(self.edges)} edges ({path})")


class Scenario:
    """Overlay of a Topology: added servers and hosts edges."""

    def __init__(self, topo, gaz, args):
        self.t, self.gaz, self.args = topo, gaz, args
        self.next_id = topo.next_id
        self.new_nodes = {}
        self.new_edges = []

    def attrs(self, nid):
        return self.new_nodes.get(nid) or self.t.nodes[nid]

    def delay(self, u, v):
        a, b = self.attrs(u), self.attrs(v)
        km = float(haversine_km(a["Latitude"], a["Longitude"], b["Latitude"], b["Longitude"]))
        return round(self.args.link_base_ms + km * self.args.ms_per_km, 3)

    def router(self, asn, metro):
        """Router of asn in metro."""
        rid = self.t.as_routers.get(asn, {}).get(metro)
        if rid is None:
            raise ValueError(f"AS{asn} has no router in {self.gaz.name[metro]}; build the topology "
                             "with the build_caida_topology.py of this version (it builds every site)")
        return rid

    def add_server(self, idx, width, asn, metro, operator, scenario, embedded=0):
        router = self.router(asn, metro)
        sid = self.next_id
        self.next_id += 1
        gaz = self.gaz
        self.new_nodes[sid] = {
            "label": f"srv_{idx:0{width}d}",
            "Country": gaz.country(gaz.cc[metro])[0],
            "Longitude": float(gaz.lon[metro]),
            "Internal": 0,
            "Latitude": float(gaz.lat[metro]),
            "type": "server",
            "operator": operator,
            "hostAs": asn,
            "city": gaz.name[metro],
            "scenario": scenario,
            "embedded": embedded,
        }
        self.new_edges.append((sid, router, "hosts", self.delay(sid, router)))

    def write(self, path, data_dir, summary=None):
        attrs = dict(self.t.graph_attrs)
        cones = observed_cones_path(self.t.path, attrs)
        if cones:
            # Keep naming the same sidecar file, relative to the new GML.
            attrs["observedCones"] = os.path.relpath(cones, os.path.dirname(os.path.abspath(path)))
        with open(path, "w") as f:
            f.write("graph [\n  directed 0\n")
            for k, v in attrs.items():
                f.write(f"  {k} {gml_value(v)}\n")
            f.write(provenance.block(__file__, data_dir, self.t.provenance, summary=summary))
            for nid in list(self.t.nodes) + list(self.new_nodes):
                f.write(f"  node [\n    id {nid}\n")
                for k, v in self.attrs(nid).items():
                    if k != "id":
                        f.write(f"    {k} {gml_value(v)}\n")
                f.write("  ]\n")
            for e in self.t.edges:
                f.write(f'  edge [\n    source {e["source"]}\n    target {e["target"]}\n'
                        f'    type "{e["type"]}"\n    delayMs {e["delayMs"]}\n  ]\n')
            for u, v, t, d in self.new_edges:
                f.write(f'  edge [\n    source {u}\n    target {v}\n    type "{t}"\n    delayMs {d}\n  ]\n')
            f.write("]\n")


NON_EYEBALL_TYPES = ("Content",)  # PeeringDB types whose APNIC "users" are mostly VPN/relay traffic
# The server operators never count as eyeballs, whatever their PeeringDB type:
# AWS is "Enterprise" but its ~3M APNIC users are VPN, proxy and workload traffic.
NON_EYEBALL_ASES = frozenset(CDN_AS) | frozenset(CLOUD_AS.values())


def load_users(data_dir, topo, gaz, min_users=1000, non_eyeball_types=NON_EYEBALL_TYPES):
    """APNIC users of eyeball ASes, spread over their routers.

    Eyeball AS: at least min_users APNIC users in total, not one of the
    server operators (NON_EYEBALL_ASES: CDN_AS and CLOUD_AS), and a
    PeeringDB type not in non_eyeball_types (PeeringDB types are otherwise
    too unreliable: big mobile/broadband ISPs are often labelled NSP,
    Enterprise or Network Services). An AS's users in a country go to its
    routers in that country, in proportion to their geolocated IPv4
    addresses (ipv4Addrs + 1); if it has no router in that country, to all
    its routers in the same way.

    Returns (router id -> users, metro -> users)."""
    path = sorted(glob.glob(os.path.join(data_dir, "apnic_aspop*.html")))
    if not path:
        log(f"Missing apnic_aspop.html in {data_dir}; run fetch_location_data.sh first.")
        sys.exit(1)
    row = re.compile(r'^\s*\[\d+,"AS(\d+)",".*",".*>([A-Z]{2})</a>",(\d+),')
    rows = []
    with open(provenance.use(path[-1], "apnic-aspop"), encoding="latin-1") as f:
        for line in f:
            hit = row.match(line)
            if hit:
                rows.append((hit.group(1), hit.group(2), int(hit.group(3))))
    as_total = collections.Counter()
    for asn, _, users in rows:
        as_total[asn] += users

    as_routers = collections.defaultdict(list)
    as_cc_routers = collections.defaultdict(list)
    for r, m in topo.router_metro.items():
        asn = str(topo.nodes[r]["asId"])
        as_routers[asn].append(r)
        as_cc_routers[(asn, gaz.cc[m])].append(r)

    router_users = collections.Counter()
    metro_users = collections.Counter()
    kept = collections.Counter()
    for asn, cc, users in rows:
        routers = as_cc_routers.get((asn, cc)) or as_routers.get(asn)
        if not routers:
            kind = "not in topology"
        elif as_total[asn] < min_users:
            kind = f"ASes under {min_users} users"
        elif asn in NON_EYEBALL_ASES:
            kind = "server operators"
        elif topo.nodes[routers[0]].get("pdbType", "") in non_eyeball_types:
            kind = "non-eyeball (" + "/".join(non_eyeball_types) + ")"
        else:
            kind = "in country" if (asn, cc) in as_cc_routers else "on routers abroad"
            addrs = np.array([topo.nodes[r].get("ipv4Addrs", 0) + 1 for r in routers], dtype=float)
            for r, share in zip(routers, addrs / addrs.sum()):
                router_users[r] += users * share
                metro_users[topo.router_metro[r]] += users * share
        kept[kind] += users
    total = sum(kept.values())
    log(f"APNIC users: {total / 1e9:.2f}B in {len(as_total)} ASes; "
        + ", ".join(f"{k} {v / total:.1%}" for k, v in kept.most_common())
        + f" ({os.path.basename(path[-1])})")
    return router_users, metro_users


def catchment(gaz, metros, metro_users):
    """Users whose nearest metro (of metros) each metro is."""
    metros = np.array(sorted(set(metros)))
    dm = np.array(sorted(metro_users))
    _, nearest = cKDTree(to_xyz(gaz.lat[metros], gaz.lon[metros])).query(to_xyz(gaz.lat[dm], gaz.lon[dm]))
    w_dm = np.array([metro_users[m] for m in dm])
    return dict(zip(metros.tolist(), np.bincount(nearest, weights=w_dm, minlength=len(metros))))


def choose_sites(scenario, n, topo, gaz, cloud, cdn_sites, rng, router_users, metro_users, selection="kmedian",
                 embedded_share=0.0, seed=1):
    """Return [(asn, metro, operator, embedded)] for n servers."""
    if scenario == "mixed":
        # Separate generators keep each part nested across N.
        n_emb = int(round(embedded_share * n))
        sites = choose_sites("cdn", n - n_emb, topo, gaz, cloud, cdn_sites, np.random.default_rng([seed, 0]),
                             router_users, metro_users) if n > n_emb else []
        emb = choose_sites("edge", n_emb, topo, gaz, cloud, cdn_sites, np.random.default_rng([seed, 1]),
                           router_users, metro_users) if n_emb else []
        names = sorted(providers.OFFNET_ISPS)
        cdf = np.cumsum([providers.OFFNET_ISPS[p] for p in names], dtype=float)
        pick = np.searchsorted(cdf / cdf[-1], np.random.default_rng([seed, 2]).random(n_emb), side="right")
        return sites + [(asn, m, names[k], 1) for (asn, m, _, _), k in zip(emb, pick)]
    if scenario in ("centralized", "multi-cloud", "cloud-cdn"):
        provs = ["AWS"] if scenario == "centralized" else list(CLOUD_AS)
        by_metro = collections.defaultdict(list)
        for prov, m in cloud:
            if prov in provs:
                by_metro[m].append((CLOUD_AS[prov], prov))
        if scenario == "cloud-cdn":
            for asn, m in cdn_sites:
                by_metro[m].append((asn, CDN_AS[asn]))
        if selection == "kmedian":
            metros = kmedian(gaz, by_metro, n, metro_users)
        else:
            cand = sorted(by_metro)
            weight = catchment(gaz, cand, metro_users)
            metros = [cand[i] for i in weighted_sample(rng, [weight[m] for m in cand], n)]
        sites = []
        for m in metros:
            # Prefer a cloud provider at the metro; break ties at random.
            options = sorted(set(by_metro[m]), key=lambda o: (o[1] not in CLOUD_AS, o))
            best = [o for o in options if (o[1] in CLOUD_AS) == (options[0][1] in CLOUD_AS)]
            asn, op = best[rng.integers(len(best))]
            sites.append((asn, m, op, 0))
        return sites

    if scenario == "cdn":
        weight = catchment(gaz, [m for _, m in cdn_sites], metro_users)
        w = [weight[m] for _, m in cdn_sites]
        return [(cdn_sites[i][0], cdn_sites[i][1], CDN_AS[cdn_sites[i][0]], 0) for i in weighted_sample(rng, w, n)]

    # edge: access-ISP routers weighted by the users they serve.
    cands = sorted(router_users)
    sites = []
    for i in weighted_sample(rng, [router_users[r] for r in cands], n):
        asn = str(topo.nodes[cands[i]]["asId"])
        sites.append((asn, topo.router_metro[cands[i]], f"AS{asn}", 0))
    return sites


def coverage_km(gaz, metros, metro_users):
    """User-weighted mean and median distance from users to the nearest
    server metro."""
    metros = np.array(sorted(set(metros)))
    dm = np.array(sorted(metro_users))
    w = np.array([metro_users[m] for m in dm])
    d, _ = cKDTree(to_xyz(gaz.lat[metros], gaz.lon[metros])).query(to_xyz(gaz.lat[dm], gaz.lon[dm]))
    km = 2 * 6371.0 * np.arcsin(np.minimum(1.0, d / 2))
    order = np.argsort(km)
    cum = np.cumsum(w[order])
    return float(np.average(km, weights=w)), float(km[order][np.searchsorted(cum, cum[-1] / 2)])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("topology", help="topology GML from build_caida_topology.py (e.g. caida_real.gml)")
    ap.add_argument("-o", "--output-prefix", required=True, help="writes <prefix>_<N>.gml per N")
    ap.add_argument("--servers", type=int, nargs="+", default=[5, 10, 100, 1000, 10000],
                    help="server counts, one output each (default 5 10 100 1000 10000)")
    ap.add_argument("--scenario", choices=["centralized", "multi-cloud", "cloud-cdn", "cdn", "edge", "mixed"],
                    help="force one scenario for every N instead of choosing it from N")
    ap.add_argument("--embedded-share", type=float, default=0.5,
                    help="mixed scenario: share of servers embedded in eyeball ISPs (default 0.5)")
    ap.add_argument("--seed", type=int, default=1, help="random seed (default 1)")
    ap.add_argument("--site-selection", choices=["kmedian", "sample"], default="kmedian",
                    help="centralized, multi-cloud and cloud-cdn: greedy k-median (default, deterministic) "
                         "or weighted sampling by user catchment (varies with the seed)")
    ap.add_argument("--data-dir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
    ap.add_argument("--metro-pop", type=int, default=500_000, help="must match build_caida_topology.py (default 500000)")
    ap.add_argument("--metro-radius-km", type=float, default=50.0, help="must match build_caida_topology.py (default 50)")
    ap.add_argument("--ms-per-km", type=float, default=0.007, help="propagation delay per km (default 0.007)")
    ap.add_argument("--link-base-ms", type=float, default=0.2, help="fixed delay added to every link (default 0.2)")
    args = ap.parse_args()
    provenance.options(args)
    if not 0.0 <= args.embedded_share <= 1.0:
        ap.error(f"--embedded-share must be between 0 and 1, not {args.embedded_share}")
    t0 = time.perf_counter()

    gaz = Gazetteer(args.data_dir, args.metro_pop, args.metro_radius_km)
    topo = Topology(args.topology, gaz)
    as_fac, as_ix, _, _ = load_peeringdb(args.data_dir, gaz)
    router_users, metro_users = load_users(args.data_dir, topo, gaz)

    cloud = providers.cloud_sites(gaz, topo.as_routers)
    cdn_sites = providers.cdn_sites(as_fac, as_ix, topo.as_routers)
    log(f"Candidates: {len(cloud)} cloud (provider, metro) sites, {len(cdn_sites)} CDN (AS, metro) sites")

    for n in args.servers:
        scenario = args.scenario or scenario_for(n)
        rng = np.random.default_rng(args.seed)
        try:
            sites = choose_sites(scenario, n, topo, gaz, cloud, cdn_sites, rng, router_users, metro_users,
                                 args.site_selection, args.embedded_share, args.seed)
        except ValueError as exc:
            log(f"N={n} ({scenario}): {exc}; pick a larger-scale scenario with --scenario")
            sys.exit(1)
        sc = Scenario(topo, gaz, args)
        width = len(str(n))
        try:
            for i, (asn, m, op, emb) in enumerate(sites, 1):
                sc.add_server(i, width, asn, m, op, scenario, emb)
        except ValueError as exc:
            log(f"N={n} ({scenario}): {exc}")
            sys.exit(1)
        path = f"{args.output_prefix}_{n}.gml"
        provenance.use(providers.__file__, "providers")
        sc.write(path, args.data_dir, {"servers": n, "embeddedServers": sum(1 for s in sites if s[3]),
                                       "hostAses": len({s[0] for s in sites}), "metros": len({s[1] for s in sites})})
        mean_km, median_km = coverage_km(gaz, [s[1] for s in sites], metro_users)
        ops = collections.Counter("access ISPs" if op.startswith("AS") else op + (" (embedded)" if emb else "")
                                  for _, _, op, emb in sites)
        n_emb_hosts = len({s[0] for s in sites if s[3]})
        log(f"N={n} ({scenario}): {len({s[1] for s in sites})} metros, {len({s[0] for s in sites})} host ASes"
            + (f" ({n_emb_hosts} hosting embedded servers)" if n_emb_hosts else "") + ", "
            f"user->nearest server {mean_km:.0f} km mean, "
            f"{median_km:.0f} km median; operators {dict(ops.most_common(6))} -> {path}")
    log(f"Done in {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main()

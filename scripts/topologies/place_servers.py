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
                           networks, next to their users.

Site selection follows Internet users, from APNIC's per-AS user estimates
of eyeball ASes, spread over their routers exactly as add_clients.py does
(see load_users).
  - centralized / multi-cloud / cloud-cdn: greedy k-median over candidate
    metros, i.e. each new site is the one that most reduces the user-
    weighted great-circle distance to the nearest server;
  - cdn: weighted sampling without replacement, weight = users in the site
    metro's catchment (users whose nearest CDN metro it is);
  - edge: weighted sampling without replacement among routers with users,
    weight = the router's users.
Sampling is seeded (--seed), so runs are reproducible.

A server is hosted by a router of its operator's AS in the site metro. If
that AS has no router there (the topology caps PoPs per AS), one is added:
full-mesh internal links to the AS's other routers, and links to each
neighbour AS present in that metro, following the builder's rule (at most
--max-links-per-pair links per AS pair, original c2p/p2p direction kept).

Output per N: <prefix>_<N>.gml = the topology with any existing servers,
hosts and demand edges removed, plus the new routers, server nodes (at the
metro centre, attributes operator / hostAs / scenario) and one hosts edge
per server. No demand edges are written.

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

# add_routing_tables_valley_free.py sits next to this script, or one level up
# (scripts/ in the ServiceCast repository).
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from add_routing_tables_valley_free import parse_gml
from build_caida_topology import Gazetteer, gml_value, haversine_km, load_peeringdb, log, to_xyz

CLOUD_AS = {"AWS": "16509", "Azure": "8075", "GCP": "15169"}

# Public cloud regions: (provider, region, lat, lon) of the region's
# metro. Snapped to the gazetteer's metros at run time.
CLOUD_REGIONS = [
    # AWS
    ("AWS", "us-east-1", 39.04, -77.49), ("AWS", "us-east-2", 39.96, -83.00),
    ("AWS", "us-west-1", 37.34, -121.89), ("AWS", "us-west-2", 45.52, -122.68),
    ("AWS", "ca-central-1", 45.50, -73.57), ("AWS", "ca-west-1", 51.05, -114.07),
    ("AWS", "mx-central-1", 20.59, -100.39), ("AWS", "sa-east-1", -23.55, -46.63),
    ("AWS", "eu-west-1", 53.35, -6.26), ("AWS", "eu-west-2", 51.51, -0.13),
    ("AWS", "eu-west-3", 48.86, 2.35), ("AWS", "eu-central-1", 50.11, 8.68),
    ("AWS", "eu-central-2", 47.38, 8.54), ("AWS", "eu-north-1", 59.33, 18.07),
    ("AWS", "eu-south-1", 45.46, 9.19), ("AWS", "eu-south-2", 41.65, -0.88),
    ("AWS", "il-central-1", 32.09, 34.78), ("AWS", "me-south-1", 26.23, 50.59),
    ("AWS", "me-central-1", 25.20, 55.27), ("AWS", "af-south-1", -33.92, 18.42),
    ("AWS", "ap-east-1", 22.32, 114.17), ("AWS", "ap-east-2", 25.03, 121.57),
    ("AWS", "ap-south-1", 19.08, 72.88), ("AWS", "ap-south-2", 17.39, 78.49),
    ("AWS", "ap-southeast-1", 1.35, 103.82), ("AWS", "ap-southeast-2", -33.87, 151.21),
    ("AWS", "ap-southeast-3", -6.21, 106.85), ("AWS", "ap-southeast-4", -37.81, 144.96),
    ("AWS", "ap-southeast-5", 3.14, 101.69), ("AWS", "ap-southeast-6", -36.85, 174.76),
    ("AWS", "ap-southeast-7", 13.76, 100.50), ("AWS", "ap-northeast-1", 35.68, 139.69),
    ("AWS", "ap-northeast-2", 37.57, 126.98), ("AWS", "ap-northeast-3", 34.69, 135.50),
    ("AWS", "cn-north-1", 39.90, 116.41), ("AWS", "cn-northwest-1", 38.49, 106.23),
    # Azure
    ("Azure", "eastus", 36.68, -78.39), ("Azure", "eastus2", 36.68, -78.39),
    ("Azure", "centralus", 41.59, -93.62), ("Azure", "northcentralus", 41.88, -87.63),
    ("Azure", "southcentralus", 29.42, -98.49), ("Azure", "westus", 37.77, -122.42),
    ("Azure", "westus2", 47.23, -119.85), ("Azure", "westus3", 33.45, -112.07),
    ("Azure", "westcentralus", 41.14, -104.82), ("Azure", "canadacentral", 43.65, -79.38),
    ("Azure", "canadaeast", 46.81, -71.21), ("Azure", "brazilsouth", -23.55, -46.63),
    ("Azure", "mexicocentral", 20.59, -100.39), ("Azure", "chilecentral", -33.45, -70.67),
    ("Azure", "northeurope", 53.35, -6.26), ("Azure", "westeurope", 52.37, 4.90),
    ("Azure", "uksouth", 51.51, -0.13), ("Azure", "ukwest", 51.48, -3.18),
    ("Azure", "francecentral", 48.86, 2.35), ("Azure", "germanywestcentral", 50.11, 8.68),
    ("Azure", "switzerlandnorth", 47.38, 8.54), ("Azure", "norwayeast", 59.91, 10.75),
    ("Azure", "swedencentral", 60.67, 17.14), ("Azure", "polandcentral", 52.23, 21.01),
    ("Azure", "italynorth", 45.46, 9.19), ("Azure", "spaincentral", 40.42, -3.70),
    ("Azure", "austriaeast", 48.21, 16.37), ("Azure", "belgiumcentral", 50.85, 4.35),
    ("Azure", "israelcentral", 32.09, 34.78), ("Azure", "qatarcentral", 25.29, 51.53),
    ("Azure", "uaenorth", 25.20, 55.27), ("Azure", "southafricanorth", -26.20, 28.05),
    ("Azure", "centralindia", 18.52, 73.86), ("Azure", "southindia", 13.08, 80.27),
    ("Azure", "westindia", 19.08, 72.88), ("Azure", "southeastasia", 1.35, 103.82),
    ("Azure", "eastasia", 22.32, 114.17), ("Azure", "japaneast", 35.68, 139.69),
    ("Azure", "japanwest", 34.69, 135.50), ("Azure", "koreacentral", 37.57, 126.98),
    ("Azure", "koreasouth", 35.18, 129.08), ("Azure", "australiaeast", -33.87, 151.21),
    ("Azure", "australiasoutheast", -37.81, 144.96), ("Azure", "australiacentral", -35.28, 149.13),
    ("Azure", "indonesiacentral", -6.21, 106.85), ("Azure", "malaysiawest", 3.14, 101.69),
    ("Azure", "newzealandnorth", -36.85, 174.76), ("Azure", "taiwannorth", 25.03, 121.57),
    # GCP
    ("GCP", "us-east4", 39.04, -77.49), ("GCP", "us-east1", 33.20, -80.01),
    ("GCP", "us-east5", 39.96, -83.00), ("GCP", "us-central1", 41.26, -95.86),
    ("GCP", "us-south1", 32.78, -96.80), ("GCP", "us-west1", 45.60, -121.18),
    ("GCP", "us-west2", 34.05, -118.24), ("GCP", "us-west3", 40.76, -111.89),
    ("GCP", "us-west4", 36.17, -115.14), ("GCP", "northamerica-northeast1", 45.50, -73.57),
    ("GCP", "northamerica-northeast2", 43.65, -79.38), ("GCP", "northamerica-south1", 20.59, -100.39),
    ("GCP", "southamerica-east1", -23.55, -46.63), ("GCP", "southamerica-west1", -33.45, -70.67),
    ("GCP", "europe-west1", 50.45, 3.82), ("GCP", "europe-west2", 51.51, -0.13),
    ("GCP", "europe-west3", 50.11, 8.68), ("GCP", "europe-west4", 53.44, 6.83),
    ("GCP", "europe-west6", 47.38, 8.54), ("GCP", "europe-west8", 45.46, 9.19),
    ("GCP", "europe-west9", 48.86, 2.35), ("GCP", "europe-west10", 52.52, 13.40),
    ("GCP", "europe-west12", 45.07, 7.69), ("GCP", "europe-north1", 60.57, 27.20),
    ("GCP", "europe-north2", 59.33, 18.07), ("GCP", "europe-central2", 52.23, 21.01),
    ("GCP", "europe-southwest1", 40.42, -3.70), ("GCP", "me-west1", 32.09, 34.78),
    ("GCP", "me-central1", 25.29, 51.53), ("GCP", "me-central2", 26.43, 50.10),
    ("GCP", "africa-south1", -26.20, 28.05), ("GCP", "asia-south1", 19.08, 72.88),
    ("GCP", "asia-south2", 28.61, 77.21), ("GCP", "asia-southeast1", 1.35, 103.82),
    ("GCP", "asia-southeast2", -6.21, 106.85), ("GCP", "asia-east1", 24.08, 120.54),
    ("GCP", "asia-east2", 22.32, 114.17), ("GCP", "asia-northeast1", 35.68, 139.69),
    ("GCP", "asia-northeast2", 34.69, 135.50), ("GCP", "asia-northeast3", 37.57, 126.98),
    ("GCP", "australia-southeast1", -33.87, 151.21), ("GCP", "australia-southeast2", -37.81, 144.96),
]

# Major CDN / content ASes whose PeeringDB footprint defines CDN sites.
CDN_AS = {
    "13335": "Cloudflare", "20940": "Akamai", "54113": "Fastly", "16509": "AWS",
    "15169": "Google", "8075": "Microsoft", "22822": "Edgio", "60068": "CDN77",
    "199524": "Gcore", "32934": "Meta", "2906": "Netflix", "714": "Apple",
}
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

        # AS adjacency with the original edge type/direction, and link counts.
        self.neighbours = collections.defaultdict(list)  # asn -> [(other, type, asn_is_source)]
        self.pair_links = collections.Counter()
        for e in self.edges:
            if e.get("type") not in ("c2p", "p2p"):
                continue
            a, b = str(self.nodes[e["source"]]["asId"]), str(self.nodes[e["target"]]["asId"])
            key = frozenset((a, b))
            if key not in self.pair_links:
                self.neighbours[a].append((b, e["type"], True))
                self.neighbours[b].append((a, e["type"], False))
            self.pair_links[key] += 1
        log(f"Topology: {len(rids)} routers in {len(self.metro_routers)} metros, "
            f"{len(self.as_routers)} ASes, {len(self.edges)} edges ({path})")


class Scenario:
    """Copy-on-write overlay of a Topology: added routers, servers, edges."""

    def __init__(self, topo, gaz, args):
        self.t, self.gaz, self.args = topo, gaz, args
        self.next_id = topo.next_id
        self.new_nodes = {}
        self.changed = {}  # base node id -> replacement attrs
        self.new_edges = []
        self.as_routers = {}  # asn -> {metro: router id}, copied when changed
        self.pair_links = collections.Counter()  # extra links per AS pair
        self.added_routers = 0

    def attrs(self, nid):
        return self.new_nodes.get(nid) or self.changed.get(nid) or self.t.nodes[nid]

    def routers_of(self, asn):
        return self.as_routers.get(asn, self.t.as_routers.get(asn, {}))

    def delay(self, u, v):
        a, b = self.attrs(u), self.attrs(v)
        km = float(haversine_km(a["Latitude"], a["Longitude"], b["Latitude"], b["Longitude"]))
        return round(self.args.link_base_ms + km * self.args.ms_per_km, 3)

    def ensure_router(self, asn, metro):
        """Router of asn in metro, adding a PoP if the AS has none there."""
        existing = self.routers_of(asn)
        if metro in existing:
            return existing[metro]
        if not existing:
            raise ValueError(f"AS{asn} is not in the topology")
        template = self.attrs(next(iter(existing.values())))
        if len(existing) == 1:
            # The AS stops being single-PoP: its internal delay is now modelled by links.
            only = next(iter(existing.values()))
            self.changed[only] = {**self.attrs(only), "internalDelayMs": 0}
        rid = self.next_id
        self.next_id += 1
        gaz = self.gaz
        cname, continent = gaz.country(gaz.cc[metro])
        self.new_nodes[rid] = {
            "label": f"{asn}-p{len(existing)}",
            "Country": cname,
            "Longitude": float(gaz.lon[metro]),
            "Internal": 1,
            "Latitude": float(gaz.lat[metro]),
            "type": "router",
            "asId": asn,
            "tier": template.get("tier", "stub"),
            "city": gaz.name[metro],
            "continent": continent,
            "internalDelayMs": 0,
            "locSource": "server-site",
            "ipv4Addrs": 0,
            "pdbType": template.get("pdbType", ""),
        }
        for other in existing.values():
            self.new_edges.append((other, rid, "internal", self.delay(other, rid)))
        for nb, etype, asn_is_source in self.t.neighbours.get(asn, ()):
            nb_router = self.routers_of(nb).get(metro)
            key = frozenset((asn, nb))
            if nb_router is None or self.t.pair_links[key] + self.pair_links[key] >= self.args.max_links_per_pair:
                continue
            u, v = (rid, nb_router) if asn_is_source else (nb_router, rid)
            self.new_edges.append((u, v, etype, self.delay(u, v)))
            self.pair_links[key] += 1
        self.as_routers[asn] = {**existing, metro: rid}
        self.added_routers += 1
        return rid

    def add_server(self, idx, width, asn, metro, operator, scenario):
        router = self.ensure_router(asn, metro)
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
        }
        self.new_edges.append((sid, router, "hosts", self.delay(sid, router)))

    def write(self, path):
        with open(path, "w") as f:
            f.write("graph [\n  directed 0\n")
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


def load_users(data_dir, topo, gaz, min_users=1000, non_eyeball_types=NON_EYEBALL_TYPES):
    """APNIC users of eyeball ASes, spread over their routers.

    Eyeball AS: at least min_users APNIC users in total, and a PeeringDB
    type not in non_eyeball_types (PeeringDB types are otherwise too
    unreliable: big mobile/broadband ISPs are often labelled NSP,
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
    with open(path[-1], encoding="latin-1") as f:
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


def choose_sites(scenario, n, topo, gaz, cloud, cdn_sites, rng, router_users, metro_users):
    """Return [(asn, metro, operator)] for n servers."""
    if scenario in ("centralized", "multi-cloud", "cloud-cdn"):
        providers = ["AWS"] if scenario == "centralized" else list(CLOUD_AS)
        by_metro = collections.defaultdict(list)
        for prov, m in cloud:
            if prov in providers:
                by_metro[m].append((CLOUD_AS[prov], prov))
        if scenario == "cloud-cdn":
            for asn, m in cdn_sites:
                by_metro[m].append((asn, CDN_AS[asn]))
        sites = []
        for m in kmedian(gaz, by_metro, n, metro_users):
            # Prefer a cloud provider at the metro; break ties at random.
            options = sorted(set(by_metro[m]), key=lambda o: (o[1] not in CLOUD_AS, o))
            best = [o for o in options if (o[1] in CLOUD_AS) == (options[0][1] in CLOUD_AS)]
            asn, op = best[rng.integers(len(best))]
            sites.append((asn, m, op))
        return sites

    if scenario == "cdn":
        metros = np.array(sorted({m for _, m in cdn_sites}))
        dm = np.array(sorted(metro_users))
        _, nearest = cKDTree(to_xyz(gaz.lat[metros], gaz.lon[metros])).query(to_xyz(gaz.lat[dm], gaz.lon[dm]))
        w_dm = np.array([metro_users[m] for m in dm])
        catchment = dict(zip(metros.tolist(), np.bincount(nearest, weights=w_dm, minlength=len(metros))))
        w = [catchment[m] for _, m in cdn_sites]
        return [(cdn_sites[i][0], cdn_sites[i][1], CDN_AS[cdn_sites[i][0]]) for i in weighted_sample(rng, w, n)]

    # edge: access-ISP routers weighted by the users they serve.
    cands = sorted(router_users)
    sites = []
    for i in weighted_sample(rng, [router_users[r] for r in cands], n):
        asn = str(topo.nodes[cands[i]]["asId"])
        sites.append((asn, topo.router_metro[cands[i]], f"AS{asn}"))
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
    ap.add_argument("--scenario", choices=["centralized", "multi-cloud", "cloud-cdn", "cdn", "edge"],
                    help="force one scenario for every N instead of choosing it from N")
    ap.add_argument("--seed", type=int, default=1, help="random seed (default 1)")
    ap.add_argument("--data-dir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
    ap.add_argument("--metro-pop", type=int, default=500_000, help="must match build_caida_topology.py (default 500000)")
    ap.add_argument("--metro-radius-km", type=float, default=50.0, help="must match build_caida_topology.py (default 50)")
    ap.add_argument("--max-links-per-pair", type=int, default=4,
                    help="max links between two ASes when adding a PoP (default 4, as in the builder)")
    ap.add_argument("--ms-per-km", type=float, default=0.007, help="propagation delay per km (default 0.007)")
    ap.add_argument("--link-base-ms", type=float, default=0.2, help="fixed delay added to every link (default 0.2)")
    args = ap.parse_args()
    t0 = time.perf_counter()

    gaz = Gazetteer(args.data_dir, args.metro_pop, args.metro_radius_km)
    topo = Topology(args.topology, gaz)
    as_fac, as_ix, _ = load_peeringdb(args.data_dir, gaz)
    router_users, metro_users = load_users(args.data_dir, topo, gaz)

    cloud_metros = gaz.snap([r[2] for r in CLOUD_REGIONS], [r[3] for r in CLOUD_REGIONS]).tolist()
    cloud = sorted({(r[0], m) for r, m in zip(CLOUD_REGIONS, cloud_metros) if CLOUD_AS[r[0]] in topo.as_routers})
    cdn_sites = sorted({(asn, m) for asn in CDN_AS if asn in topo.as_routers
                        for m in set(as_fac.get(asn, {})) | as_ix.get(asn, set())})
    log(f"Candidates: {len(cloud)} cloud (provider, metro) sites, {len(cdn_sites)} CDN (AS, metro) sites")

    for n in args.servers:
        scenario = args.scenario or scenario_for(n)
        rng = np.random.default_rng([args.seed, n])
        try:
            sites = choose_sites(scenario, n, topo, gaz, cloud, cdn_sites, rng, router_users, metro_users)
        except ValueError as exc:
            log(f"N={n} ({scenario}): {exc}; pick a larger-scale scenario with --scenario")
            sys.exit(1)
        sc = Scenario(topo, gaz, args)
        width = len(str(n))
        for i, (asn, m, op) in enumerate(sites, 1):
            sc.add_server(i, width, asn, m, op, scenario)
        path = f"{args.output_prefix}_{n}.gml"
        sc.write(path)
        mean_km, median_km = coverage_km(gaz, [m for _, m, _ in sites], metro_users)
        ops = collections.Counter(op if not op.startswith("AS") else "access ISPs" for _, _, op in sites)
        log(f"N={n} ({scenario}): {len({m for _, m, _ in sites})} metros, {len({a for a, _, _ in sites})} host ASes, "
            f"{sc.added_routers} routers added; user->nearest server {mean_km:.0f} km mean, "
            f"{median_km:.0f} km median; operators {dict(ops.most_common(6))} -> {path}")
    log(f"Done in {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main()

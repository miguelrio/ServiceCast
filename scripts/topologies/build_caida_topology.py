#!/usr/bin/env python3
"""
Build a router-level GML topology, with routers at realistic locations,
from a CAIDA AS-relationship file (e.g. 20260801.as-rel.txt).

The as-rel file gives the ASes and their relationships: `a|b|-1` (a is b's
provider) becomes a c2p edge written provider -> customer, `a|b|0` a p2p
edge. Tiers: the "# input clique" ASes are tier1, ASes with customers are
transit, the rest are stubs. IXP route servers (PeeringDB type "Route
Server") are dropped first: they take no part in forwarding, but CAIDA
lists some of them as providers. ASes outside the clique's customer cones
(no provider in the file, or only providers with no provider path to the
clique) are then dropped: under valley-free routing they could only reach
their peers' customer cones, so some routes would be missing. Servers and
clients are added afterwards by place_servers.py and add_clients.py.

Observed customer cones: following every c2p link of the as-rel file
gives some ASes customer cones far larger than CAIDA sees on BGP paths
(Cloudflare 22,319 ASes against 1,012 observed), and under Gao-Rexford one
such link pulls routes down chains nobody uses. The builder therefore also
reads CAIDA's ppdc-ases file of the same date (the cone each AS is observed
to carry routes for) and writes it, restricted to the topology's ASes, to a
sidecar file next to the GML, <output>.cones.txt, named by the graph
attribute observedCones. Routing (add_routing_tables_valley_free.py and the
simulator) lets AS p use a customer route to AS d only if d is in p's
observed cone; tier-1s are unrestricted. Each router carries its AS's
observed cone size (observedCone).

Each AS is given one router per point of presence (PoP, "model B"), placed
in metros where the AS actually is, using, in order of trust:

  1. PeeringDB (CAIDA's daily dump): metros of the facilities (netfac) and
     IXPs (netixlan) the AS declares itself present at;
  2. IP geolocation: the AS's announced IPv4 prefixes (RouteViews prefix2as)
     located with DB-IP City Lite, weighted by address count;
  3. RIR delegation country: the AS is put in its country's largest city;
  4. otherwise the main PoP of a neighbour AS (providers first).

All locations are snapped to metros: GeoNames cities with population >=
--metro-pop within --metro-radius-km, else the nearest GeoNames city of
15k+ inhabitants. Routers sit at the metro centre, so every AS present in
e.g. Frankfurt shares the same coordinates.

PoP selection per AS: a metro scores
    geo_share + W_FAC*fac_share + W_IX*ix_share
(shares of the AS's geolocated addresses, PeeringDB facilities and IXPs in
that metro) and is eligible if it has PeeringDB presence, holds at least
--min-geo-share (--min-geo-share-transit for non-stubs) of the AS's
geolocated addresses, or is the AS's top geolocated metro. PoPs are
picked greedily by score (metros within --diversity-km of an already-picked
PoP are down-weighted). Stubs get at most --max-pops-stub PoPs. Transit
ASes get at most ceil(log2(cone + 1)) PoPs, cone = number of ASes in their
observed customer cone (1 PoP for a cone of 0 or 1 AS, 2 up to 3, 3 up to
7, ..., 8 from 128), capped at --max-pops: small transit ASes with a
handful of customers carry little transit traffic. Tier-1s get --max-pops,
unless they are in --tier1-pops (tier1_pops.csv): a hand-curated list of
their PoP cities from the operators' network maps and looking glasses, with
the source of each city (and coordinates for towns GeoNames does not list or
would resolve to another place). A listed tier-1 gets exactly those PoPs.

Cloud providers and CDNs (providers.py) also get a PoP at every candidate
server site: their cloud regions and the metros of their PeeringDB
facilities and IXPs. place_servers.py only attaches servers to these
routers, so the network is the same for every server count and seed.

Edges:
  - internal: full mesh between the PoPs of an AS, except for cloud
    providers, CDNs and tier-1s, which get a hub backbone (isHub 1 on hubs). Hubs
    are the cloud regions (AWS, Azure, GCP) or, for CDNs, the metros with
    the most IXPs, about one per HUB_EVERY PoPs; every continent with PoPs
    has at least one, and every backbone at least HUB_HOMING (or all its
    PoPs, if fewer), so none is a single-hub star. Each other PoP links to
    its HUB_HOMING nearest hubs;
    hubs are meshed within a continent and each links to its HUB_HOMING
    nearest hubs on other continents;
  - inter-AS (c2p, p2p): one link in each metro where both ASes have a PoP
    (best-scoring first, at most --max-links-per-pair, --max-links-tier1-pair
    between two tier-1s that are not siblings, no cap if either is a cloud
    provider or CDN); siblings are ASes of one organisation in CAIDA's
    AS2Org data or with the same operator in tier1_pops.csv; if
    they share none, one link between their closest pair of PoPs;
  - transit: every cloud or CDN PoP with no c2p link from a provider gets
    one from the nearest PoP of one of its providers (in its own metro if
    there is one).
Edge delay = --link-base-ms + great-circle km * --ms-per-km (0.007 ms/km
is light in fibre, ~0.005 ms/km, with ~1.4x path inflation).

Each router also gets:
  locSource  peeringdb, geoip, peeringdb+geoip, rir-country, neighbour,
             curated (tier1_pops.csv), or server-site for cloud/CDN PoPs
             added at candidate sites
  ipv4Addrs  geolocated IPv4 addresses of its AS in its metro
  pdbType    the AS's PeeringDB network type (e.g. "Cable/DSL/ISP",
             "Content", "NSP"), empty if the AS is not in PeeringDB
  observedCone  number of other ASes of the topology in its AS's observed
             customer cone
  isHub      cloud providers, CDNs and tier-1s only: 1 on backbone hubs, else 0

Data files (see fetch_location_data.sh), looked up in --data-dir:
  peeringdb_2_dump_*.json, *.pfx2as.gz, dbip-city-lite-*.csv.gz,
  cities15000.zip, countryInfo.txt, delegated-*-extended-latest,
  caida_ppdc/<date>.ppdc-ases.txt.bz2 (date taken from the as-rel file name),
  as2org/*.as-org2info.txt.gz (optional; sibling tier-1s)
IP geolocation by DB-IP.com (https://db-ip.com), licensed CC BY 4.0.

Usage:
  .venv/bin/python3 build_caida_topology.py 20260801.as-rel.txt -o caida_real.gml
"""
import argparse
import collections
import csv
import glob
import gzip
import io
import json
import os
import re
import sys
import time
import zipfile

import numpy as np
from scipy.spatial import cKDTree

import providers
from gml_lines import read_cones


EARTH_RADIUS_KM = 6371.0
HUB_EVERY = 10  # CDN backbones: about one hub per this many PoPs
HUB_HOMING = 2  # each PoP links to this many nearest hubs
W_FAC = 0.8
W_IX = 0.5
CONTINENTS = {
    "AF": "Africa", "AS": "Asia", "EU": "Europe", "NA": "North America",
    "OC": "Oceania", "SA": "South America", "AN": "Antarctica",
}
# Keep the short names the original topology uses.
COUNTRY_NAME_OVERRIDES = {"US": "USA", "GB": "UK", "AE": "UAE"}


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def find_one(data_dir, pattern):
    paths = sorted(glob.glob(os.path.join(data_dir, pattern)))
    if not paths:
        log(f"Missing data file {pattern} in {data_dir}; run fetch_location_data.sh first.")
        sys.exit(1)
    return paths[-1]


def to_xyz(lat, lon):
    la, lo = np.radians(np.asarray(lat, dtype=float)), np.radians(np.asarray(lon, dtype=float))
    return np.column_stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])


def chord_to_km(chord):
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.minimum(1.0, chord / 2))


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.minimum(1.0, np.sqrt(a)))


class Gazetteer:
    """GeoNames cities (15k+ inhabitants) and countries. Metros are city
    indices into these arrays."""

    def __init__(self, data_dir, metro_pop, metro_radius_km):
        self.countries = {}  # iso2 -> (name, continent)
        with open(find_one(data_dir, "countryInfo.txt"), encoding="utf-8") as f:
            for line in f:
                if line.startswith("#"):
                    continue
                c = line.rstrip("\n").split("\t")
                name = COUNTRY_NAME_OVERRIDES.get(c[0], c[4])
                self.countries[c[0]] = (name, CONTINENTS.get(c[8], ""))

        names, ccs, lats, lons, pops = [], [], [], [], []
        self.by_name = {}  # (cc, lower name) -> city idx, primary/ascii names
        by_alt = {}  # (cc, lower alternate name) -> city idx
        with zipfile.ZipFile(find_one(data_dir, "cities15000.zip")) as z:
            with z.open("cities15000.txt") as raw:
                for line in io.TextIOWrapper(raw, encoding="utf-8"):
                    c = line.rstrip("\n").split("\t")
                    if c[7] == "PPLX":  # districts of a larger city
                        continue
                    i = len(names)
                    names.append(c[1])
                    ccs.append(c[8])
                    lats.append(float(c[4]))
                    lons.append(float(c[5]))
                    pops.append(int(c[14] or 0))
                    for key, table in [(c[1], self.by_name), (c[2], self.by_name)] + [
                        (a, by_alt) for a in c[3].split(",") if len(a) > 2
                    ]:
                        k = (c[8], key.lower())
                        j = table.get(k)
                        if j is None or pops[j] < pops[i]:
                            table[k] = i
        for k, i in by_alt.items():
            self.by_name.setdefault(k, i)

        self.name = names
        self.cc = ccs
        self.lat = np.array(lats)
        self.lon = np.array(lons)
        self.pop = np.array(pops)
        xyz = to_xyz(self.lat, self.lon)
        # Metro centres: big cities, largest first, skipping any within
        # metro_radius_km of a bigger centre in the same country (so suburbs
        # merge into it, but e.g. Hong Kong stays apart from Shenzhen).
        centres = []
        for i in np.argsort(-self.pop):
            if self.pop[i] < metro_pop:
                break
            same = [c for c in centres if ccs[c] == ccs[i]]
            if not same or haversine_km(self.lat[i], self.lon[i], self.lat[same], self.lon[same]).min() > metro_radius_km:
                centres.append(i)
        self.metro_idx = np.array(centres)
        self.metro_tree = cKDTree(xyz[self.metro_idx])
        self.all_tree = cKDTree(xyz)
        self.metro_radius_km = metro_radius_km
        self.main_city = {}
        for i in np.argsort(-self.pop):
            self.main_city.setdefault(ccs[i], int(i))

    def snap(self, lat, lon):
        """Metro (city index) of each coordinate."""
        xyz = to_xyz(np.atleast_1d(lat), np.atleast_1d(lon))
        d, i = self.metro_tree.query(xyz)
        res = self.metro_idx[i]
        far = chord_to_km(d) > self.metro_radius_km
        if far.any():
            _, j = self.all_tree.query(xyz[far])
            # The nearest city may itself be within reach of a centre; use
            # that centre then, so snapping a metro's own coordinates
            # returns the same metro.
            dj, ij = self.metro_tree.query(to_xyz(self.lat[j], self.lon[j]))
            res[far] = np.where(chord_to_km(dj) <= self.metro_radius_km, self.metro_idx[ij], j)
        return res

    def geocode(self, city, cc):
        """Metro of a (city name, ISO2 country) pair, or None."""
        if not city:
            return None
        for cand in [city] + re.split(r"[,/(]", city)[:1]:
            i = self.by_name.get((cc, cand.strip().lower()))
            if i is not None:
                return int(self.snap(self.lat[i], self.lon[i])[0])
        return None

    def country(self, cc):
        return self.countries.get(cc, (cc, ""))


def load_peeringdb(data_dir, gaz):
    """Per AS: Counter of metro -> number of facilities, set of IXP metros,
    and PeeringDB network type; and Counter of metro -> number of IXPs."""
    path = find_one(data_dir, "peeringdb_2_dump_*.json")
    with open(path, encoding="utf-8") as f:
        d = json.load(f)

    fac_metro = {}
    for fac in d["fac"]["data"]:
        lat, lon = fac.get("latitude"), fac.get("longitude")
        if lat is not None and lon is not None and (lat, lon) != (0, 0):
            fac_metro[fac["id"]] = int(gaz.snap(lat, lon)[0])
        else:
            m = gaz.geocode(fac.get("city"), fac.get("country"))
            if m is not None:
                fac_metro[fac["id"]] = m

    ix_facs = collections.defaultdict(list)
    for x in d["ixfac"]["data"]:
        if x["fac_id"] in fac_metro:
            ix_facs[x["ix_id"]].append(fac_metro[x["fac_id"]])
    ix_metro = {}
    for ix in d["ix"]["data"]:
        if ix_facs.get(ix["id"]):
            ix_metro[ix["id"]] = collections.Counter(ix_facs[ix["id"]]).most_common(1)[0][0]
        else:
            m = gaz.geocode(ix.get("city"), ix.get("country"))
            if m is not None:
                ix_metro[ix["id"]] = m

    as_fac = collections.defaultdict(collections.Counter)
    for nf in d["netfac"]["data"]:
        if nf["fac_id"] in fac_metro and nf.get("local_asn"):
            as_fac[str(nf["local_asn"])][fac_metro[nf["fac_id"]]] += 1
    as_ix = collections.defaultdict(set)
    for nl in d["netixlan"]["data"]:
        if nl["ix_id"] in ix_metro and nl.get("asn"):
            as_ix[str(nl["asn"])].add(ix_metro[nl["ix_id"]])
    as_type = {str(n["asn"]): n.get("info_type") or "" for n in d["net"]["data"]}
    log(f"PeeringDB: {len(fac_metro)} facilities, {len(ix_metro)} IXPs located; "
        f"{len(as_fac)} ASes with facilities, {len(as_ix)} with IXPs ({os.path.basename(path)})")
    return as_fac, as_ix, as_type, collections.Counter(ix_metro.values())


def ipv4_to_int(s):
    a, b, c, d = s.split(".")
    return (int(a) << 24) | (int(b) << 16) | (int(c) << 8) | int(d)


def load_geoip(data_dir, gaz, wanted_asns):
    """Per AS: dict metro -> share of its geolocated IPv4 addresses, and
    dict metro -> number of addresses.
    Nested prefixes are counted for each origin (a /16 also gets credit for
    a more-specific /24 announced by someone else); multi-origin prefixes
    are split evenly between their origins."""
    dbip_path = find_one(data_dir, "dbip-city-lite-*.csv.gz")
    starts, ends, lats, lons = [], [], [], []
    with gzip.open(dbip_path, "rt", encoding="utf-8") as f:
        for row in csv.reader(f):
            if ":" in row[0] or row[3] == "ZZ":
                continue
            starts.append(ipv4_to_int(row[0]))
            ends.append(ipv4_to_int(row[1]))
            lats.append(float(row[6]))
            lons.append(float(row[7]))
    starts = np.array(starts, dtype=np.int64)
    ends = np.array(ends, dtype=np.int64)
    order = np.argsort(starts)
    starts, ends = starts[order], ends[order]
    coords = np.column_stack([np.array(lats)[order], np.array(lons)[order]])
    uniq, inv = np.unique(coords, axis=0, return_inverse=True)
    range_metro = gaz.snap(uniq[:, 0], uniq[:, 1])[inv.ravel()]
    log(f"DB-IP: {len(starts)} IPv4 ranges, {len(uniq)} distinct locations ({os.path.basename(dbip_path)})")

    pfx_path = find_one(data_dir, "*.pfx2as.gz")
    p_start, p_end, p_as, p_frac = [], [], [], []
    with gzip.open(pfx_path, "rt") as f:
        for line in f:
            addr, plen, origins = line.split()
            plen = int(plen)
            if plen < 8 or plen > 24:
                continue
            ases = [a for a in re.split(r"[_,]", origins) if a in wanted_asns]
            if not ases:
                continue
            s = ipv4_to_int(addr)
            n_orig = len(re.split(r"[_,]", origins))
            for a in ases:
                p_start.append(s)
                p_end.append(s + (1 << (32 - plen)) - 1)
                p_as.append(int(a))
                p_frac.append(1.0 / n_orig)
    p_start = np.array(p_start, dtype=np.int64)
    p_end = np.array(p_end, dtype=np.int64)
    p_as = np.array(p_as, dtype=np.int64)
    p_frac = np.array(p_frac)

    # Expand each prefix into the DB-IP ranges it overlaps, fully vectorized.
    i0 = np.maximum(np.searchsorted(starts, p_start, "right") - 1, 0)
    i1 = np.searchsorted(starts, p_end, "right") - 1
    counts = np.maximum(i1 - i0 + 1, 0)
    rep = np.repeat(np.arange(len(p_start)), counts)
    offset = np.arange(counts.sum()) - np.repeat(np.cumsum(counts) - counts, counts)
    idx = i0[rep] + offset
    overlap = np.minimum(p_end[rep], ends[idx]) - np.maximum(p_start[rep], starts[idx]) + 1
    ok = overlap > 0
    key = p_as[rep][ok] * (1 << 20) + range_metro[idx][ok]
    weight = overlap[ok] * p_frac[rep][ok]
    ukey, kinv = np.unique(key, return_inverse=True)
    wsum = np.bincount(kinv.ravel(), weights=weight)

    as_addrs = collections.defaultdict(dict)
    for k, w in zip(ukey.tolist(), wsum.tolist()):
        as_addrs[str(k >> 20)][k & ((1 << 20) - 1)] = w
    as_geo = {}
    for a, metros in as_addrs.items():
        total = sum(metros.values())
        as_geo[a] = {m: w / total for m, w in metros.items()}
    log(f"Geolocation: {len(p_start)} prefix/origin pairs, {len(as_geo)} ASes located "
        f"({os.path.basename(pfx_path)})")
    return as_geo, as_addrs


def load_rir_countries(data_dir):
    starts, counts, ccs = [], [], []
    for path in glob.glob(os.path.join(data_dir, "delegated-*-extended-latest")):
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                c = line.split("|")
                if len(c) >= 7 and c[2] == "asn" and c[1] not in ("", "*") and c[6] in ("allocated", "assigned"):
                    starts.append(int(c[3]))
                    counts.append(int(c[4]))
                    ccs.append(c[1])
    order = np.argsort(starts)
    starts = np.array(starts, dtype=np.int64)[order]
    counts = np.array(counts, dtype=np.int64)[order]
    ccs = [ccs[i] for i in order]
    log(f"RIR delegations: {len(starts)} ASN blocks")

    def lookup(asn):
        i = np.searchsorted(starts, asn, "right") - 1
        if i >= 0 and asn < starts[i] + counts[i]:
            return ccs[i]
        return None

    return lookup


def choose_pops(gaz, fac, ix, geo, max_pops, min_geo_share, diversity_km):
    """Return [(metro, score)] for one AS, best first."""
    score = collections.Counter()
    for m, share in geo.items():
        score[m] += share
    n_fac = sum(fac.values())
    for m, c in fac.items():
        score[m] += W_FAC * c / n_fac
    for m in ix:
        score[m] += W_IX / len(ix)
    top_geo = max(geo, key=geo.get) if geo else None
    eligible = {
        m: s for m, s in score.items()
        if m in fac or m in ix or geo.get(m, 0) >= min_geo_share or m == top_geo
    }
    chosen = []
    while eligible and len(chosen) < max_pops:
        m = max(eligible, key=lambda k: (eligible[k], -k))
        chosen.append((m, score[m]))
        del eligible[m]
        for k in eligible:
            if haversine_km(gaz.lat[m], gaz.lon[m], gaz.lat[k], gaz.lon[k]) < diversity_km:
                eligible[k] *= 0.25
    return chosen


def load_tier1_pops(path, gaz):
    """Curated tier-1 PoP list (CSV: asn, operator, city, country_iso2,
    source_url, accessed, notes, lat, lon) -> ({asn: sorted metros},
    {asn: operator}). A row's lat/lon, when given, place it (towns
    GeoNames does not list, or names it would resolve to another place,
    e.g. Quincy WA); otherwise the city name is looked up. Cities that are
    still not found are reported and skipped."""
    out, operator, missed = collections.defaultdict(set), {}, []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            operator[row["asn"]] = row["operator"]
            if row.get("lat") and row.get("lon"):
                m = int(gaz.snap(float(row["lat"]), float(row["lon"]))[0])
            else:
                m = gaz.geocode(row["city"], row["country_iso2"])
            if m is None:
                missed.append(f"{row['city']} ({row['country_iso2']})")
            else:
                out[row["asn"]].add(m)
    if missed:
        log(f"Tier-1 PoP list: {len(missed)} cities not found and skipped: {', '.join(sorted(set(missed)))}")
    log(f"Tier-1 PoP list: {len(out)} ASes, {sum(map(len, out.values()))} metros ({os.path.basename(path)})")
    return {a: sorted(ms) for a, ms in out.items()}, operator


def load_as_orgs(data_dir):
    """CAIDA AS-to-organisation file (data/as2org/*.as-org2info.txt.gz, the
    latest one) -> {asn: org id}, or {} if there is none."""
    paths = sorted(glob.glob(os.path.join(data_dir, "as2org", "*.as-org2info.txt.gz")))
    if not paths:
        log("No CAIDA AS-to-organisation file in data/as2org/; siblings come from tier1_pops.csv only.")
        return {}
    org, fmt = {}, []
    with gzip.open(paths[-1], "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("# format:"):
                fmt = line[len("# format:"):].strip().split("|")
            elif not line.startswith("#") and fmt and fmt[0] == "aut":
                row = dict(zip(fmt, line.rstrip("\n").split("|")))
                org[row["aut"]] = row["org_id"]
    log(f"AS organisations: {len(org)} ASes ({os.path.basename(paths[-1])})")
    return org


def choose_hubs(gaz, metros, metro_ix, fixed=()):
    """Hub metros of a provider backbone: the fixed ones (cloud regions)
    if any, else the metros with the most IXPs, about 1 per HUB_EVERY PoPs;
    plus the best metro of every continent that has none. Every backbone
    has at least HUB_HOMING hubs (or all its PoPs, if fewer), so each PoP
    is homed to more than one hub: a network on one continent with 10 PoPs
    or fewer (AT&T) is no longer a single-hub star. A continent can still
    have one hub; its other PoPs then also home to the nearest hub abroad."""
    continent = {m: gaz.country(gaz.cc[m])[1] for m in metros}
    rank = sorted(metros, key=lambda m: (-metro_ix[m], -gaz.pop[m], m))
    hubs = [m for m in rank if m in set(fixed)]
    for c in sorted(set(continent.values())):
        if not any(continent[h] == c for h in hubs):
            hubs.append(next(m for m in rank if continent[m] == c))
    target = min(HUB_HOMING, len(metros))
    if not fixed:
        target = max(target, int(np.ceil(len(metros) / HUB_EVERY)))
    hubs += [m for m in rank if m not in hubs][: max(0, target - len(hubs))]
    return hubs


def backbone_links(gaz, metros, hubs):
    """Metro pairs of a hub backbone: each other PoP to its HUB_HOMING
    nearest hubs; hubs meshed within a continent, and each hub to its
    HUB_HOMING nearest hubs on other continents."""
    continent = {m: gaz.country(gaz.cc[m])[1] for m in metros}
    h = np.array(hubs)

    def km(m, others):
        return haversine_km(gaz.lat[m], gaz.lon[m], gaz.lat[others], gaz.lon[others])

    pairs = set()
    for m in metros:
        if m in hubs:
            continue
        for j in np.argsort(km(m, h), kind="stable")[:HUB_HOMING]:
            pairs.add(frozenset((m, int(h[j]))))
    for i, a in enumerate(hubs):
        for b in hubs[i + 1:]:
            if continent[a] == continent[b]:
                pairs.add(frozenset((a, b)))
        abroad = np.array([b for b in hubs if continent[b] != continent[a]])
        if abroad.size:
            for j in np.argsort(km(a, abroad), kind="stable")[:HUB_HOMING]:
                pairs.add(frozenset((a, int(abroad[j]))))
    return sorted(tuple(sorted(p)) for p in pairs)


def gml_value(v):
    if isinstance(v, str):
        return f'"{v}"'
    if isinstance(v, float):
        return repr(v)
    return str(v)


def load_as_rel(path, exclude=frozenset()):
    """CAIDA as-rel file -> (AS list sorted by number, tier per AS,
    [(source AS, target AS, type)]). c2p links are written provider ->
    customer, as in CAIDA's `provider|customer|-1` lines (the routing
    script auto-detects this from the tiers). ASes in exclude are dropped
    with their links before the check for a provider path to the clique."""
    clique, links, ases = set(), [], set()
    has_customers, excluded = set(), set()
    with open(path) as f:
        for line in f:
            if line.startswith("# input clique:"):
                clique = set(line.split(":", 1)[1].split())
            if line.startswith("#") or not line.strip():
                continue
            a, b, rel = line.strip().split("|")[:3]
            if a in exclude or b in exclude:
                excluded.update({a, b} & exclude)
                continue
            ases.update((a, b))
            if rel == "-1":
                links.append((a, b, "c2p"))
                has_customers.add(a)
            elif rel == "0":
                links.append((a, b, "p2p"))
    if excluded:
        log(f"Excluded {len(excluded)} ASes before the clique check (route servers)")
    if not clique:
        log(f"No '# input clique:' line in {path}; no AS will be tier1.")
    else:
        # Keep only the clique and its customer cones. Other ASes (no
        # provider, or providers that themselves have no provider path to
        # the clique) can only reach their peers' customer cones under
        # valley-free routing; CAIDA misses their upstreams.
        customers = collections.defaultdict(list)
        for a, b, t in links:
            if t == "c2p":
                customers[a].append(b)
        keep, stack = set(clique), list(clique)
        while stack:
            for c in customers.get(stack.pop(), ()):
                if c not in keep:
                    keep.add(c)
                    stack.append(c)
        dropped = ases - keep
        no_provider = dropped - {b for a, b, t in links if t == "c2p"}
        n_links = len(links)
        ases &= keep
        links = [l for l in links if l[0] in keep and l[1] in keep]
        has_customers = {a for a, b, t in links if t == "c2p"}
        log(f"Dropped {len(dropped)} ASes with no provider path to the clique "
            f"({len(no_provider)} with no provider at all) and their {n_links - len(links)} links")
    tier = {a: "tier1" if a in clique else "transit" if a in has_customers else "stub" for a in ases}
    order = sorted(ases, key=lambda a: (len(a), a))
    return order, tier, links


def load_observed_cones(data_dir, as_rel_path, ppdc_path=None):
    """CAIDA ppdc-ases file of the as-rel file's date: {asn: set of the
    other ASes in its observed customer cone}."""
    if ppdc_path is None:
        date = re.match(r"\d{8}", os.path.basename(as_rel_path))
        if not date:
            log(f"Cannot tell the date of {as_rel_path}; pass --ppdc.")
            sys.exit(1)
        ppdc_path = find_one(data_dir, f"caida_ppdc/{date.group(0)}.ppdc-ases.txt*")
    cones = read_cones(ppdc_path)
    log(f"Observed customer cones: {len(cones)} ASes ({os.path.basename(ppdc_path)})")
    return cones


def write_cones(path, cones, as_order):
    """Sidecar file: one line per AS of the topology with a non-empty
    observed cone, the AS then the cone's members in the topology (CAIDA's
    ppdc-ases format)."""
    keep = set(as_order)
    n = 0
    with open(path, "w") as f:
        f.write("# Observed customer cones (CAIDA ppdc-ases), restricted to the ASes of the topology.\n"
                "# Format: <AS> <customer cone member> ... (the AS itself is not repeated).\n"
                "# Rule: AS p may use a customer route to AS d only if d is in p's line here;\n"
                "# tier-1s (tier \"tier1\" in the GML) are unrestricted. An AS with no line has an empty cone.\n")
        for a in as_order:
            members = sorted(cones.get(a, set()) & keep, key=lambda x: (len(x), x))
            if members:
                f.write(a + " " + " ".join(members) + "\n")
                n += len(members)
    return n


def customer_cone_sizes(links):
    """Number of ASes in each AS's customer cone (customers, their
    customers, ...), excluding itself."""
    customers = collections.defaultdict(list)
    for a, b, t in links:
        if t == "c2p":
            customers[a].append(b)
    sizes = {}
    for root in customers:
        seen, stack = {root}, [root]
        while stack:
            for c in customers.get(stack.pop(), ()):
                if c not in seen:
                    seen.add(c)
                    stack.append(c)
        sizes[root] = len(seen) - 1
    return sizes


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("as_rel", help="CAIDA AS-relationship file (e.g. 20260801.as-rel.txt)")
    ap.add_argument("-o", "--output", required=True, help="output GML path")
    ap.add_argument("--data-dir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
    ap.add_argument("--ppdc", help="CAIDA ppdc-ases file (default: data/caida_ppdc/<as-rel date>.ppdc-ases.txt.bz2)")
    ap.add_argument("--max-pops", type=int, default=8, help="max PoPs (routers) per transit/tier1 AS; fewer for small observed customer cones (default 8)")
    ap.add_argument("--max-pops-stub", type=int, default=1, help="max PoPs per stub AS (default 1; stubs never carry transit)")
    ap.add_argument("--min-geo-share", type=float, default=0.10,
                    help="min share of an AS's addresses for a geolocated metro to become a PoP (default 0.10)")
    ap.add_argument("--min-geo-share-transit", type=float, default=0.02,
                    help="same, for transit/tier1 ASes (default 0.02)")
    ap.add_argument("--diversity-km", type=float, default=300.0,
                    help="down-weight candidate PoPs this close to an already chosen one (default 300)")
    ap.add_argument("--metro-pop", type=int, default=500_000,
                    help="min population of a city to act as a metro centre (default 500000)")
    ap.add_argument("--metro-radius-km", type=float, default=50.0,
                    help="locations within this distance snap to a metro centre (default 50)")
    ap.add_argument("--max-links-per-pair", type=int, default=4,
                    help="max parallel links between two ASes sharing several metros (default 4)")
    ap.add_argument("--max-links-tier1-pair", type=int, default=16,
                    help="the same between two tier-1s that are not siblings (default 16)")
    ap.add_argument("--tier1-pops", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "tier1_pops.csv"),
                    help="curated tier-1 PoP list (default tier1_pops.csv next to this script; '' for none)")
    ap.add_argument("--ms-per-km", type=float, default=0.007, help="propagation delay per km (default 0.007)")
    ap.add_argument("--link-base-ms", type=float, default=0.2, help="fixed delay added to every link (default 0.2)")
    ap.add_argument("--single-pop-internal-delay", type=float, default=1.5,
                    help="internalDelayMs of single-router ASes (default 1.5)")
    args = ap.parse_args()
    t0 = time.perf_counter()

    if os.path.abspath(args.output) == os.path.abspath(args.as_rel):
        log("Refusing to overwrite the input file; pass a different -o path.")
        sys.exit(1)

    gaz = Gazetteer(args.data_dir, args.metro_pop, args.metro_radius_km)
    as_fac, as_ix, as_type, metro_ix = load_peeringdb(args.data_dir, gaz)
    route_servers = {a for a, t in as_type.items() if t == "Route Server"}
    as_order, as_tier, links = load_as_rel(args.as_rel, exclude=route_servers)
    log(f"Input: {len(as_order)} ASes ({dict(collections.Counter(as_tier.values()))}), "
        f"{sum(t == 'c2p' for *_, t in links)} c2p and {sum(t == 'p2p' for *_, t in links)} p2p links ({args.as_rel})")
    cones = load_observed_cones(args.data_dir, args.as_rel, args.ppdc)
    in_topo = set(as_order)
    cone = {a: len(cones.get(a, set()) & in_topo) for a in as_order}
    as_geo, as_addrs = load_geoip(args.data_dir, gaz, set(as_order))
    rir_cc = load_rir_countries(args.data_dir)
    curated, t1_operator = load_tier1_pops(args.tier1_pops, gaz) if args.tier1_pops else ({}, {})
    as_org = load_as_orgs(args.data_dir)

    def siblings(a, b):
        """Same organisation (CAIDA AS2Org) or same operator in the tier-1 list."""
        return (as_org.get(a) is not None and as_org.get(a) == as_org.get(b)) or \
            (a in t1_operator and t1_operator[a] == t1_operator.get(b))

    # PoPs per AS.
    pops = {}  # asn -> [(metro, score)]
    source = {}
    for asn in as_order:
        if as_tier[asn] == "tier1" and curated.get(asn):
            # Curated footprint from the operator's network map; IXP-rich
            # metros first, for the links to other tier-1s.
            pops[asn] = sorted(((m, float(metro_ix[m])) for m in curated[asn]), key=lambda p: (-p[1], p[0]))
            source[asn] = "curated"
            continue
        fac, ix, geo = as_fac.get(asn, {}), as_ix.get(asn, set()), as_geo.get(asn, {})
        if as_tier[asn] == "stub":
            cap = args.max_pops_stub
        elif as_tier[asn] == "tier1":
            cap = args.max_pops
        else:
            # 1 PoP for an observed cone of 0 or 1 AS, 2 up to 3, 3 up to 7, ..., capped.
            cap = min(args.max_pops, max(1, int(np.ceil(np.log2(cone[asn] + 1)))))
        min_share = args.min_geo_share if as_tier[asn] == "stub" else args.min_geo_share_transit
        chosen = choose_pops(gaz, fac, ix, geo, cap, min_share, args.diversity_km)
        if chosen:
            src = [s for s, ok in (("peeringdb", fac or ix), ("geoip", geo)) if ok]
            source[asn] = "+".join(src)
            pops[asn] = chosen
        else:
            cc = rir_cc(int(asn)) if asn.isdigit() else None
            if cc in gaz.main_city:
                pops[asn] = [(gaz.main_city[cc], 0.0)]
                source[asn] = "rir-country"

    # ASes with no evidence at all: the main PoP of a placed neighbour,
    # providers first, repeated until nothing changes.
    neighbours = collections.defaultdict(list)
    for a, b, t in links:
        neighbours[b].append((0 if t == "c2p" else 1, a))  # a is b's provider (c2p) or peer
        neighbours[a].append((2 if t == "c2p" else 1, b))
    changed = True
    while changed:
        changed = False
        for asn in as_order:
            if asn in pops:
                continue
            placed = sorted((rank, nb) for rank, nb in neighbours[asn] if nb in pops)
            if placed:
                pops[asn] = [(pops[placed[0][1]][0][0], 0.0)]
                source[asn] = "neighbour"
                changed = True
    unplaced = [a for a in as_order if a not in pops]
    if unplaced:
        log(f"Dropping {len(unplaced)} ASes with no location evidence and no placed neighbour")
        as_order = [a for a in as_order if a in pops]
        links = [(a, b, t) for a, b, t in links if a in pops and b in pops]

    # Cloud providers and CDNs: a PoP at every candidate server site, so
    # placing servers never changes the network, and a hub backbone.
    prov_ases = providers.provider_ases() & set(as_order)
    site_metros = {}  # asn -> metros added as server sites
    hubs = {}  # asn -> hub metros
    regions = collections.defaultdict(set)
    for prov, m in providers.cloud_sites(gaz, prov_ases):
        regions[providers.CLOUD_AS[prov]].add(m)
    for asn, metros in providers.sites_by_as(gaz, as_fac, as_ix, prov_ases).items():
        have = {m for m, _ in pops[asn]}
        site_metros[asn] = metros - have
        pops[asn] = pops[asn] + [(m, 0.0) for m in sorted(metros - have)]
    for asn in prov_ases:
        hubs[asn] = choose_hubs(gaz, [m for m, _ in pops[asn]], metro_ix, regions.get(asn, ()))
    # Tier-1s with more than one PoP get the same kind of backbone.
    tier1_bb = {a for a in as_order if as_tier[a] == "tier1" and len(pops[a]) > 1}
    for asn in tier1_bb:
        hubs[asn] = choose_hubs(gaz, [m for m, _ in pops[asn]], metro_ix)
    backbone_ases = prov_ases | tier1_bb

    # Routers.
    out_nodes = []  # (attrs dict) in output order; ids assigned by position
    as_routers = {}  # asn -> [(node index, metro)]
    for asn in as_order:
        single = len(pops[asn]) == 1
        lst = []
        for k, (m, _) in enumerate(pops[asn]):
            cname, continent = gaz.country(gaz.cc[m])
            lst.append((len(out_nodes), m))
            out_nodes.append({
                "label": f"{asn}-p{k}",
                "Country": cname,
                "Longitude": float(gaz.lon[m]),
                "Internal": 1,
                "Latitude": float(gaz.lat[m]),
                "type": "router",
                "asId": asn,
                "tier": as_tier[asn],
                "city": gaz.name[m],
                "continent": continent,
                "internalDelayMs": args.single_pop_internal_delay if single else 0,
                "locSource": "server-site" if m in site_metros.get(asn, ()) else source[asn],
                "ipv4Addrs": int(round(as_addrs.get(asn, {}).get(m, 0))),
                "pdbType": as_type.get(asn, ""),
                "observedCone": cone[asn],
            })
            if asn in backbone_ases:
                out_nodes[-1]["isHub"] = int(m in hubs[asn])
        as_routers[asn] = lst
    lat = np.array([n["Latitude"] for n in out_nodes])
    lon = np.array([n["Longitude"] for n in out_nodes])

    def delay(u, v):
        return round(args.link_base_ms + float(haversine_km(lat[u], lon[u], lat[v], lon[v])) * args.ms_per_km, 3)

    out_edges = []
    for asn in as_order:
        rs = as_routers[asn]
        if asn in backbone_ases:
            at = {m: r for r, m in rs}
            for a, b in backbone_links(gaz, list(at), hubs[asn]):
                out_edges.append((at[a], at[b], "internal", delay(at[a], at[b])))
            continue
        for i in range(len(rs)):
            for j in range(i + 1, len(rs)):
                out_edges.append((rs[i][0], rs[j][0], "internal", delay(rs[i][0], rs[j][0])))
    n_internal = len(out_edges)

    # Inter-AS links, one AS pair at a time.
    seen_pairs = set()
    pair_kinds = collections.Counter()
    sibling_t1 = set()
    for a, b, etype in links:
        if frozenset((a, b)) in seen_pairs:
            continue
        seen_pairs.add(frozenset((a, b)))
        ra, rb = as_routers[a], as_routers[b]
        score_a, score_b = dict(pops[a]), dict(pops[b])
        common = sorted(set(score_a) & set(score_b), key=lambda m: (-(score_a[m] + score_b[m]), m))
        if common:
            pair_kinds["shared metro"] += 1
            ia, ib = {m: r for r, m in ra}, {m: r for r, m in rb}
            # Cloud providers and CDNs peer in every metro they share.
            cap = None if a in prov_ases or b in prov_ases else args.max_links_per_pair
            if as_tier[a] == as_tier[b] == "tier1":
                # Sibling tier-1s (Lumen 209/3356, GTT 286/3257, Verizon
                # 701/2828) share a footprint; they get the ordinary cap,
                # not one link in every shared metro.
                if siblings(a, b):
                    sibling_t1.add(frozenset((a, b)))
                    cap = args.max_links_per_pair
                else:
                    cap = args.max_links_tier1_pair
            for m in common[:cap]:
                out_edges.append((ia[m], ib[m], etype, delay(ia[m], ib[m])))
        else:
            pair_kinds["closest PoPs"] += 1
            u, v = min(((u, v) for u, _ in ra for v, _ in rb), key=lambda p: delay(*p))
            out_edges.append((u, v, etype, delay(u, v)))
    # Every cloud or CDN PoP buys transit: a c2p link from the nearest PoP
    # of one of its providers (in its own metro if possible), unless it
    # already has one.
    up = {v for u, v, t, _ in out_edges if t == "c2p"}
    upstreams = collections.defaultdict(set)
    for a, b, t in links:
        if t == "c2p" and b in prov_ases:
            upstreams[b].add(a)
    n_transit = 0
    for asn in sorted(prov_ases):
        cand = np.array([r for p in sorted(upstreams[asn]) for r, _ in as_routers[p]])
        for r, _ in as_routers[asn]:
            if r in up or not cand.size:
                continue
            u = int(cand[np.argmin(haversine_km(lat[r], lon[r], lat[cand], lon[cand]))])
            out_edges.append((u, r, "c2p", delay(u, r)))
            n_transit += 1
    n_inter = len(out_edges) - n_internal

    cones_name = re.sub(r"\.gml$", "", os.path.basename(args.output)) + ".cones.txt"
    n_entries = write_cones(os.path.join(os.path.dirname(os.path.abspath(args.output)), cones_name), cones, as_order)
    with open(args.output, "w") as f:
        f.write(f'graph [\n  directed 0\n  observedCones "{cones_name}"\n')
        for i, n in enumerate(out_nodes):
            f.write(f"  node [\n    id {i}\n")
            for k, v in n.items():
                f.write(f"    {k} {gml_value(v)}\n")
            f.write("  ]\n")
        for u, v, t, dms in out_edges:
            f.write(f'  edge [\n    source {u}\n    target {v}\n    type "{t}"\n    delayMs {dms}\n  ]\n')
        f.write("]\n")

    n_routers = sum(len(r) for r in as_routers.values())
    per_as = collections.Counter(min(len(r), 8) for r in as_routers.values())
    cities = {m for r in as_routers.values() for _, m in r}
    log(f"Location source per AS: {dict(collections.Counter(source.values()).most_common())}")
    log(f"Routers: {n_routers} in {len(cities)} metros; ASes by router count {sorted(per_as.items())}")
    log(f"Edges: {n_internal} internal, {n_inter} inter-AS for {len(seen_pairs)} AS pairs ({dict(pair_kinds)})")
    log(f"Cloud providers and CDNs: {sum(len(as_routers[a]) for a in prov_ases)} PoPs "
        f"({sum(len(v) for v in site_metros.values())} added as server sites), "
        f"{sum(len(hubs[a]) for a in prov_ases)} hubs, {n_transit} transit links added")
    log(f"Tier-1s: {sum(len(as_routers[a]) for a in as_order if as_tier[a] == 'tier1')} PoPs "
        f"({len(curated)} curated ASes), {sum(len(hubs[a]) for a in tier1_bb)} hubs; "
        f"sibling tier-1 pairs at {args.max_links_per_pair} links: "
        f"{', '.join('/'.join(sorted(p, key=int)) for p in sorted(sibling_t1, key=lambda p: sorted(p, key=int)))}")
    n_cap = sum(len(r) == args.max_pops for a, r in as_routers.items() if as_tier[a] == "transit")
    log(f"Observed cones: {sum(c > 0 for c in cone.values())} ASes, {n_entries} entries in {cones_name}; "
        f"{n_cap} transit ASes at {args.max_pops} PoPs")
    log(f"Wrote {args.output} in {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main()

# Realistic CAIDA topology: user manual

Three scripts turn a CAIDA AS-relationship file (`20260801.as-rel.txt`)
into a realistic router-level simulation input:

1. `build_caida_topology.py` builds routers, placed where each AS actually is.
2. `place_servers.py` adds N servers under a deployment scenario.
3. `add_clients.py` tags routers of eyeball ASes with their number of clients.

Run them in that order. The first reads the as-rel file; the others read a
GML file and write a new one. No input file is ever modified. All commands
run from the project directory, with the project's Python environment.

## 0. Setup: download the data (once per snapshot)

```bash
./fetch_location_data.sh            # snapshot 20260801
./fetch_location_data.sh 20260901   # another CAIDA snapshot date
```

This downloads `<DATE>.as-rel.txt` into the project directory, plus about
260 MB into `data/`. Files that are already there are skipped.

| Data | Used for |
|---|---|
| CAIDA AS relationships (serial-1, `<DATE>.as-rel.txt`) | the ASes and their c2p/p2p relationships |
| PeeringDB dump (CAIDA archive, same date) | facilities and IXPs where each AS is present |
| RouteViews prefix2as (same date) | IPv4 prefixes announced by each AS |
| DB-IP City Lite (current month) | geolocation of those prefixes |
| GeoNames cities15000 and countryInfo | city coordinates, population, country names |
| RIR delegation files (current) | country of each AS number (fallback) |
| APNIC AS population (current) | estimated Internet users per AS and country |

DB-IP is licensed CC BY 4.0 and APNIC asks for attribution, so cite both in
publications.

## 1. Router placement: `build_caida_topology.py`

```bash
.venv/bin/python3 build_caida_topology.py 20260801.as-rel.txt -o caida_real.gml
```

**ASes and relationships.** These come straight from the as-rel file:

- `a|b|-1` means a is b's provider. It becomes a `c2p` edge, written
  provider → customer.
- `a|b|0` becomes a `p2p` edge.

**Tiers.**

- `tier1`: the 18 ASes of CAIDA's Tier-1 clique (the `# input clique` line).
- `transit`: any other AS with at least one customer.
- `stub`: everything else.

The routing script detects the c2p direction from these tiers.

**Dropped ASes.** ASes outside the customer cones of the Tier-1 clique are
dropped, with their links: 516 ASes in the 20260801 snapshot. 453 of them have
no provider in the file; the rest only have providers in that group. Under
valley-free routing such an AS can only reach its peers' customer cones. The
real AS has upstreams, but CAIDA misses them. Dropping these ASes means every
router has a valley-free route to every server.

**Router placement.** Each AS gets one router per point of presence (model
B), placed in real metros using this evidence, in order of trust:

1. PeeringDB: the facilities and IXPs the AS declares itself present at.
2. IP geolocation: where the AS's announced addresses are, weighted by
   address count.
3. RIR delegation country: the AS goes to its country's largest city.
4. Otherwise, the main PoP of a neighbouring AS, providers first. This
   applies to fewer than 100 ASes.

Locations are snapped to metros: GeoNames cities of at least 500k
inhabitants, absorbing suburbs within 50 km in the same country. All ASes in
a metro share its coordinates.

**How many PoPs.**

- Stubs get 1 PoP.
- Transit and tier-1 ASes get up to ⌈log2(cone + 1)⌉ PoPs, capped at 8.
  Here cone is the number of ASes in the AS's customer cone: its customers,
  their customers, and so on. That means 1 PoP for a cone of 1 AS, 2 for up
  to 3 ASes, 3 for up to 7, and 8 from 255.
- An AS only gets as many PoPs as it has evidence for.

**Links and delays.**

- Internal links form a full mesh between the PoPs of an AS.
- Two ASes are linked in each metro they share, up to 4 links. If they share
  no metro, they get one link between their closest PoPs.
- Link delay is 0.2 ms + 0.007 ms/km. That is light in fibre (about 0.005
  ms/km) with about 1.4× path inflation.
- The output has routers only. Servers and clients are added by the next two
  scripts.

**Rationale.** Valley-free routing means stub ASes never carry transit
traffic, so internal geography only matters for ASes that do. Small transit
ASes with a handful of customers carry little transit traffic, so the number
of PoPs grows with the size of the customer cone. The result is about 96.9k
routers in about 8.5k metros. Tier-1s and large ISPs get realistic
footprints; for example, AT&T: New York, Washington, Atlanta, Dallas,
Chicago, Los Angeles, Houston, San Francisco.

**Extra router attributes.**

| Attribute | Meaning |
|---|---|
| `locSource` | where the location came from: `peeringdb`, `geoip`, `peeringdb+geoip`, `rir-country` or `neighbour` |
| `ipv4Addrs` | geolocated IPv4 addresses of the AS in that metro |
| `pdbType` | the AS's PeeringDB network type |

**Useful options.**

| Option | Default | Effect |
|---|---|---|
| `--max-pops` | 8 | maximum PoPs for transit and tier-1 ASes, reached from a cone of 255 |
| `--max-pops-stub` | 1 | maximum PoPs for stubs; 2 adds several thousand routers |
| `--max-links-per-pair` | 4 | maximum links between two ASes |
| `--metro-pop` | 500000 | minimum population of a metro centre |
| `--metro-radius-km` | 50 | merge radius for metros |
| `--ms-per-km` | 0.007 | propagation delay per km |
| `--link-base-ms` | 0.2 | fixed delay added to every link |

Running time is about 75 s.

## 2. Servers: `place_servers.py`

```bash
.venv/bin/python3 place_servers.py caida_real.gml -o caida_servers                   # writes caida_servers_{5,10,100,1000,10000}.gml
.venv/bin/python3 place_servers.py caida_real.gml -o caida_servers --servers 50 500  # other sizes
.venv/bin/python3 place_servers.py caida_real.gml -o run2 --seed 7                   # different random draw
.venv/bin/python3 place_servers.py caida_real.gml -o cdn --servers 300 --scenario cdn  # force a scenario
```

**What it does.** It writes one GML per server count N. Each N maps to a
deployment scenario, from centralized cloud to edge cloud:

| N | Scenario | Candidate sites | Selection |
|---|---|---|---|
| ≤ 5 | centralized | AWS regions | greedy k-median |
| ≤ 10 | multi-cloud | AWS, Azure and GCP regions | greedy k-median |
| ≤ 100 | cloud-cdn | cloud regions plus metros of major CDNs | greedy k-median |
| ≤ 1000 | cdn | (CDN AS, metro) sites from PeeringDB (Cloudflare, Akamai, Fastly, …) | weighted sampling by users in each site's catchment |
| > 1000 | edge | routers of eyeball ISPs | weighted sampling by the router's users |

Greedy k-median adds, one at a time, the site that most reduces the
user-weighted distance to the nearest server. Weighted sampling is seeded and
draws without replacement, so a run with the same `--seed` is reproducible.

**How servers are attached.** Each server is a node at the metro centre with
the attributes `operator`, `hostAs`, `scenario` and `city`. It is linked by a
`hosts` edge to a router of its hosting AS in that metro. If the hosting AS
has no router there, one is added, linked to the AS's other routers and to
neighbouring ASes present in that metro. No demand edges are written.

**Rationale.** Server counts correspond to real deployment models. A few
servers means a few cloud regions chosen for coverage. Thousands of servers
means CDN or edge sites, which follow where users are. Users are measured
with APNIC estimates, the same way as `add_clients.py`, not raw population,
so placement tracks Internet demand.

The script prints, for each N, the user-weighted mean and median distance
from users to their nearest server: about 1900 km at N=5 and about 200 km at
N=100. Running time is about 25 s for all five sizes.

## 3. Clients: `add_clients.py`

```bash
.venv/bin/python3 add_clients.py caida_servers_100.gml -o caida_servers_100_clients.gml                          # real user estimates
.venv/bin/python3 add_clients.py caida_servers_100.gml -o caida_servers_100_clients.gml --total-clients 1000000  # scaled to 1M
```

**What it does.** It adds a `clientCount <n>` line to each router of an
eyeball AS. Nothing else in the file changes, so it works on
`caida_real.gml` or on any `caida_servers_N.gml`.

**How counts are computed.**

- Users come from APNIC's estimates of users per (AS, country), which
  preserves each AS's share of its country's Internet population.
- An AS's users in a country are split over its routers in that country, in
  proportion to their geolocated addresses. If the AS has no router in that
  country, they go to its routers elsewhere.
- With `--total-clients N`, counts are scaled to sum to exactly N, and
  routers left with 0 are not tagged.

**Eyeball AS.** An AS counts as eyeball if it has at least `--min-users`
APNIC users (default 1000) and is not PeeringDB type "Content". The users of
Content ASes are mostly VPN or relay traffic, such as Cloudflare WARP. Other
PeeringDB types are not used, because big ISPs are often mislabelled; for
example, MTN Nigeria is labelled "Enterprise".

**Result.** About 4.46B users on ~33k routers in ~24k ASes. By country: China
18%, India 15%, USA 6%.

**Rationale.** Clients enter the network at their ISP's PoPs, which is the
granularity of model B. Users are therefore concentrated in PoP cities; for
example, most of Jio's 295M users sit on its Mumbai router.

## 4. Routing tables (existing script)

```bash
.venv/bin/python3 add_routing_tables_valley_free.py caida_servers_100_clients.gml -o caida_servers_100_routing.gml
```

This computes valley-free (Gao-Rexford) next hops from every router to every
server. Every router/server pair has a route, because the build step drops
ASes with no provider path to the Tier-1 clique.

The output has about routers × servers entries. N=10000 gives roughly 980M
entries, likely tens of GB.

## Full pipeline

For another CAIDA snapshot, pass its date to `fetch_location_data.sh` and use
the matching `<DATE>.as-rel.txt` in the build step.

```bash
./fetch_location_data.sh
.venv/bin/python3 build_caida_topology.py 20260801.as-rel.txt -o caida_real.gml
.venv/bin/python3 place_servers.py caida_real.gml -o caida_servers
.venv/bin/python3 add_clients.py caida_servers_100.gml -o caida_servers_100_clients.gml --total-clients 1000000
.venv/bin/python3 add_routing_tables_valley_free.py caida_servers_100_clients.gml -o caida_servers_100_routing.gml
```

## Known limitations

- **Geolocation.** IP geolocation can place an AS where its addresses are
  registered rather than where its routers are; for example, Cogent's first
  PoP is Cleveland. China Telecom gets mostly foreign PoPs, because its
  PeeringDB presence is abroad and its Chinese addresses are spread thinly
  over many cities.
- **Data dates.** DB-IP, RIR and APNIC data are current, while PeeringDB and
  prefix2as match the CAIDA snapshot date.
- **CAIDA relationship data.** 516 ASes (0.6%) are dropped because CAIDA
  gives them no provider path to the Tier-1 clique. Their users are missing
  from `add_clients.py` and `place_servers.py`: about 1.1M users, 0.02%.
- **Cloud region list.** The list of cloud regions is hard-coded at the top of
  `place_servers.py`; keep it current.
- **Distances.** Coverage distances are metro-to-metro, so users and servers
  in the same metro count as 0 km.

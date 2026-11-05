# Realistic CAIDA topology: user manual

Three scripts turn a CAIDA AS-relationship file (`20260801.as-rel.txt`)
into a realistic router-level simulation input:

1. `build_caida_topology.py` builds routers, placed where each AS actually is.
2. `place_servers.py` adds N servers under a deployment scenario.
3. `add_clients.py` tags routers of eyeball ASes with their number of clients.

Run them in that order. `subset_caida_topology.py` cuts the first one's
output down to about 1K or 10K ASes for quick tests (section 5). The first reads the as-rel file; the others read a
GML file and write a new one. No input file is ever modified. All commands
run from the project directory, with the project's Python environment.

## 0. Setup: download the data (once per snapshot)

```bash
./fetch_location_data.sh            # snapshot 20260801
./fetch_location_data.sh 20260901   # another CAIDA snapshot date
```

This downloads `<DATE>.as-rel.txt` into the project directory, plus about
260 MB into `data/`. Files that are already there are skipped. Each
file's URL and download date go in `data/SOURCES.tsv`. For a file that
was already there, the date recorded is the file's modification time.
DB-IP, GeoNames, the RIR files and the APNIC page are only published in
their current version. Set `DBIP_MONTH=YYYY-MM` to pin DB-IP to a month
that is still online. The data is not committed: see `data/README.md`.
Every GML records its inputs, with hashes, in a `provenance` block (see
the README).

| Data | Used for |
|---|---|
| CAIDA AS relationships (serial-1, `<DATE>.as-rel.txt`) | the ASes and their c2p/p2p relationships |
| PeeringDB dump (CAIDA archive, same date) | facilities and IXPs where each AS is present |
| RouteViews prefix2as (same date) | IPv4 prefixes announced by each AS |
| DB-IP City Lite (current month) | geolocation of those prefixes |
| GeoNames cities15000 and countryInfo | city coordinates, population, country names |
| RIR delegation files (current) | country of each AS number (fallback) |
| APNIC AS population (current) | estimated Internet users per AS and country |
| CAIDA AS-to-organisation (`data/as2org/`, latest file; optional) | sibling ASes among the tier-1s |

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

**Dropped ASes.** IXP route servers (PeeringDB type "Route Server", 111 ASes
in the 20260801 snapshot) are dropped first: they take no part in forwarding,
but CAIDA lists 63 of them as providers. Then ASes outside the customer cones
of the Tier-1 clique are dropped, with their links: 471 ASes in the 20260801
snapshot. 416 of them have no provider in the file; the rest only have
providers in that group. Under
valley-free routing such an AS can only reach its peers' customer cones. The
real AS has upstreams, but CAIDA misses them. Dropping these ASes means every
router has a valley-free route to every server.

**Observed customer cones.** Following every c2p link of the as-rel file
(the recursive customer cone) gives some ASes cones far larger than the ones
CAIDA sees on BGP paths: Cloudflare 22,319 ASes against 1,012 observed,
AS1000 22,702 against 35. Under Gao-Rexford a customer route beats every
other route, so one such link pulls routes down chains nobody uses (routes
of about 230 ms). The builder reads CAIDA's observed cones (ppdc-ases, same
date, `data/caida_ppdc/`) and writes them, restricted to the topology's
ASes, to a sidecar file next to the GML, `<output>.cones.txt`, in the same
format: an AS, then the members of its observed cone. The GML names it in
the graph attribute `observedCones` (a path relative to the GML). Routing
uses the rule: AS p may use a customer route to AS d only if d is in p's
line of that file; tier-1s are unrestricted. `compare_customer_cones.py`
compares the two kinds of cone.

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
- Transit ASes get up to ⌈log2(cone + 1)⌉ PoPs, capped at 8. Here cone is
  the number of ASes in the AS's observed customer cone. That means 1 PoP
  for a cone of 0 or 1 AS, 2 for up to 3 ASes, 3 for up to 7, and 8 from 128.
- Tier-1s listed in `tier1_pops.csv` get exactly the PoPs listed there
  (below); the others get up to 8.
- An AS only gets as many PoPs as it has evidence for.

**Links and delays.**

- Internal links form a full mesh between the PoPs of an AS, except for
  cloud providers, CDNs and tier-1s, which get a hub backbone (below).
- Two ASes are linked in each metro they share: up to 4 links, up to 16
  between two tier-1s that are not siblings, and with no cap for cloud
  providers and CDNs. If they share no metro, they get one link between
  their closest PoPs.
- Link delay is 0.2 ms + 0.007 ms/km. That is light in fibre (about 0.005
  ms/km) with about 1.4× path inflation.
- The output has routers only. Servers and clients are added by the next two
  scripts.

**Cloud providers and CDNs.** The ASes in `providers.py` (AWS, Azure, GCP
and 11 CDNs) get a PoP at every candidate server site: their cloud regions
and the metros of their PeeringDB facilities and IXPs, about 1,100 PoPs.
Servers are only attached to these routers, so the network is the same for
every server count and seed.

- Backbone: hubs are the cloud regions for AWS, Azure and GCP, and for CDNs
  the metros with the most IXPs, about one per 10 PoPs. Every continent with
  PoPs has a hub, and every backbone at least 2, so no network is a
  single-hub star (AT&T, all in North America, has hubs in Washington and
  Chicago). Each other PoP links to its 2 nearest hubs; hubs are
  meshed within a continent, and each links to its 2 nearest hubs on other
  continents. Hubs carry `isHub 1`. Compared with a full mesh, the internal
  path between two PoPs is 1.14× the direct delay at the median (6.8 ms
  more), 2.2× at the 95th percentile.
- Peering: these ASes link to a neighbour in every metro they share, with
  no cap.
- Transit: a PoP with no link from one of the AS's providers gets one, from
  the nearest provider PoP (in its own metro if there is one).

**Tier-1s.** Automatic placement suits tier-1s badly: their PeeringDB
entries are thin or sit under sibling ASNs, and geolocation leans towards
headquarters (Lumen ended up centred on Monroe, AS286 was one router in New
York). `tier1_pops.csv` lists the PoP cities of 17 of the 18 clique ASes,
one row per city with its source URL, taken from the operators' looking
glasses and network maps (accessed 31 Oct 2026):

| AS | Operator | Cities | Source |
|---|---|---|---|
| 174 | Cogent | 97 | cogentco.com looking glass |
| 209, 3356 | Lumen | 119 | lookingglass.lumen.com; it lists no South or Central American sites (that business went to Cirion in 2022) but still 5 Mexican cities, which are kept |
| 286, 3257 | GTT | 86 | gtt.net network map (POP entries); AS286 is the former KPN backbone, now GTT |
| 701 | Verizon | 74 | verizon.com looking glass, AS701 sites (AS702/703 regions left out) |
| 1299 | Arelion | 114 | lg.twelve99.net |
| 2828 | XO | 74 | Verizon's AS701 list: XO is being routed behind AS701 |
| 2914 | NTT | 44 | gin.ntt.net Global IP Network map (one world map, though its file name ends in NA) |
| 3320 | Deutsche Telekom | 27 | wholesale.telekom.com IP Transit map data |
| 3491 | PCCW Global | 91 | Console Connect looking glass |
| 5511 | Orange | 34 | lg.opentransit.net |
| 6453 | Tata | 83 | lg.as6453.net (likely cable landings left out) |
| 6461 | Zayo | 147 | zayo.com Global IP Network map |
| 6762 | Sparkle | 49 | 5 from a Sparkle press release, 44 from PeeringDB (no usable operator list) |
| 6830 | Liberty Global | 17 | PeeringDB only (no operator list) |
| 12956 | Telxius | 41 | telxius.com network map |

AT&T (7018) has no public PoP list and keeps its automatic placement (New
York, Washington, Atlanta, Dallas, Chicago, Los Angeles, Houston, San
Francisco). Cities are looked up by name in GeoNames, except for rows
with `lat` and `lon`: towns GeoNames lists only below 15k people (Glen
Allen VA, East Wenatchee WA), places it does not list at all (Oude Meer,
approximate coordinates, marked in `notes`), and names that would resolve
to a larger town of the same name (Quincy WA, not Quincy MA; also
Bloomington CA, Riverdale IL, Wheeling WV, Wilmington DE). Coordinates come
from GeoNames `cities500`, cited by id in `notes`. Tier-1s get a hub
backbone like the cloud providers and CDNs, and two tier-1s get up to 16
links (`--max-links-tier1-pair`), one per shared metro. Siblings, which
share a footprint, get the ordinary 4: ASes of one organisation in CAIDA's
AS2Org data, or with the same operator in `tier1_pops.csv` (Lumen
209/3356, GTT 286/3257, Verizon 701/2828). With the lists, 1% of tier-1
inter-AS links are longer than 30 ms, against 10% before.

**Rationale.** Valley-free routing means stub ASes never carry transit
traffic, so internal geography only matters for ASes that do. Small transit
ASes with a handful of customers carry little transit traffic, so the number
of PoPs grows with the size of the observed customer cone. The result is about 97.0k
routers in about 8.3k metros. Tier-1s and large ISPs get realistic
footprints; for example, AT&T: New York, Washington, Atlanta, Dallas,
Chicago, Los Angeles, Houston, San Francisco.

**Extra router attributes.**

| Attribute | Meaning |
|---|---|
| `locSource` | where the location came from: `peeringdb`, `geoip`, `peeringdb+geoip`, `rir-country`, `neighbour`, `curated` (tier-1 list), or `server-site` for cloud and CDN PoPs added at candidate sites |
| `ipv4Addrs` | geolocated IPv4 addresses of the AS in that metro |
| `pdbType` | the AS's PeeringDB network type |
| `observedCone` | number of other ASes of the topology in the AS's observed customer cone |
| `isHub` | cloud providers, CDNs and tier-1s: 1 on backbone hubs, 0 elsewhere |

**Useful options.**

| Option | Default | Effect |
|---|---|---|
| `--ppdc` | `data/caida_ppdc/<date>.ppdc-ases.txt.bz2` | CAIDA observed-cone file of the as-rel date |
| `--max-pops` | 8 | maximum PoPs for transit and tier-1 ASes, reached from an observed cone of 128 |
| `--max-pops-stub` | 1 | maximum PoPs for stubs; 2 adds several thousand routers |
| `--max-links-per-pair` | 4 | maximum links between two ASes |
| `--max-links-tier1-pair` | 16 | maximum links between two tier-1s that are not siblings |
| `--tier1-pops` | `tier1_pops.csv` | curated tier-1 PoP list; `''` for automatic placement |
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
.venv/bin/python3 place_servers.py caida_real.gml -o s7 --servers 10 100 --site-selection sample --seed 7  # sampled sites
.venv/bin/python3 place_servers.py caida_real.gml -o mix --servers 1000 --scenario mixed --embedded-share 0.3  # 30% embedded in ISPs
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
| `--scenario mixed` | mixed | a share `--embedded-share` (default 0.5) embedded in eyeball ISPs, the rest at CDN sites | as edge and as cdn |

**Mixed scenario.** Large content networks serve much of their traffic from
caches embedded in ISPs. `--scenario mixed` places a share
`--embedded-share` (between 0 and 1) of the servers on eyeball routers (drawn as in edge) and
the rest at CDN sites (drawn as in cdn). Each embedded server gets
`embedded 1`, the host ISP as `hostAs`, and a content provider as
`operator`: Google, Meta, Netflix or Akamai, drawn in proportion to the
number of ISPs hosting their off-nets in 2021 (3,800, 2,200, 2,100, 1,100;
Gigis et al., SIGCOMM 2021). A provider's embedded and CDN-site servers
therefore compete. The simulator limits an embedded server's announcements
to its host AS's observed customer cone (the `observedCones` sidecar). Other
servers carry `embedded 0`. At N=1000 two seeds share about half of their
sites, against 96% in the cdn scenario.

Greedy k-median adds, one at a time, the site that most reduces the
user-weighted distance to the nearest server. It is deterministic: the seed
only breaks ties between providers in a metro. For variety across seeds up to
100 servers, `--site-selection sample` draws the metros instead, weighted by
their user catchment.

Weighted sampling is seeded by `--seed` alone and draws without replacement,
so a run with the same seed is reproducible, and within one scenario the
sites for a smaller N are a subset of those for a larger N. Scaling runs
should pass `--scenario` so every N uses the same scenario. At N=1000 the cdn
scenario draws 1,000 of 1,089 sites, so two seeds share at least 91% of
sites.

**How servers are attached.** Each server is a node at the metro centre with
the attributes `operator`, `hostAs`, `scenario` and `city`. It is linked by a
`hosts` edge to the router of its hosting AS in that metro. The builder has
already built a router at every candidate site, so the network is the same
for every N and seed; a missing router stops the script with an error. No
demand edges are written.

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
APNIC users (default 1000), is not one of the server operators
(`CDN_AS` and `CLOUD_AS` in `providers.py`), and is not PeeringDB type
"Content". The users of these ASes are mostly VPN, relay or workload
traffic, such as Cloudflare WARP; the operator list catches AWS, whose
PeeringDB type is "Enterprise" (3.1M users). Other PeeringDB types are not
used, because big ISPs are often mislabelled; for example, MTN Nigeria is
labelled "Enterprise".

**Result.** About 4.46B users on ~33k routers in ~24k ASes. By country: China
18%, India 15%, USA 6%.

**Rationale.** Clients enter the network at their ISP's PoPs, which is the
granularity of model B. Users are therefore concentrated in PoP cities; for
example, most of Jio's 295M users sit on its Mumbai router.

## 4. Routing tables

The simulator computes valley-free (Gao-Rexford) next hops and delays from
every router to every server at start-up (`src/Routing.py`), from the link
delays it loads, so the GMLs carry no tables.

`add_routing_tables_valley_free.py` computes the same tables and writes them
into a GML. It is the reference the simulator's routes are checked against:

```bash
.venv/bin/python3 add_routing_tables_valley_free.py caida_servers_100.gml -o caida_servers_100_routing.gml
```

Both apply two rules beyond plain Gao-Rexford:

- **Observed cones.** A router of AS p holds a customer route to a server in
  AS d only if p is d, p is a tier-1, or d is in p's observed cone (the
  sidecar file named by `observedCones`). Otherwise it falls back to peer and
  provider routes. `--no-observed-cones` turns this off.
- **Crossing delay.** A single-router AS stands for a whole network, so its
  router carries `internalDelayMs` (1.5 ms by default). It is added once each
  time a route passes through that router, but not at the route's source or
  at the server's hosting router. `--ignore-internal-delay` leaves it out.

Link delays follow the simulator's rules (`src/Gml.py`,
`src/Network.py`): a router link uses its `delayMs`, and a `delayMs` of 0
becomes `--default-delay-ms` (10 ms, the simulator's
`Graph.default_propagation_delay`); a server's `hosts` link uses its
`delayMs` unless it is missing or 0, then 1 ms. The builder writes a
non-zero `delayMs` on every link, so these defaults only matter for GMLs
from elsewhere.

The output has about routers × servers entries; N=1000 gives about 95M.

## 5. Smaller topologies: `subset_caida_topology.py`

For quick tests, cut the full topology down to 1,000 or 10,000 ASes ("1K
ASes, about 6.3K routers" and "10K ASes, about 22.9K routers"), then place
servers and clients on the subset as usual:

```bash
.venv/bin/python3 subset_caida_topology.py caida_real.gml -o caida_1k.gml --ases 1000
.venv/bin/python3 place_servers.py caida_1k.gml -o caida_1k_servers --servers 10 100 1000
```

**Which ASes are kept.** First, a fixed base of 377 ASes: the 18 tier-1s,
the cloud providers and CDNs of `providers.py`, and every AS whose observed
cone contains one of them. Then eyeball ASes (APNIC users, counted as in
`place_servers.py`) in an order drawn by weighted sampling without
replacement, weight = users. Each comes with every AS whose observed cone
contains it, so its provider chains up to the tier-1s are kept. Drawing
stops at the first eyeball AS that would take the total past `--ases`. The
order depends on `--seed` alone (default 1), so for one seed the 1K subset
is contained in the 10K subset.

**What is kept.** Every router of a kept AS and every edge between two kept
routers, unchanged: PoPs, backbones, hubs, inter-AS links and delays are
those of the full topology. An AS keeps only the neighbours that are in the
subset. Servers and clients are kept when every router they link to is
kept, so a GML with servers can be cut too: every cloud and CDN PoP is
kept, so servers at those sites are, but an edge or embedded server is
dropped if its host ISP is not drawn. Placing servers on the subset avoids
this. The observed cones are restricted to the
kept ASes in a new sidecar file, and each router's `observedCone` is
recomputed. Graph attributes `subsetOf`, `subsetAses` and `subsetSeed`
record how the file was made.

Observed cones are not transitive, so an AS brought in this way can still
have none of its own providers in the subset (AS3630, whose only provider
AS3755 does not list the eyeball behind it). Such an AS also brings its
providers in the same way, so every kept AS other than a tier-1 has a
provider in the subset.

**Result** (seed 1, from the full topology of 97,040 routers):

| | 1K | 10K |
|---|---|---|
| ASes (eyeball ASes drawn) | 1,000 (400) | 10,000 (7,956) |
| Routers | 6,342 | 22,881 |
| Users of the full topology | 73% | 97.5% |
| ASes that are transit | 84% | 55% |
| Median neighbours a kept AS keeps | 31% | 83% |

With the same 1,000 server sites (cdn, seed 1), every router reaches every
server, and the routes of the kept routers barely change: 99.3% (1K) and
99.7% (10K) of router-server delays are identical to the full topology's,
none is shorter, and 0.5% and 0.2% of AS paths change. The distributions
over all routers do change, because the subsets keep relatively more of the
core: mean AS-path length 3.09 (1K), 3.67 (10K) and 4.03 (full).

**Limits.** The tier-1s and the 1,117 cloud and CDN PoPs alone come to
2,363 routers, so a 1K subset has about 6.3K routers. With few eyeball
routers, the 1K subset cannot take `edge` at 10,000 servers (3,109
candidates). Stubs without users (enterprises, hosting) are never drawn,
so the AS degree distribution is shifted up: median 12 neighbours at 1K,
4 at 10K, against 2 in the full topology. Use subsets for quick tests and
check conclusions on the full topology.

## Full pipeline

For another CAIDA snapshot, pass its date to `fetch_location_data.sh` and use
the matching `<DATE>.as-rel.txt` in the build step.

```bash
./fetch_location_data.sh
.venv/bin/python3 build_caida_topology.py 20260801.as-rel.txt -o caida_real.gml
.venv/bin/python3 place_servers.py caida_real.gml -o caida_servers
.venv/bin/python3 add_clients.py caida_servers_100.gml -o caida_servers_100_clients.gml --total-clients 1000000
```

## Known limitations

- **Geolocation.** IP geolocation can place an AS where its addresses are
  registered rather than where its routers are; for example, Cogent's first
  PoP is Cleveland. China Telecom gets mostly foreign PoPs, because its
  PeeringDB presence is abroad and its Chinese addresses are spread thinly
  over many cities.
- **Data dates.** DB-IP, RIR and APNIC data are current, while PeeringDB and
  prefix2as match the CAIDA snapshot date.
- **CAIDA relationship data.** 471 ASes (0.6%) are dropped because CAIDA
  gives them no provider path to the Tier-1 clique once route servers are
  removed. Their users are missing
  from `add_clients.py` and `place_servers.py`: about 1.1M users, 0.02%.
- **Cloud region list.** The list of cloud regions is hard-coded in
  `providers.py`; keep it current.
- **Distances.** Coverage distances are metro-to-metro, so users and servers
  in the same metro count as 0 km.
- **Metro names.** A PoP takes the name and country of its metro's main
  city, which can be across a border: the McAllen (Texas) PoPs of seven
  tier-1s are labelled Reynosa, Mexico. Delays are unaffected (the cities
  are 15 km apart), but per-country counts of PoPs are not.
- **Announcements.** Every AS announces all its servers over every link to
  every neighbour, because which address blocks go over each peering is
  not published. Against RouteViews (route-views2, 1 Aug 2026, 197 AS
  pairs), AS paths are slightly short: 50% are one AS hop, against 36%
  observed, all over links CAIDA lists; the mean gap is 0.62 AS hops.
- **Route choice.** Within the best class (customer, then peer, then
  provider), routers take the lowest-delay route, while BGP prefers the
  shortest AS path, so route delays are somewhat optimistic. Every scheme
  simulated on the topology uses the same routes.
- **PoP cap.** Transit ASes outside the tier-1 list have at most
  `--max-pops` (8) PoPs. Hurricane Electric (AS6939), for example, has
  Amsterdam as its only continental European PoP, which carries 4,343 of
  its 10,479 inter-AS links.
- **Highly connected stubs.** A stub AS is a single router whatever its
  degree: Valve (AS32590) has 5,128 links on one router. None of the
  largest hosts servers or users, so in simulation runs their RIBs stay
  small.
- **Tier-1 lists.** AT&T publishes no PoP list and keeps its automatic 8
  PoPs. Lumen's Mexican PoPs are kept because its looking glass still
  lists them, though Lumen sold its Latin American business to Cirion in
  2022.
- **Siblings without AS2Org.** Without a `data/as2org/` file, sibling
  tier-1s are recognised only by the operator column of `tier1_pops.csv`,
  which names Verizon (701) and XO (2828) differently; they then get 16
  links instead of 4. Fetch the AS2Org file before building.

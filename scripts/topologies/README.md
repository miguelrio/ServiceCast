# CAIDA-based router topologies

Scripts that build router-level topologies from a CAIDA AS-relationship
snapshot, place servers under deployment scenarios of increasing size, and
tag routers with client counts. The simulator computes the valley-free
routing tables itself at start-up, so the GMLs carry no tables. See
`MANUAL.md` for details.

| Script | Purpose |
|---|---|
| `fetch_location_data.sh` | download the CAIDA, PeeringDB, geolocation, RIR and APNIC data into `data/` |
| `build_caida_topology.py` | place routers (one per PoP) from the as-rel file |
| `place_servers.py` | add N servers under a deployment scenario |
| `add_clients.py` | tag eyeball routers with client counts |
| `subset_caida_topology.py` | cut the topology down to about 1K or 10K ASes for quick tests |
| `add_client_nodes.py` | add client nodes on the N routers with the largest client counts |
| `add_routing_tables_valley_free.py` | reference valley-free routing tables, to check `src/Routing.py` against |
| `compare_customer_cones.py` | compare recursive and observed (ppdc) customer cones |
| `providers.py` | cloud providers, CDNs and their candidate server sites, shared by the builder and `place_servers.py` |
| `tier1_pops.csv` | curated PoP cities of the tier-1s, with the source of each |
| `gml_lines.py` | line-based GML reader shared by the scripts |
| `provenance.py` | the GMLs' `provenance` block; `check` and `strip` commands |
| `make_zoo_gml.py` | **placeholder, to be revised soon:** a Topology Zoo GML to a simulator-ready GML (link delays, N servers and N clients on random low-degree routers, provenance, `simulatorReady 1`) |

Requires Python 3 with numpy and scipy. The commands below run from this
directory and leave their output here; for real builds work in the
git-ignored `topologies/build/` instead (see `doc/Workflow.md`):

```bash
./fetch_location_data.sh
python3 build_caida_topology.py 20260801.as-rel.txt -o caida_real.gml
python3 place_servers.py caida_real.gml -o caida_servers
python3 add_clients.py caida_servers_100.gml -o caida_servers_100_clients.gml
python3 add_client_nodes.py caida_servers_100_clients.gml caida_servers_100_c5000.gml 5000
```

Each GML names its observed-cone sidecar (`<output>.cones.txt`) in the graph
attribute `observedCones`, as a path relative to the GML's folder; keep the
two files together. To cut a topology down for quick tests:

```bash
python3 subset_caida_topology.py caida_real.gml -o caida_1k.gml --ases 1000
```

Topology Zoo networks (`topologies/gml/`) go through `make_zoo_gml.py`, a
placeholder until it is reviewed (its delay rule, placement rule and
whether to split it into conversion and placement steps are open; see the
notes at the top of the script):

```bash
python3 make_zoo_gml.py ../../topologies/gml/Dfn.gml ../../topologies/ready/dfn_s10_c10.gml 10 10
```

or, from the repository root (as `doc/Workflow.md` does):

```bash
python3 scripts/topologies/make_zoo_gml.py topologies/gml/Dfn.gml topologies/ready/dfn_s10_c10.gml 10 10
```

See `doc/Workflow.md` for the whole path from a topology to a run.

1K ASes is about 6.3K routers, 10K ASes about 22.9K. The subsets keep every
tier-1, cloud provider and CDN PoP, so they are mostly core; check
conclusions on the full topology.

`fetch_location_data.sh` puts the as-rel file in this directory and the rest
(about 260 MB) in `data/`. Downloaded data is not committed: see
`data/README.md` for the sources, dates and licences.

Every GML has a `provenance` block in its graph attributes. It holds one
`step` for each script that worked on the file, with the code version
(`git describe --dirty` and the script's sha256), the command, every
option's resolved value, the Python and numpy versions, and
for each input file its sha256, size, dataset date, URL and download date.
To check that your input files match the ones a GML was built from, or to
compare two builds without the block:

```bash
python3 provenance.py check caida_real.gml
python3 provenance.py strip caida_real.gml > a.gml
```

IP geolocation by DB-IP.com (https://db-ip.com), licensed CC BY 4.0. User
estimates from APNIC Labs (https://stats.labs.apnic.net/aspop/).

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
| `add_client_nodes.py` | add client nodes on the N routers with the largest client counts |
| `add_routing_tables_valley_free.py` | reference valley-free routing tables, to check `src/Routing.py` against |
| `compare_customer_cones.py` | compare recursive and observed (ppdc) customer cones |
| `providers.py` | cloud providers, CDNs and their candidate server sites, shared by the builder and `place_servers.py` |
| `tier1_pops.csv` | curated PoP cities of the tier-1s, with the source of each |
| `gml_lines.py` | line-based GML reader shared by the scripts |

Requires Python 3 with numpy and scipy. Run from this directory:

```bash
./fetch_location_data.sh
python3 build_caida_topology.py 20260801.as-rel.txt -o caida_real.gml
python3 place_servers.py caida_real.gml -o caida_servers
python3 add_clients.py caida_servers_100.gml -o caida_servers_100_clients.gml
python3 add_client_nodes.py caida_servers_100_clients.gml caida_servers_100_c5000.gml 5000
```

`fetch_location_data.sh` puts the as-rel file in this directory and the rest
(about 250 MB) in `data/`; neither is committed.

IP geolocation by DB-IP.com (https://db-ip.com), licensed CC BY 4.0. User
estimates from APNIC Labs (https://stats.labs.apnic.net/aspop/).

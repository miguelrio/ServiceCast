# CAIDA-based router topologies with routing tables

Router-level topologies built from the CAIDA AS-relationship snapshot of
2026-08-01, with servers placed under deployment scenarios of increasing size
and valley-free (Gao-Rexford) routing tables from every router to every
server. See `MANUAL.md` for how they are generated.

## Routing-table files

| File | Servers | Scenario | Where |
|---|---|---|---|
| `caida_servers_5_RT.gml.xz` | 5 | centralized (AWS regions) | this folder |
| `caida_servers_10_RT.gml.xz` | 10 | multi-cloud (AWS, Azure, GCP) | this folder |
| `caida_servers_100_RT.gml.xz` | 100 | cloud regions + CDN metros | this folder |
| `caida_servers_1000_RT.gml.xz` | 1000 | CDN sites | [release `caida-20260801`](https://github.com/miguelrio/ServiceCast/releases/tag/caida-20260801) (too large for the repository) |

The files are xz-compressed GML. Decompress with `xz -dk <file>`, or read
them directly in Python with `lzma.open(path, "rt")`.

Each file has about 97k routers, and every router has a valley-free route to
every server. Each router has `nextHop "<server>" "<router>"` and
`delayMs "<server>" <ms>` lines for every server. Routers of eyeball ISPs
also have a `clientCount` attribute: APNIC's estimate of the ISP's users at
that PoP, about 4.46 billion users on about 33k routers in total.

## Scripts

| Script | Purpose |
|---|---|
| `fetch_location_data.sh` | download the CAIDA, PeeringDB, geolocation, RIR and APNIC data into `data/` |
| `build_caida_topology.py` | place routers (one per PoP) from the as-rel file |
| `place_servers.py` | add N servers under a deployment scenario |
| `add_clients.py` | tag eyeball routers with client counts |
| `add_routing_tables_valley_free.py` | compute valley-free routing tables |

Requires Python 3 with numpy and scipy. Pipeline:

```bash
./fetch_location_data.sh
python3 build_caida_topology.py 20260801.as-rel.txt -o caida_real.gml
python3 place_servers.py caida_real.gml -o caida_servers
python3 add_clients.py caida_servers_100.gml -o caida_servers_100_clients.gml
python3 add_routing_tables_valley_free.py caida_servers_100_clients.gml -o caida_servers_100_RT.gml
```

IP geolocation by DB-IP.com (https://db-ip.com), licensed CC BY 4.0. User
estimates from APNIC Labs (https://stats.labs.apnic.net/aspop/).

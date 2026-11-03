# Input data for the CAIDA topology scripts

This folder holds the downloaded input data. None of it is committed: the
licences of several sources (CAIDA's Acceptable Use Agreement in
particular) do not allow redistribution, and the files are large (about
260 MB). Only this README and the `.gitignore` are in the repository.

To download the data for a CAIDA snapshot date (default 20260801), run
from `scripts/topologies/`:

```bash
./fetch_location_data.sh [DATE]
DBIP_MONTH=2026-10 ./fetch_location_data.sh   # pin the DB-IP month
```

The script records each file's URL and download date in `SOURCES.tsv` in
this folder. For a file that was already here, it records the file's
modification time instead. The topology scripts copy those entries, with
each file's sha256, into the `provenance` block of every GML they write.

| File | Source | Dataset date | Licence / terms |
|---|---|---|---|
| `../<DATE>.as-rel.txt` | https://publicdata.caida.org/datasets/as-relationships/serial-1/ | snapshot DATE | CAIDA AUA |
| `caida_ppdc/<DATE>.ppdc-ases.txt.bz2` | same folder as the as-rel file | snapshot DATE | CAIDA AUA |
| `as2org/<DATE>.as-org2info.txt.gz` (optional) | https://publicdata.caida.org/datasets/as-organizations/ | quarterly; use the nearest one | CAIDA AUA |
| `peeringdb_2_dump_<Y>_<M>_<D>.json` | https://publicdata.caida.org/datasets/peeringdb/ | DATE | CAIDA AUA; PeeringDB AUP |
| `routeviews-rv2-<DATE>-1200.pfx2as.gz` | https://publicdata.caida.org/datasets/routing/routeviews-prefix2as/ | DATE | CAIDA AUA |
| `dbip-city-lite-<YYYY-MM>.csv.gz` | https://download.db-ip.com/free/ | month; only recent months are online | CC BY 4.0 (cite DB-IP.com) |
| `cities15000.zip`, `countryInfo.txt` | https://download.geonames.org/export/dump/ | live, undated | CC BY 4.0 (GeoNames) |
| `delegated-*-extended-latest` (5 RIRs) | ARIN, APNIC, AFRINIC, LACNIC, RIPE NCC FTP sites | live; the GML records each file's own end date | RIR terms of use |
| `apnic_aspop.html` | https://stats.labs.apnic.net/aspop/ | live, current 60-day window | attribution to APNIC Labs |

The licence column is a summary: check each source's own terms before
sharing a file outside the team.

The undated files change over time, so a rebuild months later can give a
different topology. Keep the exact copies you built from. The team shares
them privately, or shares the final GML with its `.cones.txt` sidecar.

To check that local copies match the files a GML was built from:

```bash
python3 provenance.py check caida_real.gml --data-dir data
```

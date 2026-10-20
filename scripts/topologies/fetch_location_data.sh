#!/usr/bin/env bash
# Download the CAIDA AS-relationship file for DATE (into this directory, as
# <DATE>.as-rel.txt) and the data build_caida_topology.py, place_servers.py
# and add_clients.py need (into ./data). DB-IP, RIR and APNIC files are only
# published for the current period, so those are the latest ones.
set -euo pipefail
DATE=${1:-20260801}
Y=${DATE:0:4}; M=${DATE:4:2}; D=${DATE:6:2}
BASE=$(cd "$(dirname "$0")" && pwd)
DIR=$BASE/data
mkdir -p "$DIR"
cd "$DIR"

get() { [ -s "$2" ] || curl -fL --retry 3 -o "$2" "$1"; }

if [ ! -s "$BASE/$DATE.as-rel.txt" ]; then
  curl -fL --retry 3 "https://publicdata.caida.org/datasets/as-relationships/serial-1/$DATE.as-rel.txt.bz2" \
    | bunzip2 > "$BASE/$DATE.as-rel.txt"
fi

get "https://publicdata.caida.org/datasets/peeringdb/$Y/$M/peeringdb_2_dump_${Y}_${M}_${D}.json" "peeringdb_2_dump_${Y}_${M}_${D}.json"
get "https://publicdata.caida.org/datasets/routing/routeviews-prefix2as/$Y/$M/routeviews-rv2-${DATE}-1200.pfx2as.gz" "routeviews-rv2-${DATE}-1200.pfx2as.gz"
DBIP_MONTH=$(date +%Y-%m)
get "https://download.db-ip.com/free/dbip-city-lite-${DBIP_MONTH}.csv.gz" "dbip-city-lite-${DBIP_MONTH}.csv.gz"
get "https://download.geonames.org/export/dump/cities15000.zip" cities15000.zip
get "https://download.geonames.org/export/dump/countryInfo.txt" countryInfo.txt
get "https://ftp.arin.net/pub/stats/arin/delegated-arin-extended-latest" delegated-arin-extended-latest
get "https://ftp.apnic.net/stats/apnic/delegated-apnic-extended-latest" delegated-apnic-extended-latest
get "https://ftp.afrinic.net/pub/stats/afrinic/delegated-afrinic-extended-latest" delegated-afrinic-extended-latest
get "https://ftp.lacnic.net/pub/stats/lacnic/delegated-lacnic-extended-latest" delegated-lacnic-extended-latest
get "https://ftp.ripe.net/pub/stats/ripencc/delegated-ripencc-extended-latest" delegated-ripencc-extended-latest
# APNIC estimated users per AS (current 60-day window), for place_servers.py.
get "https://stats.labs.apnic.net/aspop/" apnic_aspop.html
ls -la "$DIR"

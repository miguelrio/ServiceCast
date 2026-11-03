#!/usr/bin/env bash
# Download the CAIDA AS-relationship file for DATE (into this directory, as
# <DATE>.as-rel.txt) and the data build_caida_topology.py, place_servers.py
# and add_clients.py need (into ./data). DB-IP, RIR and APNIC files are only
# published for the current period, so those are the latest ones (set
# DBIP_MONTH=YYYY-MM to pin the DB-IP month, if that month is still online).
# Each file's URL and download date go in data/SOURCES.tsv, which the
# scripts copy into the provenance block of the GMLs they write; for a file
# that was already here, the date is its modification time.
set -euo pipefail
DATE=${1:-20260801}
Y=${DATE:0:4}; M=${DATE:4:2}; D=${DATE:6:2}
BASE=$(cd "$(dirname "$0")" && pwd)
DIR=$BASE/data
mkdir -p "$DIR"
cd "$DIR"

MANIFEST=$DIR/SOURCES.tsv
[ -s "$MANIFEST" ] || printf '# file\turl\tfetched (UTC)\thow\n' > "$MANIFEST"
# record FILE URL HOW: add FILE's entry to SOURCES.tsv. A download always
# adds one (the scripts take the last entry); a file already here only if
# it has none.
record() {
  local name; name=$(basename "$1")
  [ "$3" != download ] && awk -F'\t' -v n="$name" '$1 == n {f = 1} END {exit !f}' "$MANIFEST" && return 0
  local when; when=$([ "$3" = download ] && date -u +%Y-%m-%d || date -u -r "$1" +%Y-%m-%d)
  printf '%s\t%s\t%s\t%s\n' "$name" "$2" "$when" "$3" >> "$MANIFEST"
}
get() {
  if [ -s "$2" ]; then record "$2" "$1" mtime
  else curl -fL --retry 3 -o "$2" "$1" && record "$2" "$1" download; fi
}

AS_REL_URL="https://publicdata.caida.org/datasets/as-relationships/serial-1/$DATE.as-rel.txt.bz2"
if [ ! -s "$BASE/$DATE.as-rel.txt" ]; then
  curl -fL --retry 3 "$AS_REL_URL" | bunzip2 > "$BASE/$DATE.as-rel.txt"
  record "$BASE/$DATE.as-rel.txt" "$AS_REL_URL" download
else
  record "$BASE/$DATE.as-rel.txt" "$AS_REL_URL" mtime
fi

# Customer cones CAIDA observes on BGP paths, for compare_customer_cones.py.
mkdir -p caida_ppdc
get "https://publicdata.caida.org/datasets/as-relationships/serial-1/$DATE.ppdc-ases.txt.bz2" "caida_ppdc/$DATE.ppdc-ases.txt.bz2"
# AS-to-organisation mapping, for sibling tier-1s (published every three
# months; the latest one is used, so this may 404 for other dates).
mkdir -p as2org
get "https://publicdata.caida.org/datasets/as-organizations/$DATE.as-org2info.txt.gz" "as2org/$DATE.as-org2info.txt.gz" \
  || { rm -f "as2org/$DATE.as-org2info.txt.gz"
       echo "No AS2Org file for $DATE; put the nearest one from publicdata.caida.org/datasets/as-organizations/ in data/as2org/"; }
get "https://publicdata.caida.org/datasets/peeringdb/$Y/$M/peeringdb_2_dump_${Y}_${M}_${D}.json" "peeringdb_2_dump_${Y}_${M}_${D}.json"
get "https://publicdata.caida.org/datasets/routing/routeviews-prefix2as/$Y/$M/routeviews-rv2-${DATE}-1200.pfx2as.gz" "routeviews-rv2-${DATE}-1200.pfx2as.gz"
DBIP_MONTH=${DBIP_MONTH:-$(date +%Y-%m)}
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

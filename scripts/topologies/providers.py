#!/usr/bin/env python3
"""
Cloud providers and CDNs: their ASes, cloud regions and candidate server
sites. build_caida_topology.py builds a PoP at every site up front (with a
hub backbone), and place_servers.py draws servers from the same sites, so
placing servers never changes the network.

Sites:
  cloud  (provider, metro) for each region in CLOUD_REGIONS, snapped to the
         gazetteer's metros;
  cdn    (AS, metro) for each metro of a CDN_AS member's PeeringDB
         facilities and IXPs.
"""

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
# (Edgio, AS22822, shut down in 2025 and is not in the 20260801 CAIDA data.)
CDN_AS = {
    "13335": "Cloudflare", "20940": "Akamai", "54113": "Fastly", "16509": "AWS",
    "15169": "Google", "8075": "Microsoft", "60068": "CDN77",
    "199524": "Gcore", "32934": "Meta", "2906": "Netflix", "714": "Apple",
}


def provider_ases():
    """ASes of all cloud providers and CDNs."""
    return set(CDN_AS) | set(CLOUD_AS.values())


def cloud_sites(gaz, present):
    """Sorted (provider name, metro) of the cloud regions of providers whose
    AS is in present."""
    metros = gaz.snap([r[2] for r in CLOUD_REGIONS], [r[3] for r in CLOUD_REGIONS]).tolist()
    return sorted({(r[0], m) for r, m in zip(CLOUD_REGIONS, metros) if CLOUD_AS[r[0]] in present})


def cdn_sites(as_fac, as_ix, present):
    """Sorted (AS, metro) of the PeeringDB facilities and IXPs of the CDNs
    in present."""
    return sorted({(asn, m) for asn in CDN_AS if asn in present
                   for m in set(as_fac.get(asn, {})) | as_ix.get(asn, set())})


def sites_by_as(gaz, as_fac, as_ix, present):
    """AS -> set of candidate site metros (cloud regions and CDN sites)."""
    out = {}
    for prov, m in cloud_sites(gaz, present):
        out.setdefault(CLOUD_AS[prov], set()).add(m)
    for asn, m in cdn_sites(as_fac, as_ix, present):
        out.setdefault(asn, set()).add(m)
    return out

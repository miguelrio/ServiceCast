#!/usr/bin/env python3
"""Line-based reader for the generated CAIDA topology GMLs.

parse_gml() returns the file's lines plus its nodes, edges and the line range
of each node block, so a script can rewrite a GML in place (place_servers.py
uses it). graph_attrs() returns the graph-level attributes, such as the
observedCones sidecar file. Moved here from scripts/add_routing_tables_valley_free.py
(now scripts/topologies/add_routing_tables_valley_free.py).
"""
import bz2
import os
import re


def parse_gml(path):
    """Single-pass line parser tailored to this GML's `key value` / `key "value"`
    style. Returns (nodes, edges, node_line_ranges) where node_line_ranges maps
    node id -> (start_line_idx, end_line_idx) of its block in the raw file,
    for later in-place attribute insertion."""
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    nodes = {}  # id -> dict of attrs
    edges = []  # list of dicts: source, target, type, delayMs
    node_blocks = {}  # id -> (start_idx, end_idx) inclusive, end_idx is the line with the closing ']'

    i = 0
    n = len(lines)
    kv_re = re.compile(r'^\s*(\w+)\s+(.+?)\s*$')

    while i < n:
        stripped = lines[i].strip()
        if stripped == "node [":
            start = i
            attrs = {}
            j = i + 1
            depth = 1
            while j < n:
                s = lines[j].strip()
                if s.endswith("["):
                    depth += 1
                elif s == "]":
                    depth -= 1
                    if depth == 0:
                        break
                else:
                    m = kv_re.match(lines[j])
                    if m:
                        key, val = m.group(1), m.group(2)
                        attrs[key] = _coerce(val)
                j += 1
            end = j
            node_id = attrs.get("id")
            nodes[node_id] = attrs
            node_blocks[node_id] = (start, end)
            i = end + 1
            continue
        elif stripped == "edge [":
            j = i + 1
            depth = 1
            attrs = {}
            while j < n:
                s = lines[j].strip()
                if s.endswith("["):
                    depth += 1
                elif s == "]":
                    depth -= 1
                    if depth == 0:
                        break
                else:
                    m = kv_re.match(lines[j])
                    if m:
                        key, val = m.group(1), m.group(2)
                        attrs[key] = _coerce(val)
                j += 1
            edges.append(attrs)
            i = j + 1
            continue
        else:
            i += 1

    return lines, nodes, edges, node_blocks


def graph_attrs(lines):
    """Graph-level `key value` attributes written before the first node, as
    the topology scripts write them, excluding `directed`."""
    attrs = {}
    kv_re = re.compile(r'^\s*(\w+)\s+(.+?)\s*$')
    depth = 0
    for line in lines:
        s = line.strip()
        if s == "node [" or s == "edge [":
            break
        if s.endswith("["):
            depth += 1
        elif depth == 1:
            m = kv_re.match(line)
            if m and m.group(1) != "directed":
                attrs[m.group(1)] = _coerce(m.group(2))
    return attrs


def observed_cones_path(gml_path, attrs):
    """Absolute path of the observed-cone sidecar a GML names, or None."""
    name = attrs.get("observedCones")
    if not name:
        return None
    return os.path.join(os.path.dirname(os.path.abspath(gml_path)), name)


def read_cones(path):
    """Sidecar or CAIDA ppdc-ases file -> {asn: set of the other ASes in its
    observed customer cone}."""
    cones = {}
    opener = bz2.open if path.endswith(".bz2") else open
    with opener(path, "rt") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            asn, *members = line.split()
            cones[asn] = set(members) - {asn}
    return cones


def _coerce(raw):
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    try:
        if "." in raw or "e" in raw.lower():
            return float(raw)
        return int(raw)
    except ValueError:
        return raw

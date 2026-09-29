#!/usr/bin/env python3
"""Remove client<->server 'demand' edges from a typed GML topology.

The scenario-explorer generator exports a demand matrix as physical edges
between client and server nodes. Network.from_graph treats every GML edge as
a real link and calls add_neighbour() on both endpoints, but Host nodes
(clients and servers) keep exactly ONE outgoing port, so each extra edge
silently overwrites the previous neighbour. With demand edges present a
server's final neighbour can be a client: ServerMetric announcements get
unicast to that client and consumed, routers never learn a route, and every
request dies as REQUEST_NOT_FORWARDED.

Stripping the demand edges restores singly-attached hosts. The router graph,
access (client-router) and host (server-router) edges are untouched.

Usage: strip_host_demand_edges.py <in.gml> [<in.gml> ...]
Writes <name>_nodemand.gml next to each input and prints an edge census.
"""
import re
import sys
from pathlib import Path

NODE_RE = re.compile(r'^\s*node\s*\[')
EDGE_RE = re.compile(r'^\s*edge\s*\[')
ID_RE = re.compile(r'^\s*id\s+(\d+)')
TYPE_RE = re.compile(r'^\s*type\s+"(\w+)"')
END_RE = re.compile(r'^\s*\]')


def strip_file(path: Path) -> None:
    lines = path.read_text().splitlines(keepends=True)

    # pass 1: node id -> type ("router" / "server" / "client")
    node_type = {}
    in_node = False
    nid = None
    for line in lines:
        if NODE_RE.match(line):
            in_node, nid = True, None
            continue
        if in_node and END_RE.match(line):
            in_node = False
            continue
        if in_node:
            m = ID_RE.match(line)
            if m:
                nid = int(m.group(1))
                continue
            m = TYPE_RE.match(line)
            if m and nid is not None:
                node_type[nid] = m.group(1)

    # pass 2: drop edge blocks whose BOTH endpoints are non-router hosts
    out = []
    census = {}
    in_edge = False
    src = tgt = etype = None
    block = []
    for line in lines:
        if EDGE_RE.match(line):
            in_edge, block = True, [line]
            src = tgt = etype = None
            continue
        if in_edge:
            block.append(line)
            m = re.match(r'^\s*source\s+(\d+)', line)
            if m:
                src = int(m.group(1))
            m = re.match(r'^\s*target\s+(\d+)', line)
            if m:
                tgt = int(m.group(1))
            m = TYPE_RE.match(line)
            if m:
                etype = m.group(1)
            if END_RE.match(line):
                in_edge = False
                t1 = node_type.get(src)
                t2 = node_type.get(tgt)
                both_hosts = t1 in ("client", "server") and t2 in ("client", "server")
                census[etype] = census.get(etype, 0) + 1
                if both_hosts:
                    census[f"{etype}_DROPPED"] = census.get(f"{etype}_DROPPED", 0) + 1
                else:
                    out.extend(block)
            continue
        out.append(line)

    dest = path.with_name(path.stem + "_nodemand.gml")
    dest.write_text("".join(out))
    kept = sum(v for k, v in census.items() if not k.endswith("_DROPPED"))
    dropped = sum(v for k, v in census.items() if k.endswith("_DROPPED"))
    print(f"{path.name} -> {dest.name}: kept {kept}, dropped {dropped} "
          f"({', '.join(f'{k}={v}' for k, v in sorted(census.items()))})")


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        strip_file(Path(arg))

"""Checks for the attachment-link weight rule (team rule 2026-10-22):
a delayMs on the GML edge always wins over default/config/CLI; when the edge
carries none, the per-host default applies (10 ms client, 1 ms server); a
written 0 counts as unspecified (the engine-wide sentinel). Also checks that
UTF-8 node attributes parse (the reader is UTF-8). Run from the repository root:

    PYTHONPATH=src python3 tests/gml_attachment_weight_test.py

Exits 0 when every check passes, 1 otherwise.
"""

import os
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

from Graph import Graph

GML = """graph [
  directed 0
  node [
    id 0
    label "r1"
    Internal 1
    type "router"
    Latitude 48.85
    Longitude 2.35
    city "Montréal"
  ]
  node [
    id 1
    label "s1"
    Internal 0
    type "server"
    Latitude 48.85
    Longitude 2.35
  ]
  node [
    id 2
    label "s2"
    Internal 0
    type "server"
    Latitude 48.85
    Longitude 2.35
  ]
  node [
    id 3
    label "s3"
    Internal 0
    type "server"
    Latitude 48.85
    Longitude 2.35
  ]
  node [
    id 4
    label "c1"
    Internal 0
    type "client"
    Latitude 48.85
    Longitude 2.35
  ]
  node [
    id 5
    label "c2"
    Internal 0
    type "client"
    Latitude 48.85
    Longitude 2.35
  ]
  edge [
    source 0
    target 1
    type "hosts"
    delayMs 0.2
  ]
  edge [
    source 0
    target 2
    type "hosts"
    delayMs 0
  ]
  edge [
    source 0
    target 3
    type "hosts"
  ]
  edge [
    source 0
    target 4
    type "access"
    delayMs 3.5
  ]
  edge [
    source 0
    target 5
    type "access"
  ]
]
"""

failures = []


def check(what, got, want):
    ok = got == want
    print(f"  [{'ok' if ok else 'FAIL'}] {what}: got {got}, want {want}")
    if not ok:
        failures.append(what)


with tempfile.NamedTemporaryFile("w", suffix=".gml", delete=False) as f:
    f.write(GML)
    path = f.name

try:
    graph = Graph.from_gml_file(path)
finally:
    os.unlink(path)

weights = dict(graph.graph[graph._to_index("r1")].as_list())

print("attachment link weights (GML delayMs wins; 0/unset -> 1 ms server, 10 ms client):")
check("hosts with delayMs 0.2 -> 0.2 (GML wins)", weights[graph._to_index("s1")], 0.2)
check("hosts with delayMs 0 -> 1 (0 = unspecified, server default)",
      weights[graph._to_index("s2")], Graph.default_server_attachment_delay_ms)
check("hosts with no delayMs -> 1 (server default)",
      weights[graph._to_index("s3")], Graph.default_server_attachment_delay_ms)
check("access with delayMs 3.5 -> 3.5 (GML wins)", weights[graph._to_index("c1")], 3.5)
check("access with no delayMs -> 10 (client default)",
      weights[graph._to_index("c2")], Graph.default_client_attachment_delay_ms)

print(f"{len(failures)} check(s) failed" if failures else "all checks passed")
sys.exit(1 if failures else 0)

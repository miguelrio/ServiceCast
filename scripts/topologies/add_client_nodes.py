#!/usr/bin/env python3
"""
Add client nodes to a GML: one client on each of the N routers with the
largest clientCount (the tags written by add_clients.py).

Each client is a node of type "client" joined to its router by an access
link (delayMs, default 10 ms). Clients are named client_00001, client_00002,
... in order of decreasing clientCount, and their ids continue from the
largest id in the file. Each client also carries its router's clientCount,
for a client generator that weights requests by population; the current
simulator gives every client the same weight.

Everything else in the input is copied unchanged, so this works on large
files (the input is streamed, not loaded). The file must end with the
graph's closing "]" on its own line, as the topology scripts write it.

If fewer than N routers carry a clientCount, all of them get a client and a
warning is printed. A list of the clients and their routers goes to stdout.

Usage:
  python3 add_client_nodes.py caida_servers_1000_clients.gml caida_servers_1000_c5000.gml 5000
  python3 add_client_nodes.py IN.gml OUT.gml N --delay-ms 10
"""
import argparse
import sys

import provenance


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="GML whose routers carry clientCount")
    ap.add_argument("output", help="GML to write")
    ap.add_argument("n", type=int, help="number of clients to add")
    ap.add_argument("--delay-ms", type=float, default=10.0,
                    help="access link delay in ms (default 10)")
    args = ap.parse_args()
    provenance.options(args)

    candidates = []  # (clientCount, router id, router label)
    max_id = -1
    node = None
    last = None
    provenance.use(args.input, "topology")
    step = provenance.StepInserter(provenance.step_text(__file__, provenance.DEFAULT_DATA_DIR))
    with open(args.input, encoding="utf-8", errors="surrogateescape") as fin, \
         open(args.output, "w", encoding="utf-8", errors="surrogateescape") as fout:
        # copy every line except the last (the graph's closing "]"), which is
        # written after the new nodes
        for line in fin:
            if last is not None:
                fout.write(last)
            fout.write(step.before(line))
            last = line
            s = line.strip()
            if s == "node [":
                node = {}
            elif s == "]" and node is not None:
                max_id = max(max_id, int(node.get("id", -1)))
                if "clientCount" in node and node.get("type") == '"router"':
                    candidates.append((float(node["clientCount"]), int(node["id"]),
                                       node["label"].strip('"')))
                node = None
            elif node is not None:
                key, _, value = s.partition(" ")
                if key in ("id", "label", "clientCount", "type"):
                    node[key] = value
        if last is None or last.strip() != "]":
            sys.exit(f"{args.input}: does not end with the graph's closing ']'")
        if not candidates:
            sys.exit(f"{args.input}: no routers carry a clientCount (run add_clients.py first)")
        if len(candidates) < args.n:
            print(f"warning: only {len(candidates)} routers carry a clientCount; "
                  f"adding {len(candidates)} clients, not {args.n}", file=sys.stderr)

        # largest clientCount first; ties by router id, so the output is repeatable
        chosen = sorted(candidates, key=lambda c: (-c[0], c[1]))[:args.n]
        width = max(5, len(str(len(chosen))))
        for i, (count, rid, label) in enumerate(chosen, start=1):
            cid = max_id + i
            name = f"client_{i:0{width}d}"
            fout.write(f'  node [\n    id {cid}\n    label "{name}"\n    Internal 0\n'
                       f'    type "client"\n    clientCount {count:g}\n  ]\n')
            fout.write(f'  edge [\n    source {cid}\n    target {rid}\n    type "access"\n'
                       f'    delayMs {args.delay_ms:g}\n  ]\n')
            print(f"{name} on {label} (clientCount {count:g})")
        fout.write(last)


if __name__ == "__main__":
    main()

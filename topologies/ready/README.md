# Simulator-ready topologies

`experiments/main.py` runs the GML files in this folder. A file belongs
here when the topology scripts have finished with it:

- servers placed (`scripts/topologies/place_servers.py`, which is to mark
  the file `simulatorReady 1` in its graph attributes; not done yet), and
  clients placed
  (`scripts/topologies/add_client_nodes.py`); a run with `CLIENTS = 0` needs
  no clients;
- a `provenance [ ... ]` block recording every script that made it
  (`scripts/topologies/provenance.py`);
- its sidecar file (for CAIDA topologies, the observed customer cones
  `<name>.cones.txt` named by the graph attribute `observedCones`) beside
  it, with the checksum its provenance recorded.

Keep each GML and its sidecar here side by side with their original names:
the GML names the sidecar relative to its own folder. In configs, refer to
these files relative to the repository root, e.g.
`GML_FILE = "topologies/ready/dfn_s5_c5.gml"`.

`main.py` checks these before a run. Until the topologies in use are
rebuilt with the `simulatorReady` mark, a file without provenance, without
the mark, or outside this folder gets a warning; these will become errors.

CAIDA-derived files are not committed (data licences and file size; see
`scripts/topologies/data/README.md`): they are ignored by `.gitignore` here
and shared privately. One small example, `caida_1k_s100_c100.gml`
(1000 ASes, 100 servers, 100 clients) with its sidecar
`caida_1k.cones.txt`, is shared within the team: put both files here and
`configs/caida_1k_s100_c100.py` runs it without building anything.
Small topologies built from Topology Zoo files can be committed.

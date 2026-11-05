# Intermediate topology files

A working folder for the topology scripts (`scripts/topologies/`): the
base network, subsets and the files between placement steps. Nothing here
is committed (see `.gitignore`); CAIDA files are large and derived from
data that is shared privately.

When a topology is finished (servers and clients placed), copy the GML and
its sidecar file into `topologies/ready/`. See `doc/Workflow.md`.

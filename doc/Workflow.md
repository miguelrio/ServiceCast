# Workflow: from a topology to results

How a simulation run is made, in four steps:

```
 topology source        topology scripts            config file         experiments/main.py        log (stdout)
 (CAIDA data,     -->   build, place servers,  -->  NAME = value   -->  checks, runs,       -->   header + events
  Topology Zoo)         place clients, provenance   lines               prints DONE                 -> analysis scripts
                        -> topologies/ready/
```

1. **Topology:** make a simulator-ready GML in `topologies/ready/`.
2. **Config:** write a config file naming the GML and the settings that
   differ from the defaults.
3. **Run:** `python3 experiments/main.py CONFIG [--set NAME=VALUE ...]`,
   redirecting stdout to a log file.
4. **Analyse:** read the log with the scripts in `scripts/`.

All times, in topology files, configs, the command line and logs, are in
milliseconds.

## 1. Topology

A GML is **simulator-ready** when the topology scripts have finished with
it:

- servers are placed, and the file is marked `simulatorReady 1` in its
  graph attributes;
- clients are placed (not needed for a run with `CLIENTS = 0`);
- it has a `provenance [ ... ]` block: each script that worked on it, its
  options, and the input files with their checksums
  (`scripts/topologies/provenance.py`);
- its sidecar file, if it names one, sits beside it.

These files live in `topologies/ready/` (see its README).
`experiments/main.py` checks all of this before a run.

**Status (Nov 2026):** `place_servers.py` does not write
`simulatorReady 1` yet, and the topologies built before provenance existed
have none, so for now `main.py` only **warns** about a file without
provenance, without the mark, or outside `topologies/ready/`. These will
become errors once the topologies in use are rebuilt.

### CAIDA topologies

The scripts are in `scripts/topologies/` (see its `README.md` and
`MANUAL.md`). `fetch_location_data.sh` downloads the input data, once per
CAIDA snapshot: the as-rel file into `scripts/topologies/` and the rest
into `scripts/topologies/data/`, where the scripts look for it.

Run from the repository root, like every command in this document. The
intermediate files go in `topologies/build/`, a git-ignored folder (the
full CAIDA network alone is about 80 MB):

```bash
S=scripts/topologies
B=topologies/build
python3 $S/build_caida_topology.py $S/20260801.as-rel.txt -o $B/caida_real.gml
python3 $S/subset_caida_topology.py $B/caida_real.gml -o $B/caida_1k.gml --ases 1000
python3 $S/place_servers.py $B/caida_1k.gml -o $B/caida_1k_servers --servers 100
python3 $S/add_clients.py $B/caida_1k_servers_100.gml -o $B/caida_1k_s100_clients.gml
python3 $S/add_client_nodes.py $B/caida_1k_s100_clients.gml $B/caida_1k_s100_c100.gml 100
cp $B/caida_1k_s100_c100.gml $B/caida_1k.cones.txt topologies/ready/
```

Then run it with the committed example config:

```bash
python3 experiments/main.py configs/caida_1k_s100_c100.py --set UNTIL=50000 > logs/caida_1k.log
```

In order: routers and links (`caida_real.gml` and its sidecar
`caida_real.cones.txt`, about 40 s); optionally a smaller network of 1000
ASes, with its own sidecar; 100 servers; client counts on routers; 100
client nodes on the routers with the most users. `place_servers.py -o`
takes a prefix and adds the server count, so `-o $B/caida_1k_servers
--servers 100` writes `caida_1k_servers_100.gml`. Skip the subset step to
use the full network, with `caida_real.gml` as the input to
`place_servers.py` and `caida_real.cones.txt` as the sidecar to copy.

The last line copies the finished GML **and its sidecar** into
`topologies/ready/`. The graph attribute `observedCones` names the sidecar
relative to the GML, so the two files must stay together. CAIDA-derived
files are not committed (data licences and file size): they are shared
privately, and their provenance lets anyone check they have the same
files. One small example, `caida_1k_s100_c100.gml` with its sidecar
`caida_1k.cones.txt`, is shared within the team: put both in
`topologies/ready/` and `configs/caida_1k_s100_c100.py` runs it without
building anything.

### Topology Zoo topologies

The Topology Zoo GMLs are in `topologies/gml/`. One script converts a zoo
network and places servers and clients:

```bash
python3 scripts/topologies/make_zoo_gml.py topologies/gml/Dfn.gml topologies/ready/dfn_s10_c10.gml 10 10
```

It drops the external nodes, gives each link a delay from its length,
places N servers and N clients on random routers of degree 3 or less
(seeded), and writes the provenance block and `simulatorReady 1`. To run
it, point the DFN example config at it and set the load for 10 servers (see
section 2):

```bash
python3 experiments/main.py configs/dfn_s5_c5.py --set GML_FILE=topologies/ready/dfn_s10_c10.gml --set ARRIVAL_MEAN=2000 > logs/dfn_s10_c10.log
```

You choose the output file names, and the scripts overwrite an existing
file without asking. Put the options that matter in the name, for example
`dfn_s5_c5_seed2.gml` for `--seed 2`; the provenance block records them
all in any case.

**`make_zoo_gml.py` is a placeholder, to be revised soon.** Its delay
rule, its placement rule, and whether it should be split into a
conversion step and a placement step are still to be decided (see the
notes at the top of the script).

## Paths

Run every command from the repository root and write paths relative to it
(`configs/...`, `topologies/ready/...`, `logs/...`); every example here
does.

| Path | Relative to | Notes |
|---|---|---|
| the config file given to `main.py` | the current folder, else the repo root | an absolute path also works |
| `GML_FILE` | the current folder, else the repo root | in configs, write it relative to the repo root (`topologies/ready/...`) |
| the topology's sidecar | the GML's own folder | named by the GML's `observedCones`; keep both files in one folder, with their original names |
| the log (`> logs/x.log`) | the current folder | plain shell redirection |
| paths in the log header | the repo root, always | a file outside the repo shows as `../../...` |
| topology scripts' inputs and outputs | the current folder | CAIDA input data is found in `scripts/topologies/data/` wherever you run from |

Build each topology in one folder (`topologies/build/`) and copy the
finished GML and its sidecar together into `topologies/ready/`. Renaming the
sidecar, or writing a step's output to another folder, can leave the GML
naming a sidecar that is not there (`place_servers.py` adjusts the path when
it writes elsewhere, `add_client_nodes.py` does not); `main.py` then stops
with "names sidecar ..., which is missing".

## 2. Config

A config is a Python file of `NAME = value` lines. Only upper-case names
are settings; lower-case names and imports are allowed as helpers. Each
setting's value comes from, in order:

1. the command line, `--set NAME=VALUE`;
2. the config file;
3. the default in the simulator code.

A config names the topology and whatever differs from the defaults. It can
also list settings that equal their defaults, to be explicit; a value
written in a config stays as written, even if a code default changes
later.

```python
# configs/dfn_s5_c5.py
GML_FILE = "topologies/ready/dfn_s5_c5.gml"
ARRIVAL_MEAN = 4000           # ms between requests: 10% load on 5 servers x 50 slots
SERVER_CF = 0.01
```

`GML_FILE` must be given, in the config or with `--set`. Misspelt names
(with a suggestion of the closest name) and invalid values stop `main.py`
before it runs: every setting has a type and a range, so for example
`yes` for a True/False setting, `0,05`, 0 slots or an alpha of 2 are
refused, as are an unknown routing policy or function name. `--set` values
are read as `true`, `false` or `none` (in any capitalisation), numbers, or
text.

To see every setting, its value and where the value came from:

```bash
python3 experiments/main.py configs/dfn_s5_c5.py --dump-config
```

The output is itself a valid config, with every value fixed.

**Choosing `ARRIVAL_MEAN` for a target load.** Requests arrive as one
Poisson process over all clients, one every `ARRIVAL_MEAN` ms on average,
and each holds a server slot for `SESSION_MEAN` x `SESSION_SCALE` ms on
average (100 s by default). The offered load is therefore

```
load = SESSION_MEAN * SESSION_SCALE / (ARRIVAL_MEAN * SERVER_SLOTS * number of servers)
```

For example, 1000 servers of 50 slots at 10% load need
`ARRIVAL_MEAN = 100000 / (0.1 * 50 * 1000) = 20` ms.

## 3. Run

From the repository root:

```bash
python3 experiments/main.py configs/dfn_s5_c5.py > logs/dfn_s5_c5.log
python3 experiments/main.py configs/dfn_s5_c5.py --set SERVER_CF=0.05 --set UNTIL=200000 > logs/dfn_s5_c5_cf005.log
```

- The log goes to stdout; redirect it where you want it. `logs/` is there
  for this and nothing in it is committed. `main.py` writes no files
  itself, so casual runs leave nothing behind.
- Before the run starts, the log gives the offered load (see section 2),
  and a warning goes to stderr if it is above 100%.
- Warnings and progress messages go to stderr.
- `main.py` always uses its own checkout's `src/` and `scripts/`, whatever
  `PYTHONPATH` says.
- The default log level is `VERBOSE_LEVEL = -1` (per-request metrics and
  end-of-run summaries). Use 0 or above only to debug the protocol on small
  networks; see `Logging.md`.
- The last line of the log is `DONE` only if the run completed. A log
  without it is from a run that crashed, was killed, or is still running.

To repeat a run made with the older `experiments/main_precomputed_t1.py`,
start from `configs/precomputed_t1.py`, which holds that script's values
(the code defaults now differ), and give its arguments and environment
variables with `--set`, in ms:

```bash
python3 experiments/main.py configs/precomputed_t1.py --set GML_FILE=topologies/ready/x.gml --set UNTIL=200000 --set VERBOSE_LEVEL=-1 --set ARRIVAL_MEAN=20
```

An old variable name (`TAU`, `NOCLIENTS`, `TREE_CHILDREN_ONLY`, ...) given
to `--set` gets an error naming the setting that replaced it.

A sweep is a loop of such runs, each a separate process:

```bash
for cf in 0.001 0.01 0.05; do
  python3 experiments/main.py configs/caida_1k_s100_c100.py --set SERVER_CF=$cf > logs/caida_1k_cf$cf.log
done
```

`experiments/sweep_simple.py` is the same loop in Python, over two settings
(server change factor x FIB update threshold on the DFN example): copy it
as a starting point for other sweeps.

For the change-factor matrix, `experiments/sweep.py` adds log parsing and the
existing matrix JSON output. Its definition names a normal base config, fixed
command-line overrides, and the threshold axes:

```bash
python3 experiments/sweep.py experiments/sweeps/dfn_thresholds.py --jobs 3
```

Each cell is a separate `main.py` process. The driver requires a zero exit status
and a final `DONE`, keeps the logs, writes `manifest.json`, and prints the matrix
JSON path on stdout. The selected log metrics require `VERBOSE_LEVEL = 1`.

## 4. The log and analysis

The log starts with a header:

```
Simulation parameters:
    command_line = experiments/main.py configs/dfn_s5_c5.py --set SERVER_CF=0.05
    config_file = 'configs/dfn_s5_c5.py'
    git_commit = '8e3e9f7+dirty'
    gml_sha256 = '64a05978d76d13b0'
    time_unit = 'ms'
    # Settings in config form: every value is fixed here, defaults included.
    GML_FILE = 'topologies/ready/dfn_s5_c5.gml'   # config
    UNTIL = 500000                                # default
    SERVER_CF = 0.05                              # command line
    ...
```

It records how the run was started, the code version (`+dirty` means
uncommitted changes), checksums of the topology and its sidecar, and every
setting with where its value came from. The settings block, from the
`# Settings in config form` line down, is the same as `--dump-config`
prints: copy those lines (without the indentation) into a config file to
repeat the run. The lines above it describe the run and are not config
lines.

Scripts that read logs (all in `scripts/`):

| Script | Gives |
|---|---|
| `quick_stats.py LOG` | accuracy, utility gaps, update messages, FIB stability |
| `window_stats.py LOG` | the same measures in time windows, to check settling |
| `plot_load.py LOG` | server load over time, and its distribution |

They read logs from `main.py` and older logs, and print a note when a
`main.py` log has no final `DONE` line.

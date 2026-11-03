"""Provenance of the generated GMLs: which input files, code and options
made them.

Each topology script calls use() for every input file it reads and then
writes a `provenance [ ... ]` block into its GML's graph attributes, after
the plain attributes and before the first node. The block holds one `step`
per script that worked on the file; a script that starts from another
script's GML copies the earlier steps and adds its own. Each step records:

  script, code (git describe --always --dirty of the repo), command,
  python, numpy, built (UTC time), then per input file its role, file
  name, sha256, bytes, dataset date (from the file name, or "latest"),
  URL and download date (from data/SOURCES.tsv, which
  fetch_location_data.sh writes), and for the RIR files the end date of
  their records; then optional inputs the run did not have (`absent`),
  the files written beside the GML (e.g. the cones sidecar) with their
  sha256, and a few summary counts.

The input data files themselves are not in the repo (see data/README.md):
the hashes let a person with copies check they have the same files:

    python3 provenance.py check caida_real.gml [--data-dir data]

The `built` time and `code` fields differ between rebuilds of the same
topology; compare two builds with `python3 provenance.py strip`.
"""
import argparse
import hashlib
import os
import platform
import re
import shlex
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATA_DIR = os.path.join(HERE, "data")
MANIFEST = "SOURCES.tsv"  # file<TAB>url<TAB>fetched (UTC date)<TAB>how

_used = {}  # abspath -> role, in the order first used
_absent = {}  # role -> note, for optional inputs this run did not have


def use(path, role):
    """Note that this run read `path` (kept for the provenance block)."""
    p = os.path.abspath(path)
    _used.setdefault(p, role)
    return path


def absent(role, note):
    """Note that an optional input was not there (the GML differs without it)."""
    _absent.setdefault(role, note)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_describe():
    try:
        out = subprocess.run(["git", "-C", HERE, "describe", "--always", "--dirty", "--abbrev=12"],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _manifest(data_dir):
    """{file name: (url, fetched, how)} from data/SOURCES.tsv (last entry wins)."""
    entries = {}
    path = os.path.join(data_dir, MANIFEST)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("#") or not line.strip():
                    continue
                c = line.rstrip("\n").split("\t")
                if len(c) >= 3:
                    entries[c[0]] = (c[1], c[2], c[3] if len(c) > 3 else "")
    return entries


def _dataset_date(name):
    """Dataset date from a file name: 20260801, 2026_08_01, 2026-10; else
    "latest" for files that are only published for the current period."""
    m = re.search(r"(\d{4})[_-](\d{2})[_-](\d{2})", name) or re.search(r"(?<!\d)(\d{8})(?!\d)", name) \
        or re.search(r"(\d{4})-(\d{2})(?!\d)", name)
    if m:
        return m.group(0)
    return "latest" if ("latest" in name or name.endswith(".html")) else ""


def _rir_date(path):
    """End date of the records in an RIR delegated file, from its version
    line (version|registry|serial|records|startdate|enddate|UTCoffset)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line[:1].isdigit():
                    c = line.split("|")
                    return c[5] if len(c) > 5 else ""
    except OSError:
        pass
    return ""


def _command(argv):
    """The command line, with file and folder paths cut to their last part
    (so the GML does not carry anyone's home folder)."""
    words = [os.path.basename(argv[0])]
    for a in argv[1:]:
        words.append(os.path.basename(a.rstrip(os.sep)) if os.sep in a else a)
    return shlex.join(words)


def _q(v):
    return '"' + str(v).replace("&", "&amp;").replace('"', "&quot;") + '"'


def step_lines(script, data_dir, outputs=(), summary=None, argv=None):
    """GML lines (indented for the provenance block) for this run's step."""
    import numpy
    manifest = _manifest(data_dir)
    argv = sys.argv if argv is None else argv
    out = ["    step [",
           f"      script {_q(os.path.basename(script))}",
           f"      code {_q(_git_describe())}",
           f"      command {_q(_command(argv))}",
           f"      python {_q(platform.python_version())}",
           f"      numpy {_q(numpy.__version__)}",
           f"      built {_q(time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))}"]
    for p, role in _used.items():
        name = os.path.basename(p)
        out += ["      input [", f"        role {_q(role)}", f"        file {_q(name)}",
                f"        sha256 {_q(sha256(p))}", f"        bytes {os.path.getsize(p)}"]
        date = _dataset_date(name)
        if date:
            out.append(f"        dataset {_q(date)}")
        if name.startswith("delegated-"):
            out.append(f"        published {_q(_rir_date(p))}")
        if name in manifest:
            url, fetched, how = manifest[name]
            out += [f"        url {_q(url)}", f"        fetched {_q(fetched)}"]
            if how:
                out.append(f"        fetchedFrom {_q(how)}")
        out.append("      ]")
    for role, note in _absent.items():
        out += ["      absent [", f"        role {_q(role)}", f"        note {_q(note)}", "      ]"]
    for p in outputs:
        out += ["      output [", f"        file {_q(os.path.basename(p))}",
                f"        sha256 {_q(sha256(p))}", "      ]"]
    if summary:
        out.append("      summary [")
        out += [f"        {k} {v}" for k, v in summary.items()]
        out.append("      ]")
    out.append("    ]")
    return out


def earlier_steps(lines):
    """The step lines of the provenance block of a GML read with
    gml_lines.parse_gml (its `lines`), to copy into a derived GML."""
    start = None
    depth = 0
    for i, line in enumerate(lines):
        s = line.strip()
        if s in ("node [", "edge ["):
            return []
        if start is None:
            if s == "provenance [":
                start, depth = i, 1
            continue
        if s.endswith("["):
            depth += 1
        elif s == "]":
            depth -= 1
            if depth == 0:
                return [l.rstrip("\n") for l in lines[start + 1:i]]
    return []


def block(script, data_dir, prior_lines=(), outputs=(), summary=None):
    """The whole provenance block: earlier steps, then this run's."""
    return "\n".join(["  provenance ["] + list(prior_lines)
                     + step_lines(script, data_dir, outputs, summary) + ["  ]"]) + "\n"


class StepInserter:
    """For scripts that copy a GML line by line: before(line) returns the
    text to write before that line, so that `step` (this run's step lines,
    joined) goes at the end of the input's provenance block, or in a new
    block before the first node if the input has none."""

    def __init__(self, step):
        self.step = step
        self.state = "header"
        self.depth = 0

    def before(self, line):
        s = line.strip()
        if self.state == "header":
            if s == "provenance [":
                self.state, self.depth = "block", 1
            elif s in ("node [", "edge ["):
                self.state = "done"
                return "  provenance [\n" + self.step + "  ]\n"
        elif self.state == "block":
            if s.endswith("["):
                self.depth += 1
            elif s == "]":
                self.depth -= 1
                if self.depth == 0:
                    self.state = "done"
                    return self.step
        return ""


def step_text(script, data_dir, outputs=(), summary=None):
    return "\n".join(step_lines(script, data_dir, outputs, summary)) + "\n"


# --- command line: check a GML's inputs against local copies, or strip
# --- the provenance block for comparing two builds.

def _read_header(path):
    lines = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.strip() in ("node [", "edge ["):
                break
            lines.append(line)
    return lines


def check(gml, data_dir):
    """Compare the inputs a GML records with the files in data_dir, this
    folder and the GML's folder. Returns the number of problems."""
    want = []
    cur = None  # fields of the input [ ] being read
    for line in earlier_steps(_read_header(gml)):
        s = line.strip()
        if s == "input [":
            cur = {}
        elif cur is not None and s == "]":
            want.append(cur)
            cur = None
        elif cur is not None:
            m = re.match(r'(\w+)\s+"(.*)"$', s)
            if m:
                cur[m.group(1)] = m.group(2)
    if not want:
        print(f"{gml}: no provenance block")
        return 1
    dirs = [data_dir, os.path.join(data_dir, "caida_ppdc"), os.path.join(data_dir, "as2org"),
            HERE, os.path.dirname(os.path.abspath(gml))]
    bad = 0
    seen = set()
    for w in want:
        if (w["file"], w["sha256"]) in seen:
            continue
        seen.add((w["file"], w["sha256"]))
        found = [os.path.join(d, w["file"]) for d in dirs if os.path.exists(os.path.join(d, w["file"]))]
        if not found:
            print(f"MISSING  {w['role']:12} {w['file']}  ({w.get('url', 'no url recorded')})")
            bad += 1
        elif sha256(found[0]) != w["sha256"]:
            print(f"DIFFERS  {w['role']:12} {found[0]}")
            bad += 1
        else:
            print(f"ok       {w['role']:12} {w['file']}")
    return bad


def strip(path, out):
    """Copy a GML without its provenance block (to compare two builds)."""
    depth = None
    for line in open(path, encoding="utf-8", errors="surrogateescape"):
        s = line.strip()
        if depth is None and s == "provenance [":
            depth = 1
            continue
        if depth:
            depth += s.endswith("[") - (s == "]")
            continue
        out.write(line)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="check that local input files match the hashes a GML records")
    c.add_argument("gml")
    c.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    s = sub.add_parser("strip", help="write a GML without its provenance block to stdout")
    s.add_argument("gml")
    args = ap.parse_args()
    if args.cmd == "check":
        sys.exit(1 if check(args.gml, args.data_dir) else 0)
    strip(args.gml, sys.stdout)


if __name__ == "__main__":
    main()

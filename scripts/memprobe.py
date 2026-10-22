#!/usr/bin/env python3
"""Run a command, timestamp its output, and record its memory use over time.

Usage: python3 scripts/memprobe.py <out_prefix> -- <command> [args...]

Writes two files:

  <out_prefix>.log      the child's stdout+stderr, each line prefixed with its
                        elapsed wall seconds, so phases in the output can be
                        lined up with the memory curve
  <out_prefix>.rss.csv  one row per second: elapsed_s,rss_mb,vsz_mb,hwm_mb
                        (hwm is the kernel high-water mark from Linux /proc,
                        so peaks between samples are not lost; it is empty
                        where /proc is unavailable, e.g. macOS)

The child's output is also passed through to this process's stdout.  Memory
is sampled from /proc/<pid>/status, falling back to ps.  The exit code is the
child's (128+N when the child dies to signal N, 127 if the command is not
found).  Standard library only.

Example -- a 10 s 0-client run with the memory curve alongside:

    NOCLIENTS=1 PYTHONPATH=src python3 scripts/memprobe.py tmp/run1000 -- \
        python3 -u experiments/main_precomputed_t1.py \
        topologies/caida_servers_1000_RT.gml 10 -1
"""
import os
import subprocess
import sys
import threading
import time


def sample_rss_kb(pid):
    """Return (rss_kb, vsz_kb, hwm_kb_or_empty) for pid."""
    try:
        with open("/proc/%d/status" % pid) as f:
            fields = {}
            for line in f:
                if ":" in line:
                    key, value = line.split(":", 1)
                    # a key with an empty value (e.g. "Groups:" with no
                    # supplementary groups) has no token to take
                    tokens = value.split()
                    if tokens:
                        fields[key] = tokens[0]
        return (int(fields.get("VmRSS", 0)), int(fields.get("VmSize", 0)),
                fields.get("VmHWM", ""))
    except (OSError, ValueError):
        pass
    # no /proc (e.g. macOS): ps reports rss/vsz in kB, but no high-water mark
    try:
        out = subprocess.run(["ps", "-o", "rss=,vsz=", "-p", str(pid)],
                             capture_output=True, text=True, timeout=5).stdout.split()
        if len(out) >= 2:
            return (int(out[0]), int(out[1]), "")
    except Exception:
        pass
    return (0, 0, "")


def main():
    if ("--" not in sys.argv or sys.argv.index("--") < 2
            or sys.argv.index("--") >= len(sys.argv) - 1):
        sys.stderr.write(
            "usage: memprobe.py <out_prefix> -- <command> [args...]\n")
        sys.exit(2)
    split = sys.argv.index("--")
    prefix = sys.argv[1]
    cmd = sys.argv[split + 1:]

    out_dir = os.path.dirname(prefix)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    t0 = time.perf_counter()
    log_f = open(prefix + ".log", "w", buffering=1)
    csv_f = open(prefix + ".rss.csv", "w", buffering=1)
    csv_f.write("elapsed_s,rss_mb,vsz_mb,hwm_mb\n")

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True,
                                errors="replace")
    except FileNotFoundError:
        sys.stderr.write("memprobe: command not found: %s\n" % cmd[0])
        sys.exit(127)

    def pump():
        # keep draining the pipe even when the pass-through stdout breaks
        # (e.g. memprobe's output piped into head), or the child would block;
        # then point fd 1 at /dev/null so the shutdown flush cannot fail and
        # replace the child's exit code with 120
        for line in proc.stdout:
            stamp = "[%9.1fs] " % (time.perf_counter() - t0)
            try:
                log_f.write(stamp + line)
            except OSError:
                pass
            try:
                sys.stdout.write(stamp + line)
                sys.stdout.flush()
            except (BrokenPipeError, OSError):
                try:
                    devnull = os.open(os.devnull, os.O_WRONLY)
                    os.dup2(devnull, sys.stdout.fileno())
                    os.close(devnull)
                except OSError:
                    pass

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()

    peak = 0
    peak_hwm = 0
    while proc.poll() is None:
        rss, vsz, hwm = sample_rss_kb(proc.pid)
        if rss:
            peak = max(peak, rss)
            if hwm:
                peak_hwm = max(peak_hwm, int(hwm))
            csv_f.write("%.1f,%.1f,%.1f,%s\n" % (
                time.perf_counter() - t0, rss / 1024, vsz / 1024,
                int(hwm) / 1024 if hwm else ""))
        time.sleep(1.0)

    reader.join(timeout=5)
    # the child is reaped here: /proc/<pid> is gone, so nothing can be sampled
    # any more -- the summary reports what the loop saw.  VmHWM is monotonic,
    # so the tracked maximum is the kernel's peak over the run.
    summary = "memprobe: rc=%d, wall %.1f s" % (proc.returncode,
                                                time.perf_counter() - t0)
    if peak:
        summary += ", peak sampled RSS %.1f MB" % (peak / 1024)
    if peak_hwm:
        summary += ", kernel hwm %.1f MB" % (peak_hwm / 1024)
    print(summary)
    log_f.close()
    csv_f.close()
    rc = proc.returncode
    # shell convention: a child killed by signal N exits 128+N
    sys.exit(rc if rc >= 0 else 128 - rc)


if __name__ == "__main__":
    main()

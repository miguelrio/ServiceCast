#!/usr/bin/env python3
"""Compare two ServiceCast simulation logs (TinyDB vs dict Router backends).

The dict backend intentionally changed how RIB/sent-table entries are
identified in debug output: TinyDB's integer ``doc_id`` was replaced by the
replica name, and the per-neighbour ``SENT_TABLE`` rows are now grouped into
one line per replica. This script verifies that the *behaviour* of the two
runs is identical while ignoring those deliberate format changes.

Checks performed
----------------
1. Event-tag counts for every ``<time>: ROUTER  TAG`` style line.
2. Ordered sequences of canonicalised behavioural events, compared with an
   alignment (difflib) that reports the first divergence:
     - RECV_PACKET / PACKET_CONSUME / FORWARD_METRIC / WITHDRAW_FORWARD /
       WITHDRAW_PACKET (canonicalised to  time | router | TAG | replica.msgID)
     - ADD_METRIC / UPDATE_METRIC / MARK_METRIC / METRIC_TOO_OLD /
       REMOVE_METRIC  (time | router | TAG | replica)
     - CHOOSE_BEST_REPLICA decision lines (kept verbatim -- they contain
       utilities, thresholds and keep/change decisions)
     - SET_/CHANGED_/KEEP_/REMOVED_ BEST_REPLICA lines (kept verbatim)
     - SERVICE_FIB update_count lines (kept verbatim)
     - REQUEST_FORWARD-style client forwarding lines, if present
       (any tag containing FORWARD or REQUEST that is not FORWARD_METRIC /
       WITHDRAW_FORWARD / CHOOSE_BEST_FORWARDING_REPLICA)

Lines that are pure storage debug output (METRIC_SEARCH_RESULTS, METRIC_TABLE,
SENT_TABLE contents, ANNOUNCE lists, UTILITY tables, FORWARD_METRIC payload
dicts) are excluded from the ordered comparison because their formatting
changed; their *effects* are still covered by the behavioural lines above.

Usage:
    python3 scripts/check-tinydb-dict-logs.py logs/tinydb/old logs/tinydb/new
    python3 scripts/check-tinydb-dict-logs.py old new --max-report 30

Events that differ only in order within one step (one router at one
instant -- e.g. two withdrawals sent in one decision, sent_table insertion
order vs TinyDB's doc_id set order) are reported as ORDER ONLY and treated as
functionally equivalent: each such step must hold the same events (packet
numbers aside, as they follow send order) and every other step must match.

Exit status: 0 if no behavioural differences (identical, or order-only),
1 otherwise.
"""

import argparse
import re
import sys
from collections import Counter
from difflib import SequenceMatcher

# --------------------------------------------------------------------------
# Line classification / canonicalisation
# --------------------------------------------------------------------------

# timestamped simulator line: "12.345: BIE   TAG rest..."
TS_LINE = re.compile(r"^\d+\.\d+:\s+\S+\s+([A-Z][A-Z0-9_]+)")

# drop "time: ROUTER" prefix, collapse whitespace
def strip_head(line):
    m = re.match(r"^(\d+\.\d+):\s+(\S+)\s+(.*)$", line)
    if not m:
        return None, None, None
    return m.group(1), m.group(2), m.group(3)


def canon_msg_packet(line):
    prefix = r"^(\d+\.\d+:\s+\S+\s+)"

    # Packet receive/consume/withdraw lines have a stable source packet
    # number and, for metric packets, a stable replica.msgID bracket.  Keep
    # both: replica.msgID alone is ambiguous when several packets are logged
    # at the same simulation time.
    m = re.match(prefix + r"(RECV_PACKET|PACKET_CONSUME|WITHDRAW_PACKET)\s+(.+)$", line)
    if m:
        head, tag, rest = m.groups()
        source = re.search(r"\b(\S+)\.(\d+)\b", rest)
        bracket = re.search(r"(\[[^\]]+\])", rest)
        if source:
            packet_id = f"{source.group(1)}.{source.group(2)}"
        else:
            packet_id = "<packet>"
        metric_id = bracket.group(1) if bracket else "<no-metric-id>"
        return f"{head}{tag} packet={packet_id} metric={metric_id}"

    # Metric forwarding lines print the metric dictionary.  Its TinyDB
    # document id changes between runs, but destination, replica and msgID
    # identify the behavioural event and are stable across backends.
    m = re.match(prefix + r"(FORWARD_METRIC|WITHDRAW_FORWARD)\s+to\s+(\S+)\s+msg\s+(.*)$", line)
    if m:
        head, tag, destination, rest = m.groups()
        replica = re.search(r"['\"]replica['\"]\s*:\s*['\"]([^'\"]+)['\"]", rest)
        msg_id = re.search(r"['\"]msgID['\"]\s*:\s*['\"]?([^,'\"}\s]+)", rest)
        replica_id = replica.group(1) if replica else "<replica>"
        message_id = msg_id.group(1) if msg_id else "<msgID>"
        return f"{head}{tag} to={destination} replica={replica_id} msgID={message_id}"

    return None


# ADD_METRIC / UPDATE_METRIC / MARK_METRIC: normalise the metric identifier
def canon_metric_line(line):
    # time: router TAG ... -> normalise to the metric identity.
    # The TinyDB log identifies the metric by doc_id ("metric no [3]") and
    # usually does NOT print the replica name on UPDATE_METRIC lines; the
    # dict log prints the replica ("metric s5"). msgID is present in both,
    # so it is the reliable cross-version key for ADD/UPDATE.
    m = re.match(
        r"^(\d+\.\d+:\s+\S+\s+)(ADD_METRIC|UPDATE_METRIC|MARK_METRIC|"
        r"REMOVE_METRIC|METRIC_TOO_OLD)(.*)$", line)
    if not m:
        return None
    head, tag, rest = m.groups()
    mid = re.search(r"msgID:\s*(\d+)", rest)
    if mid:
        return f"{head}{tag} msgID={mid.group(1)}"
    rep = re.search(r"\bs\d+\b", rest)
    return f"{head}{tag} {rep.group(0) if rep else '<id>'}"


VERBATIM_TAGS = (
    "CHOOSE_BEST_REPLICA:",      # decision + utilities + threshold
    "SERVICE_FIB",               # update_count + FIB contents
    "SET_BEST_REPLICA", "CHANGED_BEST_REPLICA", "KEEP_BEST_REPLICA",
    "REMOVED_BEST_REPLICA_FROM_FIB",
)


def classify(line):
    """Return (kind, canonical) or None for lines not compared in order."""
    if not re.match(r"^\d+\.\d+:", line):
        return None

    # 1. canonicalised packet events
    c = canon_msg_packet(line)
    if c:
        return ("event", c)

    # 2. canonicalised metric store events
    c = canon_metric_line(line)
    if c:
        return ("event", c)

    # 3. verbatim behavioural lines
    for tag in VERBATIM_TAGS:
        if tag in line:
            return ("event", line.strip())

    # 4. client-request forwarding (any other FORWARD/REQUEST tag)
    m = TS_LINE.match(line)
    if m:
        tag = m.group(1)
        if (("FORWARD" in tag or "REQUEST" in tag)
                and tag not in ("FORWARD_METRIC", "WITHDRAW_FORWARD",
                                "CHOOSE_BEST_FORWARDING_REPLICA")):
            return ("event", line.strip())

    return None


# table-dump row numbers (" 1. doc_id(...) ...", " 12. replica: ...") -- these
# are verbose table rows, not events; their counts legitimately differ between
# backends because the sent table is grouped per replica in the dict version
TABLE_ROW = re.compile(r"^\s*\d+\.\s")


def tag_of(line):
    m = TS_LINE.match(line)
    if m:
        return m.group(1)
    # table rows and other non-timestamped debug lines carry no event tag
    return None


# --------------------------------------------------------------------------
# Main comparison
# --------------------------------------------------------------------------

def analyse(path):
    tags = Counter()
    events = []
    n_lines = 0
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            n_lines += 1
            line = line.rstrip("\n")
            t = tag_of(line)
            if t:
                tags[t] += 1
            c = classify(line)
            if c:
                events.append(c[1])
    return {"path": path, "lines": n_lines, "tags": tags, "events": events}


def report_tag_counts(a, b, max_report):
    ok = True
    all_tags = sorted(set(a["tags"]) | set(b["tags"]))
    diffs = [(t, a["tags"].get(t, 0), b["tags"].get(t, 0))
             for t in all_tags if a["tags"].get(t, 0) != b["tags"].get(t, 0)]
    print("-" * 72)
    print("EVENT-TAG COUNTS")
    print("-" * 72)
    if not diffs:
        print(f"  all {len(all_tags)} tags have identical counts")
    else:
        print(f"  {len(diffs)} tags differ (of {len(all_tags)}):")
        for t, ca, cb in diffs[:max_report]:
            print(f"    {t:<45} {ca:>10} {cb:>10}")
        # count-only diffs in storage-debug tags are expected
        expected = {"SENT_TABLE"}
        unexpected = [d for d in diffs if d[0] not in expected]
        if unexpected:
            ok = False
    return ok


# "12.345: BIE   rest" -> ("12.345", "BIE"); events are canonical lines, so
# every one starts with its time and router
STEP_HEAD = re.compile(r"^(\d+\.\d+):\s+(\S+)")

# packet numbers are assigned in send order, so when a router sends the same
# packets in a different order their numbers swap; ignore them when asking
# whether two steps hold the same events
PKT_NO = re.compile(r"\bpacket=(\S+?)\.\d+\b")


def group_steps(events):
    """Split the event list into steps: maximal runs of consecutive events
    with the same (time, router). Returns [(key, [events])]."""
    steps = []
    for e in events:
        m = STEP_HEAD.match(e)
        key = (m.group(1), m.group(2)) if m else (None, None)
        if steps and steps[-1][0] == key:
            steps[-1][1].append(e)
        else:
            steps.append((key, [e]))
    return steps


def order_only(ea, eb):
    """True if the two event lists hold the same events step by step, with
    only the order inside some (time, router) steps differing. Returns
    (is_order_only, [(key, old_events, new_events) for reordered steps])."""
    sa, sb = group_steps(ea), group_steps(eb)
    if len(sa) != len(sb):
        return False, []
    reordered = []
    for (ka, la), (kb, lb) in zip(sa, sb):
        if ka != kb:
            return False, []
        if la == lb:
            continue
        if sorted(PKT_NO.sub(r"packet=\1", e) for e in la) != \
                sorted(PKT_NO.sub(r"packet=\1", e) for e in lb):
            return False, []
        reordered.append((ka, la, lb))
    return True, reordered


def report_event_order(a, b, max_report):
    """Returns 'identical', 'order-only' or 'different'."""
    ea, eb = a["events"], b["events"]
    print("-" * 72)
    print("ORDERED BEHAVIOURAL EVENT SEQUENCE")
    print("-" * 72)
    print(f"  events: old={len(ea)} new={len(eb)}")
    if ea == eb:
        print("  identical: ordered canonical event sequences match")
        return "identical"

    same_events, reordered = order_only(ea, eb)
    if same_events:
        print(f"  ORDER ONLY: {len(reordered)} step(s) hold the same events in a "
              "different order")
        print("  (a step = one router at one instant, e.g. two withdrawals "
              "sent in one\n   decision, or their arrival at the neighbour; "
              "packet numbers follow the\n   send order so they swap too)")
        for (t, router), la, lb in reordered[:max_report]:
            print(f"\n  step {t} {router}:")
            for l in la:
                print(f"    old: {l[:160]}")
            for l in lb:
                print(f"    new: {l[:160]}")
        if len(reordered) > max_report:
            print(f"\n  ... {len(reordered) - max_report} more")
        print("\n  Every step holds the same events, and everything after "
              "matches, so the\n  reordering has no functional effect.")
        return "order-only"

    sm = SequenceMatcher(a=ea, b=eb, autojunk=False)
    n_diff_blocks = 0
    shown = 0
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        n_diff_blocks += 1
        if shown < max_report:
            shown += 1
            print(f"\n  [{op}] old[{i1}:{i2}] new[{j1}:{j2}]")
            for l in ea[i1:min(i2, i1 + 3)]:
                print(f"    - {l[:200]}")
            for l in eb[j1:min(j2, j1 + 3)]:
                print(f"    + {l[:200]}")
    print(f"\n  {n_diff_blocks} differing blocks total")
    return "different"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=
                                 argparse.RawDescriptionHelpFormatter)
    ap.add_argument("old", help="log from the TinyDB backend")
    ap.add_argument("new", help="log from the dict backend")
    ap.add_argument("--max-report", type=int, default=20,
                    help="max differences to print per section")
    args = ap.parse_args()

    a = analyse(args.old)
    b = analyse(args.new)

    print("=" * 72)
    print("ServiceCast log comparison (doc_id-insensitive)")
    print("=" * 72)
    print(f"  old: {a['path']}  ({a['lines']:,} lines)")
    print(f"  new: {b['path']}  ({b['lines']:,} lines)")
    print("  note: line-count differences are expected (sent_table debug rows "
          "are\n        grouped per replica in the dict backend)")

    ok_tags = report_tag_counts(a, b, args.max_report)
    order = report_event_order(a, b, args.max_report)
    ok_events = order != "different"

    print("=" * 72)
    if ok_tags and order == "identical":
        print("RESULT: equivalent -- counts and ordered behavioural events match")
        return 0
    if ok_tags and order == "order-only":
        print("RESULT: functionally equivalent -- same events; the order differs "
              "only within\n        simultaneous steps of one router, which "
              "is not functionally important")
        return 0
    print("RESULT: DIFFERENCES FOUND (see sections above)")
    if not ok_tags:
        print("  - tag counts differ beyond expected SENT_TABLE grouping")
    if not ok_events:
        print("  - ordered behavioural event sequences diverge")
    return 1


if __name__ == "__main__":
    sys.exit(main())

"""Parsing helpers for the current ServiceCast log syntax.

This module owns line-level syntax only. Consumers retain their own aggregation
and presentation logic.
"""

from __future__ import annotations

import itertools
import re
from typing import Iterable, Iterator, NamedTuple


_NUM = r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?"
_NOTE = r"(?:\([^)]*\))?"
_TIMESTAMP_LINE_RE = re.compile(rf"^\s*{_NUM}:\s+")
_PARAMETER_RE = re.compile(r"^\s*(?P<key>[^=]+?)\s*=\s*(?P<value>.*?)\s*$")
_HEADER_END_RE = re.compile(r"^\s*size_scale_factor\s*=\s*.+?\s*$")

GAP_KEYWORDS = frozenset({"OUTCOME_GAP", "DECISION_GAP", "STALENESS_ERR"})
FIB_STABILITY_KEYWORDS = frozenset({
    "SET_BEST_REPLICA",
    "KEEP_BEST_REPLICA",
    "CHANGED_BEST_REPLICA",
    "REMOVED_BEST_REPLICA_FROM_FIB",
})
EVENT_KEYWORDS = tuple(sorted(
    GAP_KEYWORDS | FIB_STABILITY_KEYWORDS | {
        "PACKET_CREATED",
        "RECV_PACKET",
        "SERVICE_FIB",
        "REQUEST_NOT_FORWARDED",
    },
    key=len,
    reverse=True,
))
_EVENT_KEYWORD_RE = "|".join(re.escape(keyword) for keyword in EVENT_KEYWORDS)
EVENT_HEADER_RE = re.compile(
    rf"^\s*(?P<timestamp>{_NUM}):\s+"
    rf"(?P<emitter>.+?)\s+(?P<keyword>{_EVENT_KEYWORD_RE})\b"
    rf"(?P<payload>.*)$"
)


class EventHeader(NamedTuple):
    timestamp: float
    emitter: str
    keyword: str
    payload: str


class GapLine(NamedTuple):
    ts: float
    tag: str
    arrival: str
    client: str
    pkt: int
    sel_time: float
    sel_server: str
    sel_load: float
    sel_latency: float
    sel_utility: float
    cmp_label: str
    cmp_time: float
    cmp_server: str
    cmp_load: float
    cmp_latency: float
    cmp_utility: float
    keyword: str
    gap: float
    minload: tuple[float, str, float, float, float] | None


class ServerMetricEvent(NamedTuple):
    kind: str
    operation: str | None


class FibUpdateCount(NamedTuple):
    router: str
    count: int


class FibStabilityAction(NamedTuple):
    router: str
    action: str
    server: str
    neighbour: str | None


class RequestNotForwarded(NamedTuple):
    router: str
    service: str
    packet: int


def _parse_parameter_value(value: str):
    if value == "True":
        return True
    if value == "False":
        return False
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def parse_log_header(
    lines: Iterable[str], filename: str | None = None, *, warn: bool = False
) -> tuple[dict[str, object] | None, Iterator[str]]:
    """Read an optional parameter header and return its values plus body lines.

    The caller sets ``warn`` only for user-supplied files. On an absent or
    malformed header, all consumed input is restored to the returned iterator.
    """
    source = iter(lines)
    consumed: list[str] = []

    for line in source:
        consumed.append(line)
        if line.strip():
            break
    else:
        return None, iter(consumed)

    if line.strip() != "Simulation parameters:":
        if warn and filename:
            print(f"Warning, simulation parameters not present in {filename}")
        return None, itertools.chain(consumed, source)

    parameters: dict[str, object] = {}
    for line in source:
        if _TIMESTAMP_LINE_RE.match(line):
            if warn and filename:
                print(f"Warning, malformed simulation parameters in {filename}")
            return None, itertools.chain(consumed, [line], source)

        consumed.append(line)
        match = _PARAMETER_RE.match(line)
        if match:
            parameters[match.group("key").strip()] = _parse_parameter_value(
                match.group("value")
            )
        if _HEADER_END_RE.match(line):
            return parameters, source

    if warn and filename:
        print(f"Warning, malformed simulation parameters in {filename}")
    return None, iter(consumed)


def parse_event_header(line: str) -> EventHeader | None:
    """Classify a timestamped event from its anchored header."""
    match = EVENT_HEADER_RE.match(line)
    if not match:
        return None
    return EventHeader(
        timestamp=float(match.group("timestamp")),
        emitter=match.group("emitter").strip(),
        keyword=match.group("keyword"),
        payload=match.group("payload").lstrip(),
    )


def _side(prefix: str, label_pattern: str) -> str:
    return (
        rf"(?P<{prefix}_label>{label_pattern}):\s+"
        rf"time{_NOTE}:\s+(?P<{prefix}_time>{_NUM})\s+"
        rf"server{_NOTE}:\s+(?P<{prefix}_server>\S+)\s+"
        rf"load:\s+(?P<{prefix}_load>{_NUM})\s+"
        rf"latency:\s+(?P<{prefix}_latency>{_NUM})\s+"
        rf"utility{_NOTE}:\s+(?P<{prefix}_utility>{_NUM})"
    )


GAP_PAYLOAD_RE = re.compile(
    rf"(?:\([^)]*\)\s+)?"
    rf"'(?P<arrival>[^']+)'\s+\[(?P<client>[^.\]]+)\.(?P<packet>\d+)\]\s+"
    + _side("selected", "SELECTED") + r"\s+"
    + _side("compared", "BEST|ACTUAL") + r"\s+"
    + rf"(?:{_side('minload', 'MINLOAD')}\s+)?"
    + rf"(?P<status>\S+)\s+(?P<gap>{_NUM})\s*$"
)


def parse_gap_line(line: str, header: EventHeader | None = None) -> GapLine | None:
    """Parse one classified per-request gap line."""
    header = header or parse_event_header(line)
    if header is None or header.keyword not in GAP_KEYWORDS:
        return None
    match = GAP_PAYLOAD_RE.match(header.payload)
    if not match:
        return None
    value = match.group
    minload = None
    if value("minload_time") is not None:
        minload = (
            float(value("minload_time")),
            value("minload_server"),
            float(value("minload_load")),
            float(value("minload_latency")),
            float(value("minload_utility")),
        )
    return GapLine(
        ts=header.timestamp,
        tag=header.keyword,
        arrival=value("arrival"),
        client=value("client"),
        pkt=int(value("packet")),
        sel_time=float(value("selected_time")),
        sel_server=value("selected_server"),
        sel_load=float(value("selected_load")),
        sel_latency=float(value("selected_latency")),
        sel_utility=float(value("selected_utility")),
        cmp_label=value("compared_label"),
        cmp_time=float(value("compared_time")),
        cmp_server=value("compared_server"),
        cmp_load=float(value("compared_load")),
        cmp_latency=float(value("compared_latency")),
        cmp_utility=float(value("compared_utility")),
        keyword=value("status"),
        gap=float(value("gap")),
        minload=minload,
    )


def parse_server_metric_event(
    line: str, header: EventHeader | None = None
) -> ServerMetricEvent | None:
    """Parse a ServerMetric creation or reception event after classification."""
    header = header or parse_event_header(line)
    if header is None:
        return None
    if header.keyword == "PACKET_CREATED":
        return ServerMetricEvent("created", None) if re.search(r"\bServerMetric\b", header.payload) else None
    if header.keyword == "RECV_PACKET":
        match = re.match(r"ServerMetric\s+(?P<operation>A|W)\b", header.payload)
        if match:
            return ServerMetricEvent("received", match.group("operation"))
    return None


def parse_not_forwarded_event(
    line: str, header: EventHeader | None = None
) -> RequestNotForwarded | None:
    """Parse a request dropped because the receiving router has no FIB entry."""
    header = header or parse_event_header(line)
    if header is None or header.keyword != "REQUEST_NOT_FORWARDED":
        return None
    match = re.fullmatch(
        r"(?:\[[^\.\]]+\.\d+\]\s+)?"
        r"for service (?P<service>\S+) pkt:\s*(?P<packet>\d+)",
        header.payload,
    )
    if not match:
        return None
    return RequestNotForwarded(
        router=header.emitter,
        service=match.group("service"),
        packet=int(match.group("packet")),
    )


def parse_fib_update_count(
    line: str, header: EventHeader | None = None
) -> FibUpdateCount | None:
    """Parse one SERVICE_FIB update counter line."""
    header = header or parse_event_header(line)
    if header is None or header.keyword != "SERVICE_FIB":
        return None
    match = re.match(r"update_count:\s*(?P<count>\d+)\b", header.payload)
    if not match:
        return None
    return FibUpdateCount(router=header.emitter, count=int(match.group("count")))


def parse_fib_stability_action(
    line: str, header: EventHeader | None = None
) -> FibStabilityAction | None:
    """Parse one FIB stability action, including a removed FIB entry."""
    header = header or parse_event_header(line)
    if header is None or header.keyword not in FIB_STABILITY_KEYWORDS:
        return None
    if header.keyword == "REMOVED_BEST_REPLICA_FROM_FIB":
        match = re.fullmatch(r"(?P<server>\S+)", header.payload)
        if not match:
            return None
        return FibStabilityAction(
            router=header.emitter,
            action=header.keyword,
            server=match.group("server"),
            neighbour=None,
        )
    match = re.match(
        r"(?P<server>\S+)\s+(?:direct|via best neighbour\s+(?P<neighbour>.+?))\s*$",
        header.payload,
    )
    if not match:
        return None
    return FibStabilityAction(
        router=header.emitter,
        action=header.keyword,
        server=match.group("server"),
        neighbour=match.group("neighbour"),
    )
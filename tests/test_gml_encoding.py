# Tests for reading GML files with accented names (Gml.read_gml encodings).
# Run with:  PYTHONPATH=src python3 tests/test_gml_encoding.py
# (also runs under pytest)

import os
import tempfile

from Gml import read_gml
from Verbose import Verbose

Verbose.level = -2

GML = """graph [
  node [
    id 0
    label "a"
    city "São Paulo"
    Latitude -23.55
    Longitude -46.63
  ]
  node [
    id 1
    label "Montréal"
    Latitude 45.5
    Longitude -73.57
  ]
  edge [
    source 0
    target 1
    delayMs 12.5
  ]
]
"""


def read_bytes(data):
    fd, path = tempfile.mkstemp(suffix=".gml")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    try:
        return read_gml(path)
    finally:
        os.remove(path)


def check(graph):
    assert graph.get_node_meta_data("a")["city"] == "São Paulo"
    assert "Montréal" in graph.nodes()
    assert graph.weight("a", "Montréal") == 12.5


def test_utf8_accents():
    check(read_bytes(GML.encode("utf-8")))


def test_utf8_with_byte_order_mark():
    check(read_bytes(b"\xef\xbb\xbf" + GML.encode("utf-8")))


def test_latin1_accents():
    check(read_bytes(GML.encode("latin-1")))


def test_plain_ascii_unchanged():
    graph = read_bytes(GML.replace("São Paulo", "Sao Paulo").replace("Montréal", "Montreal").encode("ascii"))
    assert graph.get_node_meta_data("a")["city"] == "Sao Paulo"
    assert graph.weight("a", "Montreal") == 12.5


def test_html_entities_still_unescaped():
    text = GML.replace("São Paulo", "S&#227;o Paulo").replace("Montréal", "Montr&#233;al")
    graph = read_bytes(text.encode("ascii"))
    assert graph.get_node_meta_data("a")["city"] == "São Paulo"
    assert "Montréal" in graph.nodes()


if __name__ == "__main__":
    failed = []
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", name)
            except AssertionError:
                failed.append(name)
                print("FAIL", name)
    print("{} failed: {}".format(len(failed), failed))

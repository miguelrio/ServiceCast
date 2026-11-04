
# Tests for Graph node and edge lookups (add_edge, contains_edge, ...).
# Run with:  PYTHONPATH=src python3 tests/test_graph_edges.py
# (also runs under pytest)
#
# BASELINE BUG (fixed by the constant-time lookup change in Graph.add_edge):
# add_edge("a", "b") used to create the first AdjNode before converting "b"
# to its index, so a's adjacency list stored the name "b" instead of 1.
# Assertions marked "BASELINE BUG" failed before that change because of it.

from Graph import Graph


def ab_graph():
    graph = Graph()
    graph.add_edge("a", "b", 5)
    return graph


def adjacency_entries(graph, index):
    entries = []
    node = graph.graph[index]
    while node is not None:
        entries.append((node.vertex, node.weight))
        node = node.next
    return entries


def all_vertices(graph):
    return [vertex for i in range(len(graph)) for vertex, _ in adjacency_entries(graph, i)]


# add_edge with names on an empty graph

def test_add_edge_names_creates_nodes():
    graph = ab_graph()
    assert graph.nodes() == ["a", "b"]
    assert graph.contains_node("a") and graph.contains_node("b")
    assert graph.contains_node(0) and graph.contains_node(1)


def test_contains_edge_names_forward():
    # BASELINE BUG
    assert ab_graph().contains_edge("a", "b")


def test_contains_edge_names_reverse():
    assert ab_graph().contains_edge("b", "a")


def test_contains_edge_indexes_forward():
    # BASELINE BUG
    assert ab_graph().contains_edge(0, 1)


def test_contains_edge_indexes_reverse():
    assert ab_graph().contains_edge(1, 0)


# adding the same edge again

def test_re_add_same_order_one_entry_at_a():
    # BASELINE BUG
    graph = ab_graph()
    graph.add_edge("a", "b", 7)
    assert len(adjacency_entries(graph, 0)) == 1


def test_re_add_same_order_one_entry_at_b():
    # BASELINE BUG (contains_edge("a", "b") was false, so the re-add
    # appended to both ends)
    graph = ab_graph()
    graph.add_edge("a", "b", 7)
    assert len(adjacency_entries(graph, 1)) == 1


def test_re_add_reverse_order_one_entry_each():
    graph = ab_graph()
    graph.add_edge("b", "a", 7)
    assert len(adjacency_entries(graph, 0)) == 1
    assert len(adjacency_entries(graph, 1)) == 1


def test_re_add_keeps_weight():
    graph = ab_graph()
    graph.add_edge("b", "a", 7)
    assert graph.edge("b", "a")[2] == 5


# every adjacency entry holds an index

def test_vertices_are_ints_after_name_add_edge():
    # BASELINE BUG
    graph = ab_graph()
    graph.add_edge("b", "c", 2)
    assert all(type(vertex) == int for vertex in all_vertices(graph))


def test_vertices_are_ints_after_index_add_edge():
    graph = Graph()
    graph.add_node("a")
    graph.add_node("b")
    graph.add_node("c")
    graph.add_edge(0, 1, 5)
    graph.add_edge(2, 1, 3)
    assert all(type(vertex) == int for vertex in all_vertices(graph))
    assert graph.contains_edge("a", "b") and graph.contains_edge("b", "c")
    assert graph.contains_edge(1, 0) and graph.contains_edge(1, 2)


# missing edges and unknown names

def test_no_edge_between_existing_nodes():
    graph = ab_graph()
    graph.add_node("c")
    assert not graph.contains_edge("a", "c")
    assert not graph.contains_edge(0, 2)


def raises_value_error(fn, *args):
    try:
        fn(*args)
    except ValueError:
        return True
    return False


def test_unknown_name_raises_value_error():
    graph = ab_graph()
    assert raises_value_error(graph.name_of, "zz")
    assert raises_value_error(graph.edge, "a", "zz")
    assert raises_value_error(graph.contains_edge, "zz", "a")
    assert raises_value_error(graph.contains_edge, "a", "zz")


# from_dict (integer-index add_edge) is unaffected

def test_from_dict_edges():
    graph = Graph.from_dict({'a': ['b', ('c', 3)], 'b': ['a'], 'c': []})
    assert graph.edges() == [('a', 'c', 3), ('a', 'b', 1)]
    assert graph.contains_edge("a", "b") and graph.contains_edge("c", "a")


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

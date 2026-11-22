"""Graph search worked out by code (core/graph_search.py), for BFS and DFS lessons."""
import pytest

from core.graph_search import layout, problems, search

# a small maze: S is the start, G the goal; S-A-B-G is the long way, S-C-G the short one
NODES = ["S", "A", "B", "C", "G", "D"]
EDGES = [["S", "A"], ["A", "B"], ["B", "G"], ["S", "C"], ["C", "G"], ["C", "D"]]


@pytest.mark.unit
def test_breadth_first_search_takes_nodes_level_by_level_and_finds_the_shortest_path():
    found = search(NODES, EDGES, "S", "G", "bfs")
    assert [step["node"] for step in found["steps"]] == ["S", "A", "C", "B", "G"]
    assert found["steps"][0] == {"node": "S", "added": ["A", "C"], "frontier": ["A", "C"], "distance": 0}
    assert found["steps"][2]["frontier"] == ["B", "G", "D"]      # C adds G and D behind B
    assert found["path"] == ["S", "C", "G"]                       # two edges, the shortest
    assert found["distance"]["G"] == 2


@pytest.mark.unit
def test_depth_first_search_goes_deep_first_and_may_find_a_longer_path():
    found = search(NODES, EDGES, "S", "G", "dfs")
    assert [step["node"] for step in found["steps"]] == ["S", "A", "B", "G"]
    assert found["steps"][0]["frontier"] == ["A", "C"]            # A on top of the stack
    assert found["path"] == ["S", "A", "B", "G"]                  # three edges: not the shortest


@pytest.mark.unit
def test_a_graph_that_cannot_be_searched_says_why():
    assert problems(NODES, EDGES, "S", "G") == []
    assert any("cannot be reached" in fault for fault in problems(NODES + ["Z"], EDGES, "S", "G"))
    assert any("not a node" in fault for fault in problems(NODES, EDGES, "S", "Q"))
    assert any("two different nodes" in fault for fault in problems(NODES, EDGES + [["S", "S"]], "S", "G"))


@pytest.mark.unit
def test_nodes_are_placed_by_their_distance_from_the_start():
    places = layout(NODES, EDGES, "S")
    assert places["S"] == (0, 0)
    assert {places["A"][0], places["C"][0]} == {1}
    assert places["G"][0] == 2 and places["B"][0] == 2

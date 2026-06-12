"""Tests for the graph zone: construction, get/set, neighbors, count.

Uses a small pentagon-like test graph:
  Nodes: A, B, C, D, E
  Edges: A-B, A-C, B-C, B-D, D-E
"""

from __future__ import annotations

import pytest

from baize.definition import Zone
from baize.error import ValidationError
from baize.runtime import (
    ComponentId,
    GraphZone,
    runtime_zone_from_definition,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cid(n: int) -> ComponentId:
    return ComponentId(n)


def _test_graph_def() -> Zone:
    """Zone definition for the test graph: 5 nodes, 5 edges."""
    return Zone.from_dict({
        "zone_type": "graph",
        "visibility": "public",
        "nodes": ["A", "B", "C", "D", "E"],
        "edges": [["A", "B"], ["A", "C"], ["B", "C"], ["B", "D"], ["D", "E"]],
    })


def _test_graph() -> GraphZone:
    """Build the test graph from definition."""
    zone = runtime_zone_from_definition(_test_graph_def())
    assert isinstance(zone, GraphZone)
    return zone


# ---------------------------------------------------------------------------
# TestGraphZoneConstruction
# ---------------------------------------------------------------------------


class TestGraphZoneConstruction:
    """Construction from Zone definition."""

    def test_basic_construction(self) -> None:
        """Build from Zone definition with nodes/edges: verify 5 nodes, adjacency correct."""
        graph = _test_graph()
        assert len(graph.node_names) == 5
        assert graph.node_names == ["A", "B", "C", "D", "E"]
        # A (index 0) is adjacent to B (1) and C (2)
        assert sorted(graph.adjacency[0]) == [1, 2]
        # B (index 1) is adjacent to A (0), C (2), D (3)
        assert sorted(graph.adjacency[1]) == [0, 2, 3]
        # E (index 4) is adjacent to D (3) only
        assert graph.adjacency[4] == [3]

    def test_node_properties_parsed(self) -> None:
        """Node properties parsed correctly."""
        zone_def = Zone.from_dict({
            "zone_type": "graph",
            "visibility": "public",
            "nodes": ["A", "B", "C"],
            "edges": [["A", "B"]],
            "node_properties": {
                "A": {"color": "red", "value": 10},
                "C": {"color": "blue"},
            },
        })
        graph = runtime_zone_from_definition(zone_def)
        assert isinstance(graph, GraphZone)
        # A is index 0
        assert graph.node_properties[0] == {"color": "red", "value": 10}
        # C is index 2
        assert graph.node_properties[2] == {"color": "blue"}
        # B has no properties
        assert 1 not in graph.node_properties

    def test_missing_nodes_raises(self) -> None:
        """Missing nodes field raises ValidationError."""
        zone_def = Zone.from_dict({
            "zone_type": "graph",
            "visibility": "public",
        })
        with pytest.raises(ValidationError, match="graph zone requires nodes"):
            runtime_zone_from_definition(zone_def)

    def test_unknown_node_in_edge_raises(self) -> None:
        """Unknown node in edge raises ValidationError."""
        zone_def = Zone.from_dict({
            "zone_type": "graph",
            "visibility": "public",
            "nodes": ["A", "B"],
            "edges": [["A", "Z"]],
        })
        with pytest.raises(ValidationError, match="unknown node in edge: Z"):
            runtime_zone_from_definition(zone_def)


# ---------------------------------------------------------------------------
# TestGraphGetSet
# ---------------------------------------------------------------------------


class TestGraphGetSet:
    """Get and set operations on graph nodes."""

    def test_get_empty_node_returns_none(self) -> None:
        """graph_get on empty node returns None."""
        graph = _test_graph()
        assert graph.graph_get("A") is None
        assert graph.graph_get("E") is None

    def test_set_and_get(self) -> None:
        """graph_set places component, graph_get retrieves it."""
        graph = _test_graph()
        graph.graph_set("B", _cid(42))
        assert graph.graph_get("B") == _cid(42)

    def test_set_returns_previous(self) -> None:
        """graph_set returns previous occupant."""
        graph = _test_graph()
        prev1 = graph.graph_set("A", _cid(10))
        assert prev1 is None
        prev2 = graph.graph_set("A", _cid(20))
        assert prev2 == _cid(10)
        assert graph.graph_get("A") == _cid(20)

    def test_unknown_node_returns_none(self) -> None:
        """graph_get/graph_set on unknown node returns None."""
        graph = _test_graph()
        assert graph.graph_get("Z") is None
        assert graph.graph_set("Z", _cid(99)) is None


# ---------------------------------------------------------------------------
# TestGraphNeighbors
# ---------------------------------------------------------------------------


class TestGraphNeighbors:
    """Neighbor queries on graph nodes."""

    def test_node_a_neighbors(self) -> None:
        """Node A has neighbors [B, C]."""
        graph = _test_graph()
        neighbors = graph.graph_neighbors("A")
        assert sorted(neighbors) == ["B", "C"]

    def test_node_d_neighbors(self) -> None:
        """Node D has neighbors [B, E]."""
        graph = _test_graph()
        neighbors = graph.graph_neighbors("D")
        assert sorted(neighbors) == ["B", "E"]

    def test_unknown_node_empty(self) -> None:
        """Unknown node returns empty list."""
        graph = _test_graph()
        assert graph.graph_neighbors("Z") == []


# ---------------------------------------------------------------------------
# TestGraphCount
# ---------------------------------------------------------------------------


class TestGraphCount:
    """Count of occupied nodes."""

    def test_empty_graph_count(self) -> None:
        """Empty graph has count 0."""
        graph = _test_graph()
        assert graph.count() == 0

    def test_count_after_placements(self) -> None:
        """After placing 3 components, count is 3."""
        graph = _test_graph()
        graph.graph_set("A", _cid(1))
        graph.graph_set("C", _cid(2))
        graph.graph_set("E", _cid(3))
        assert graph.count() == 3

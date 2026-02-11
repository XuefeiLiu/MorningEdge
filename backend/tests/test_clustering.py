"""Tests for clustering module (pure algorithm parts)."""
import numpy as np
import pytest

from backend.pipeline.overnight_pipeline.clustering import _connected_components


class TestConnectedComponents:
    def test_no_nodes(self):
        result = _connected_components(0, [])
        assert result == []

    def test_single_node_no_edges(self):
        result = _connected_components(1, [])
        assert len(result) == 1
        assert result[0] == [0]

    def test_two_nodes_no_edges(self):
        result = _connected_components(2, [])
        assert len(result) == 2

    def test_two_nodes_one_edge(self):
        result = _connected_components(2, [(0, 1)])
        assert len(result) == 1
        assert set(result[0]) == {0, 1}

    def test_three_nodes_chain(self):
        result = _connected_components(3, [(0, 1), (1, 2)])
        assert len(result) == 1
        assert set(result[0]) == {0, 1, 2}

    def test_three_nodes_two_components(self):
        result = _connected_components(3, [(0, 1)])
        assert len(result) == 2
        component_sets = [set(c) for c in result]
        assert {0, 1} in component_sets
        assert {2} in component_sets

    def test_invalid_edges_ignored(self):
        result = _connected_components(2, [(0, 5), (-1, 0)])
        # Edge (0,5) invalid (5 >= n=2), edge (-1,0) invalid
        assert len(result) == 2

    def test_larger_graph(self):
        # 0-1-2, 3-4, 5 alone
        edges = [(0, 1), (1, 2), (3, 4)]
        result = _connected_components(6, edges)
        assert len(result) == 3
        component_sets = [set(c) for c in result]
        assert {0, 1, 2} in component_sets
        assert {3, 4} in component_sets
        assert {5} in component_sets

"""Shortest paths over a Campus adjacency list, with pluggable edge costs.

One algorithm (Dijkstra); each routing mode is a different cost function.

Cost function contract: cost_fn(edge, from_node) -> float | IMPASSABLE
- from_node is the end the edge is being walked from (edges are undirected,
  so this is how direction-dependent costs like uphill ramps see direction).
- Return a non-negative cost, or IMPASSABLE to block the edge in this mode.
"""
import heapq
import itertools
import math
from collections.abc import Callable
from dataclasses import dataclass

from loader import Edge

IMPASSABLE = None

CostFn = Callable[[Edge, str], float | None]


@dataclass(frozen=True)
class Path:
    nodes: tuple[str, ...]   # source first, reached target last
    edges: tuple[Edge, ...]  # edge actually taken between each consecutive pair; len(nodes) - 1
    cost: float              # in the cost function's unit


@dataclass(frozen=True)
class NoPath:
    """No target is reachable from any source under the given cost function."""


# --- search ---

def shortest_path(adjacency, sources, targets, cost_fn: CostFn):
    """Cheapest path from any source to any target, or NoPath().

    Dijkstra: BFS with a min-heap ordered by total cost. Stops at the first
    target popped (its cost is final then), so with targets = a building's
    entrances this also picks the best entrance.
    """
    targets = set(targets)
    best = {}            # node -> cheapest cost found so far
    prev = {}            # node -> (node we came from, edge we used)
    done = set()         # nodes whose cost is final
    heap = []            # (cost, counter, node); counter breaks ties so node ids are never compared
    counter = itertools.count()

    for s in sources:
        best[s] = 0.0
        heapq.heappush(heap, (0.0, next(counter), s))

    while heap:
        cost, _, node = heapq.heappop(heap)
        if node in done:
            continue  # stale entry: a cheaper one for this node was already popped
        done.add(node)

        if node in targets:
            return _build_path(node, prev, cost)

        for neighbor, edge in adjacency[node]:
            c = cost_fn(edge, node)
            if c is IMPASSABLE:
                continue
            new_cost = cost + c
            if new_cost < best.get(neighbor, math.inf):  # relax
                best[neighbor] = new_cost
                prev[neighbor] = (node, edge)
                heapq.heappush(heap, (new_cost, next(counter), neighbor))

    return NoPath()


def _build_path(target, prev, cost):
    """Walk back-pointers from target to a source (sources have no prev entry)."""
    nodes, edges = [target], []
    while nodes[-1] in prev:
        node, edge = prev[nodes[-1]]
        nodes.append(node)
        edges.append(edge)
    nodes.reverse()
    edges.reverse()
    return Path(tuple(nodes), tuple(edges), cost)


# --- cost functions ---

def _meters(edge):
    """The edge's cost in meters. Raises on any other unit so seconds never get added to meters."""
    if edge.cost_unit != "meters":
        raise ValueError(f"cost function expects meters, got {edge.cost_unit!r}")
    return edge.cost


def distance(edge, from_node):
    """Walking: every edge passes, steps and unknown accessibility included."""
    return _meters(edge)


def wheelchair(edge, from_node):
    """Wheelchair: only edges known to be accessible. False and unknown (None) are impassable."""
    cost = _meters(edge)  # unit check first, so a bad unit raises even on a blocked edge
    return cost if edge.accessible is True else IMPASSABLE

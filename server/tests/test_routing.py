import pytest

from loader import Edge, load_campus
from routing import IMPASSABLE, NoPath, distance, shortest_path, wheelchair

# tiny-campus graph:  eA1 -44.5- w1 -82.8- w2 -222.4- w3 -93.7- eA2
#                     plus steps  w1 -240.0- w3  (accessible=False)
#                     island:     i1 -55.6- i2


def edge(accessible=True, unit="meters", cost=10.0):
    return Edge("a", "b", cost, unit, "footway", accessible)


# --- cost functions ---

@pytest.mark.parametrize("acc", [True, False, None])
def test_distance_passes_every_edge(acc):
    assert distance(edge(accessible=acc), "a") == 10.0


def test_distance_ignores_direction():
    assert distance(edge(), "a") == distance(edge(), "b")


def test_wheelchair_passes_known_accessible():
    assert wheelchair(edge(accessible=True), "a") == 10.0


@pytest.mark.parametrize("acc", [False, None])
def test_wheelchair_blocks_inaccessible_and_unknown(acc):
    assert wheelchair(edge(accessible=acc), "a") is IMPASSABLE


def test_zero_cost_is_not_impassable():
    # 0.0 is falsy; it must still come back as a real cost, not be mistaken for IMPASSABLE
    assert wheelchair(edge(cost=0.0), "a") == 0.0
    assert wheelchair(edge(cost=0.0), "a") is not IMPASSABLE


@pytest.mark.parametrize("cost_fn", [distance, wheelchair])
@pytest.mark.parametrize("acc", [True, False, None])
def test_cost_fns_reject_non_meters(cost_fn, acc):
    with pytest.raises(ValueError, match="meters"):
        cost_fn(edge(accessible=acc, unit="seconds"), "a")


# --- shortest_path ---

@pytest.fixture
def campus(tiny_campus):
    return load_campus(tiny_campus)


def test_walking_takes_the_steps(campus):
    path = shortest_path(campus.adjacency, ["eA1"], ["eA2"], distance)
    assert path.nodes == ("eA1", "w1", "w3", "eA2")
    assert path.cost == pytest.approx(44.5 + 240.0 + 93.7)
    assert [e.edge_type for e in path.edges] == ["connector", "steps", "connector"]


def test_wheelchair_goes_the_long_way(campus):
    path = shortest_path(campus.adjacency, ["eA1"], ["eA2"], wheelchair)
    assert path.nodes == ("eA1", "w1", "w2", "w3", "eA2")
    assert path.cost == pytest.approx(44.5 + 82.8 + 222.4 + 93.7)
    assert all(e.accessible is True for e in path.edges)


@pytest.mark.parametrize("cost_fn", [distance, wheelchair])
def test_path_edges_join_consecutive_nodes(campus, cost_fn):
    path = shortest_path(campus.adjacency, ["eA1"], ["eA2"], cost_fn)
    assert len(path.edges) == len(path.nodes) - 1
    for a, b, e in zip(path.nodes, path.nodes[1:], path.edges):
        assert {a, b} == {e.from_node, e.to_node}
    assert path.cost == pytest.approx(sum(e.cost for e in path.edges))


def test_reverse_of_stored_edge_direction(campus):
    # edges.csv stores eA1->w1 ... w3->eA2; walking the other way must work too
    path = shortest_path(campus.adjacency, ["eA2"], ["eA1"], distance)
    assert path.nodes == ("eA2", "w3", "w1", "eA1")


def test_island_is_no_path(campus):
    assert shortest_path(campus.adjacency, ["eA1"], ["i1"], distance) == NoPath()
    assert shortest_path(campus.adjacency, ["i1"], ["eA1"], distance) == NoPath()


def test_cost_fn_gets_the_node_walked_from(campus):
    calls = []
    def recording(edge, from_node):
        calls.append((edge, from_node))
        return distance(edge, from_node)
    shortest_path(campus.adjacency, ["eA2"], ["eA1"], recording)
    for edge, from_node in calls:
        assert from_node in (edge.from_node, edge.to_node)
    # first expansion is from the source; eA2's only edge is stored as w3->eA2
    assert calls[0][1] == "eA2" and calls[0][0].from_node == "w3"


def test_custom_cost_fn_changes_route(campus):
    # Same algorithm, different cost: steps x10 makes walking take the long way.
    avoid_steps = lambda e, frm: e.cost * (10 if e.edge_type == "steps" else 1)
    path = shortest_path(campus.adjacency, ["eA1"], ["eA2"], avoid_steps)
    assert path.nodes == ("eA1", "w1", "w2", "w3", "eA2")

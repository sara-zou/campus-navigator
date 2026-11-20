from pathlib import Path as FsPath

import pytest

from loader import Edge, Node, load_campus
from routing import IMPASSABLE, NoPath, Path, shortest_path, walk, wheelchair

# tiny-campus graph:  eA1 -44.5- w1 -82.8- w2 -222.4- w3 -93.7- eA2
#                     plus steps  w1 -240.0- w3  (accessible=False)
#                     island:     i1 -55.6- i2

REAL_CAMPUS = FsPath(__file__).parents[2] / "data" / "northeastern-boston"


def edge(accessible=True, unit="meters", cost=10.0):
    return Edge("a", "b", cost, unit, "footway", accessible)


# --- cost functions ---
# Path tests below use speed 1, so seconds equal meters and expected costs read as meters.
# No nodes passed: no door is blocked (door tests build their own with campus.nodes).
WALK = walk({}, 1.0)
WHEELCHAIR = wheelchair({}, 1.0)


@pytest.mark.parametrize("acc", [True, False, None])
def test_walk_passes_every_edge(acc):
    assert walk({}, 2.0)(edge(accessible=acc), "a") == 5.0  # 10 m at 2 m/s


def test_walk_ignores_direction():
    assert WALK(edge(), "a") == WALK(edge(), "b")


def test_wheelchair_passes_known_accessible():
    assert wheelchair({}, 2.0)(edge(accessible=True), "a") == 5.0


@pytest.mark.parametrize("acc", [False, None])
def test_wheelchair_blocks_inaccessible_and_unknown(acc):
    assert WHEELCHAIR(edge(accessible=acc), "a") is IMPASSABLE


@pytest.mark.parametrize("make", [walk, wheelchair])
def test_seconds_edges_pass_through_unscaled(make):
    # an elevator ride takes as long whatever the mode's speed
    assert make({}, 1.4)(edge(unit="seconds", cost=35.0), "a") == 35.0
    assert make({}, 0.5)(edge(unit="seconds", cost=35.0), "a") == 35.0


def test_meters_scale_with_speed():
    assert walk({}, 1.4)(edge(cost=14.0), "a") == pytest.approx(10.0)
    assert wheelchair({}, 1.1)(edge(cost=11.0), "a") == pytest.approx(10.0)


def test_zero_cost_is_not_impassable():
    # 0.0 is falsy; it must still come back as a real cost, not be mistaken for IMPASSABLE
    for unit in ("meters", "seconds"):
        assert WHEELCHAIR(edge(cost=0.0, unit=unit), "a") == 0.0
        assert WHEELCHAIR(edge(cost=0.0, unit=unit), "a") is not IMPASSABLE


@pytest.mark.parametrize("make", [walk, wheelchair])
@pytest.mark.parametrize("acc", [True, False, None])
def test_cost_fns_reject_unknown_units(make, acc):
    # the unit check runs before the accessibility check, so a blocked edge still raises
    with pytest.raises(ValueError, match="meters or seconds"):
        make({}, 1.0)(edge(accessible=acc, unit="feet"), "a")


def door(accessible):
    """nodes for edge(): "a" is an entrance with the given accessible, "b" a plain waypoint."""
    return {"a": Node("a", "c", "bA", 0, "latlon", 42.0, -71.0, "entrance", accessible),
            "b": Node("b", "c", None, 0, "latlon", 42.0, -71.0, "waypoint", None)}


@pytest.mark.parametrize("acc", [False, None])
@pytest.mark.parametrize("from_node", ["a", "b"])
def test_wheelchair_blocks_every_edge_at_an_inaccessible_door(acc, from_node):
    # into the door ("b" -> "a") and out of it ("a" -> "b"): ending, starting and passing through
    assert wheelchair(door(acc), 1.0)(edge(), from_node) is IMPASSABLE


def test_wheelchair_passes_an_accessible_door():
    assert wheelchair(door(True), 1.0)(edge(), "a") == 10.0


@pytest.mark.parametrize("acc", [False, None])
def test_walk_ignores_door_accessibility(acc):
    assert walk(door(acc), 1.0)(edge(), "a") == 10.0


@pytest.mark.parametrize("acc", [False, None])
def test_wheelchair_only_doors_block(acc):
    # an inaccessible-flagged waypoint is ignored: node accessible is read for entrances only
    nodes = door(True)
    nodes["b"] = Node("b", "c", None, 0, "latlon", 42.0, -71.0, "waypoint", acc)
    assert wheelchair(nodes, 1.0)(edge(), "b") == 10.0


def test_wheelchair_unknown_node_is_not_a_door():
    # query-time temporary nodes (START) aren't in campus.nodes and must never block
    start_edge = Edge("__start__", "b", 10.0, "meters", "footway", True)
    assert wheelchair(door(False), 1.0)(start_edge, "__start__") == 10.0


# --- shortest_path ---

@pytest.fixture
def campus(tiny_campus):
    return load_campus(tiny_campus)


def test_walking_takes_the_steps(campus):
    path = shortest_path(campus.adjacency, ["eA1"], ["eA2"], WALK)
    assert path.nodes == ("eA1", "w1", "w3", "eA2")
    assert path.cost == pytest.approx(44.5 + 240.0 + 93.7)
    assert [e.edge_type for e in path.edges] == ["connector", "steps", "connector"]


def test_wheelchair_goes_the_long_way(campus):
    path = shortest_path(campus.adjacency, ["eA1"], ["eA2"], WHEELCHAIR)
    assert path.nodes == ("eA1", "w1", "w2", "w3", "eA2")
    assert path.cost == pytest.approx(44.5 + 82.8 + 222.4 + 93.7)
    assert all(e.accessible is True for e in path.edges)


@pytest.mark.parametrize("cost_fn", [WALK, WHEELCHAIR])
def test_path_edges_join_consecutive_nodes(campus, cost_fn):
    path = shortest_path(campus.adjacency, ["eA1"], ["eA2"], cost_fn)
    assert len(path.edges) == len(path.nodes) - 1
    for a, b, e in zip(path.nodes, path.nodes[1:], path.edges):
        assert {a, b} == {e.from_node, e.to_node}
    assert path.cost == pytest.approx(sum(e.cost for e in path.edges))


def test_reverse_of_stored_edge_direction(campus):
    # edges.csv stores eA1->w1 ... w3->eA2; walking the other way must work too
    path = shortest_path(campus.adjacency, ["eA2"], ["eA1"], WALK)
    assert path.nodes == ("eA2", "w3", "w1", "eA1")


def test_island_is_no_path(campus):
    assert shortest_path(campus.adjacency, ["eA1"], ["i1"], WALK) == NoPath()
    assert shortest_path(campus.adjacency, ["i1"], ["eA1"], WALK) == NoPath()


def test_cost_fn_gets_the_node_walked_from(campus):
    calls = []
    def recording(edge, from_node):
        calls.append((edge, from_node))
        return WALK(edge, from_node)
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


# --- sets and edge cases ---

def test_multiple_targets_picks_the_nearest(campus):
    path = shortest_path(campus.adjacency, ["w2"], campus.entrances_for("bA"), WALK)
    assert path.nodes == ("w2", "w1", "eA1")
    assert path.cost == pytest.approx(82.8 + 44.5)


def test_multiple_sources_picks_the_nearest(campus):
    path = shortest_path(campus.adjacency, ["eA1", "w3"], ["eA2"], WALK)
    assert path.nodes == ("w3", "eA2")


def test_building_to_building_uses_both_sets(campus):
    # from bA's entrances to a set holding w2 and the island: w2 wins, reached from eA1
    path = shortest_path(campus.adjacency, campus.entrances_for("bA"), ["w2", "i1"], WALK)
    assert path.nodes == ("eA1", "w1", "w2")


def test_source_is_target(campus):
    assert shortest_path(campus.adjacency, ["w1"], ["w1", "eA2"], WALK) == Path(("w1",), (), 0.0)


def test_building_without_entrances_is_no_path(campus):
    assert campus.entrances_for("bB") == ()
    assert shortest_path(campus.adjacency, ["eA1"], campus.entrances_for("bB"), WALK) == NoPath()


def test_empty_sources_is_no_path(campus):
    assert shortest_path(campus.adjacency, [], ["eA1"], WALK) == NoPath()


@pytest.mark.parametrize("sources, targets", [(["nope"], ["eA1"]), (["eA1"], ["nope"])])
def test_unknown_node_raises(campus, sources, targets):
    with pytest.raises(KeyError, match="nope"):
        shortest_path(campus.adjacency, sources, targets, WALK)


def test_negative_cost_raises(campus):
    with pytest.raises(ValueError, match="negative"):
        shortest_path(campus.adjacency, ["eA1"], ["eA2"], lambda e, frm: -1.0)


def test_wheelchair_no_path_when_steps_are_the_only_way(broken_campus):
    # drop the accessible w2-w3 footway: only the steps connect w1 and w3 now
    campus = load_campus(broken_campus("edges.csv", lambda rows: [r for r in rows if r[:2] != ["w2", "w3"]]))
    assert shortest_path(campus.adjacency, ["eA1"], ["eA2"], WALK).nodes == ("eA1", "w1", "w3", "eA2")
    assert shortest_path(campus.adjacency, ["eA1"], ["eA2"], WHEELCHAIR) == NoPath()


def test_wheelchair_treats_unknown_as_blocked(broken_campus):
    # make the steps edge unknown instead of False: still blocked for WHEELCHAIR, still walkable
    def unknown_steps(rows):
        for r in rows:
            if r[:2] == ["w1", "w3"]:
                r[5] = ""
        return rows
    campus = load_campus(broken_campus("edges.csv", unknown_steps))
    assert "w2" in shortest_path(campus.adjacency, ["eA1"], ["eA2"], WHEELCHAIR).nodes
    assert "w2" not in shortest_path(campus.adjacency, ["eA1"], ["eA2"], WALK).nodes


# --- real data ---

def test_northeastern_every_building_with_entrances_reachable():
    campus = load_campus(REAL_CAMPUS)
    start = campus.entrances_by_building[min(campus.entrances_by_building)][0]
    for building_id, entrances in campus.entrances_by_building.items():
        path = shortest_path(campus.adjacency, [start], entrances, WALK)
        assert isinstance(path, Path), building_id

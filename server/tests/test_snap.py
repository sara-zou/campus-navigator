"""Query layer: snap()."""
import math

import pytest

from conftest import INDOOR_FIXTURE, start_neighbors
from loader import load_campus
from query import START, Snap, TooFar, snap
from routing import IMPASSABLE, NoPath, shortest_path, walk, wheelchair

WALK = walk({}, 1.0)  # speed 1: path costs in seconds equal meters
WHEELCHAIR = wheelchair({}, 1.0)

# tiny-campus nodes (lat, lon):
#   w1 (42.0005, -71.0005)  w2 (42.0005, -71.0015)  w3 (42.0025, -71.0015)
#   eA1 (42.0009, -71.0005) eA2 (42.0021, -71.0005)  island i1 (42.0050, -71.0050) i2 (42.0055, -71.0050)
# edges: eA1-w1 44.5, w1-w2 82.8, w2-w3 222.4 (vertical), w3-eA2 93.7, steps w1-w3 240.0 (diagonal, not accessible)


def test_snap_mid_edge_splits_it(campus):
    s = snap(campus, 42.0015, -71.0017)  # ~16.5 m west of the middle of w2-w3
    assert s.node_id == START
    assert s.lat == pytest.approx(42.0015) and s.lon == pytest.approx(-71.0015)
    assert s.distance_m == pytest.approx(16.5, abs=0.2)
    assert start_neighbors(s) == ["w2", "w3"]
    halves = {n: e.cost for n, e in s.adjacency[START]}
    assert halves["w2"] == pytest.approx(111.2, abs=0.1)
    assert halves["w2"] + halves["w3"] == pytest.approx(222.4)
    assert all(e.edge_type == "footway" and e.accessible is True for _, e in s.adjacency[START])


def test_overlay_links_back_and_leaves_campus_untouched(campus):
    s = snap(campus, 42.0015, -71.0017)
    assert (START in s.adjacency) and (START not in campus.adjacency)
    assert len(s.adjacency) == len(campus.adjacency) + 1
    assert [n for n, _ in s.adjacency["w2"]].count(START) == 1
    assert s.adjacency["w2"][:len(campus.adjacency["w2"])] == campus.adjacency["w2"]
    assert s.adjacency["eA1"] is campus.adjacency["eA1"]  # untouched nodes pass through


def test_route_from_snap(campus):
    s = snap(campus, 42.0015, -71.0017)
    path = shortest_path(s.adjacency, {s.node_id}, campus.entrances_for("bA"), WALK)
    assert path.nodes == (START, "w3", "eA2")
    assert path.cost == pytest.approx(111.2 + 93.7, abs=0.1)


def test_point_on_node_uses_that_node(campus):
    s = snap(campus, 42.0005, -71.0015)  # exactly w2
    assert s == Snap("w2", 42.0005, -71.0015, 0.0, campus.adjacency, 0)


def test_projection_past_the_end_clamps_to_endpoint(campus):
    s = snap(campus, 42.0000, -71.0005)  # south of w1; every nearby edge ends at w1
    assert s.node_id == "w1"
    assert s.adjacency is campus.adjacency
    assert s.distance_m == pytest.approx(55.6, abs=0.1)


def test_walking_snaps_onto_steps_wheelchair_avoids_them(campus):
    on_steps = (42.0015, -71.0010)  # middle of the w1-w3 diagonal
    walk = snap(campus, *on_steps)
    assert walk.distance_m == pytest.approx(0, abs=0.01)
    assert [e.edge_type for _, e in walk.adjacency[START]] == ["steps", "steps"]

    wc = snap(campus, *on_steps, cost_fn=WHEELCHAIR)
    assert start_neighbors(wc) == ["w2", "w3"]
    assert wc.distance_m == pytest.approx(41.4, abs=0.2)


def test_parallel_edges_are_all_split(broken_campus):
    campus = load_campus(broken_campus(
        "edges.csv", lambda rows: rows + [["w1", "w3", "260.0", "meters", "footway", "True"]]))
    s = snap(campus, 42.0015, -71.0010, cost_fn=WHEELCHAIR)  # accessible footway beside the steps
    assert s.distance_m == pytest.approx(0, abs=0.01)
    assert sorted(e.edge_type for _, e in s.adjacency[START]) == ["footway", "footway", "steps", "steps"]

    path = shortest_path(s.adjacency, {s.node_id}, campus.entrances_for("bA"), WHEELCHAIR)
    assert path.nodes == (START, "w1", "eA1")
    assert path.edges[0].edge_type == "footway"
    assert path.cost == pytest.approx(130.0 + 44.5)


def test_too_far(campus):
    r = snap(campus, 42.0100, -71.0005)
    assert isinstance(r, TooFar) and r.distance_m > 200
    assert isinstance(snap(campus, 42.0100, -71.0005, max_m=10_000), Snap)


def test_no_usable_edge_is_too_far_inf(campus):
    assert snap(campus, 42.0015, -71.0017, cost_fn=lambda e, n: IMPASSABLE) == TooFar(math.inf)


def test_island_snap_then_no_path(campus):
    s = snap(campus, 42.00525, -71.0051)
    assert start_neighbors(s) == ["i1", "i2"]
    assert shortest_path(s.adjacency, {s.node_id}, campus.entrances_for("bA"), WALK) == NoPath()


@pytest.mark.parametrize("lat, lon", [(91, 0), (0, -181), (math.nan, 0), (0, math.inf)])
def test_invalid_coordinates_raise(campus, lat, lon):
    with pytest.raises(ValueError):
        snap(campus, lat, lon)


# --- indoor (tiny-indoor fixture) ---

def test_gps_inside_building_snaps_outdoors(indoor):
    at_c0 = (42.30015, -71.10010)  # on the floor-0 corridor: nearest outdoor edge is the o1-e1 connector
    s = snap(indoor, *at_c0)
    assert s.node_id == "e1"       # the door end of the connector, never a corridor
    assert not indoor.nodes[s.node_id].indoor


def test_gps_with_only_indoor_edges_nearby_is_too_far(broken_campus):
    # drop every outdoor edge: an indoor-only graph gives GPS nothing to snap onto
    outdoor = {"o1", "o2", "o3", "o4"}
    campus = load_campus(broken_campus(
        "edges.csv", lambda rows: [r for r in rows if not ({r[0], r[1]} & outdoor)], fixture=INDOOR_FIXTURE))
    assert snap(campus, 42.30015, -71.10010) == TooFar(math.inf)

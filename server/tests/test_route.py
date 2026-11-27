"""Query layer: route()."""
from pathlib import Path

import pytest

from conftest import start_neighbors
from loader import load_campus
from query import START, Flag, FloorChange, NoRoute, Route, route, snap
from routing import shortest_path, wheelchair

REAL_CAMPUS = Path(__file__).parents[2] / "data" / "northeastern-boston"

# tiny-campus nodes (lat, lon):
#   w1 (42.0005, -71.0005)  w2 (42.0005, -71.0015)  w3 (42.0025, -71.0015)
#   eA1 (42.0009, -71.0005) eA2 (42.0021, -71.0005)  island i1 (42.0050, -71.0050) i2 (42.0055, -71.0050)
# edges: eA1-w1 44.5, w1-w2 82.8, w2-w3 222.4 (vertical), w3-eA2 93.7, steps w1-w3 240.0 (diagonal, not accessible)

MID_W2_W3 = (42.0015, -71.0017)  # ~16.5 m west of the middle of w2-w3
AT_W3 = (42.0025, -71.0015)


def test_route_to_building_picks_nearer_entrance(campus):
    r = route(campus, *MID_W2_W3, to_building="bA")
    assert r.entrance_id == "eA2"
    assert r.entrance_name == "Building A (North Entrance)"
    assert r.building_id == "bA"
    assert r.distance_m == pytest.approx(111.2 + 93.7, abs=0.1)
    assert r.approach_m == pytest.approx(16.5, abs=0.2)
    assert r.duration_s == pytest.approx((r.approach_m + r.distance_m) / 1.4)


def test_polyline_starts_at_snapped_point(campus):
    r = route(campus, *MID_W2_W3, to_building="bA")
    assert r.coords[0] == pytest.approx((42.0015, -71.0015))
    assert r.coords[1:] == ((42.0025, -71.0015), (42.0021, -71.0005))  # w3, eA2
    assert r.nodes == (START, "w3", "eA2")
    assert len(r.edges) == len(r.nodes) - 1
    assert r.edges[0].cost == pytest.approx(111.2, abs=0.1)  # half of w2-w3
    assert [e.edge_type for e in r.edges] == ["footway", "connector"]


def test_route_edges_show_steps_on_walking_route(campus):
    walk = route(campus, *AT_W3, to_poi="poi_eA1")
    assert walk.nodes == ("w3", "w1", "eA1")  # snapped onto w3 itself, so no START
    assert walk.edges[0].edge_type == "steps" and walk.edges[0].accessible is False



def test_walking_route_over_steps_is_flagged(campus):
    walk = route(campus, *AT_W3, to_poi="poi_eA1")  # w3 -steps- w1 - eA1
    assert walk.flags == (Flag(0, False, "steps"),)


def test_wheelchair_route_has_no_flags(campus):
    assert route(campus, *AT_W3, to_poi="poi_eA1", mode="wheelchair").flags == ()


def test_accessible_route_has_no_flags(campus):
    assert route(campus, *MID_W2_W3, to_building="bA").flags == ()


def test_unknown_accessibility_is_flagged(broken_campus):
    def unknown_w3_ea2(rows):
        assert rows[4][:2] == ["w3", "eA2"]
        rows[4][5] = ""
        return rows
    campus = load_campus(broken_campus("edges.csv", unknown_w3_ea2))
    r = route(campus, *MID_W2_W3, to_building="bA")
    assert r.nodes == (START, "w3", "eA2")
    assert r.flags == (Flag(1, None, "connector"),)


def test_start_partway_along_steps_flags_the_half_edge(campus):
    r = route(campus, 42.0015, -71.0010, to_poi="poi_eA1")  # middle of the w1-w3 steps
    assert r.nodes == (START, "w1", "eA1")
    assert r.flags == (Flag(0, False, "steps"),)

def test_route_to_poi_goes_to_that_entrance(campus):
    r = route(campus, *MID_W2_W3, to_poi="poi_eA1")  # the farther entrance
    assert r.entrance_id == "eA1"
    assert r.distance_m == pytest.approx(111.2 + 82.8 + 44.5, abs=0.1)


def test_wheelchair_avoids_steps_and_is_slower(campus):
    walk = route(campus, *AT_W3, to_poi="poi_eA1")
    wc = route(campus, *AT_W3, to_poi="poi_eA1", mode="wheelchair")
    assert walk.distance_m == pytest.approx(240.0 + 44.5)              # w3 -steps- w1 - eA1
    assert wc.distance_m == pytest.approx(222.4 + 82.8 + 44.5)         # w3 - w2 - w1 - eA1
    assert wc.duration_s == pytest.approx(wc.distance_m / 1.1)


def with_lift(broken_campus, secs):
    """tiny-campus plus an accessible seconds edge (an "elevator") parallel to the w1-w3 steps."""
    return load_campus(broken_campus(
        "edges.csv", lambda rows: rows + [["w1", "w3", str(secs), "seconds", "elevator", "True"]]))


@pytest.mark.parametrize("mode, speed", [("walk", 1.4), ("wheelchair", 1.1)])
def test_fast_seconds_edge_is_taken_and_counts_as_time_only(broken_campus, mode, speed):
    # 60 s beats the steps (240 m / 1.4 = 171 s) and the long way round
    r = route(with_lift(broken_campus, 60), *AT_W3, to_poi="poi_eA1", mode=mode)
    assert r.nodes == ("w3", "w1", "eA1")
    assert r.edges[0].edge_type == "elevator"
    assert r.distance_m == pytest.approx(44.5)                  # the 60 s edge adds no meters
    assert r.duration_s == pytest.approx(44.5 / speed + 60)     # but does add its seconds


def test_slow_seconds_edge_loses_to_meters(broken_campus):
    # 1000 s is slower than walking the steps, so walking ignores it
    r = route(with_lift(broken_campus, 1000), *AT_W3, to_poi="poi_eA1")
    assert [e.edge_type for e in r.edges] == ["steps", "connector"]
    assert r.duration_s == pytest.approx((240.0 + 44.5) / 1.4)


def door_blocked(broken_campus, *lines, value="False"):
    """tiny-campus with the doors on the given nodes.csv lines (2 = eA1, 3 = eA2) not accessible."""
    def edit(rows):
        for line in lines:
            rows[line - 1][rows[0].index("accessible")] = value
        return rows
    return load_campus(broken_campus("nodes.csv", edit))


@pytest.mark.parametrize("value", ["False", ""])  # known steps, or unknown
def test_wheelchair_skips_an_inaccessible_door(broken_campus, value):
    campus = door_blocked(broken_campus, 3, value=value)  # eA2, the nearer door from w3
    assert route(campus, *AT_W3, to_building="bA").entrance_id == "eA2"  # walking doesn't care
    wc = route(campus, *AT_W3, to_building="bA", mode="wheelchair")
    assert wc.entrance_id == "eA1" and "eA2" not in wc.nodes


def test_wheelchair_no_path_when_every_door_is_blocked(broken_campus):
    campus = door_blocked(broken_campus, 2, 3)
    assert route(campus, *AT_W3, to_building="bA", mode="wheelchair") == NoRoute("no_path")


def test_wheelchair_to_a_blocked_entrance_is_no_path(broken_campus):
    campus = door_blocked(broken_campus, 3)
    assert route(campus, *AT_W3, to_entrance="eA2").entrance_id == "eA2"
    assert route(campus, *AT_W3, to_entrance="eA2", mode="wheelchair") == NoRoute("no_path")


def test_wheelchair_never_snaps_onto_a_blocked_door(broken_campus):
    campus = door_blocked(broken_campus, 3)
    near_connector = (42.0023, -71.0010)  # middle of the w3-eA2 connector
    assert start_neighbors(snap(campus, *near_connector)) == ["eA2", "w3"]
    wc = snap(campus, *near_connector, cost_fn=wheelchair(campus.nodes, 1.1))
    assert wc.node_id != "eA2"
    assert wc.node_id != START or "eA2" not in start_neighbors(wc)


def test_start_on_entrance_is_zero_length(campus):
    r = route(campus, 42.0009, -71.0005, to_building="bA")  # exactly eA1
    assert r.coords == ((42.0009, -71.0005),)
    assert r.distance_m == 0 and r.duration_s == 0
    assert r.entrance_id == "eA1"


def test_route_no_entrances(campus):
    assert route(campus, *MID_W2_W3, to_building="bB") == NoRoute("no_entrances")


def test_route_too_far(campus):
    r = route(campus, 42.0100, -71.0005, to_building="bA")
    assert r.reason == "too_far" and r.distance_m > 200


def test_no_path_from_island(campus):
    assert route(campus, 42.00525, -71.0051, to_building="bA") == NoRoute("no_path")


def test_route_to_entrance_goes_to_that_door(campus):
    best = route(campus, *MID_W2_W3, to_building="bA")
    assert best.entrance_id == "eA2"
    r = route(campus, *MID_W2_W3, to_entrance="eA1")  # the farther door
    assert r.entrance_id == "eA1"
    assert r.entrance_name == "Building A (South Entrance)"
    assert r.building_id == "bA"
    assert r.distance_m == pytest.approx(111.2 + 82.8 + 44.5, abs=0.1)


def test_route_to_entrance_wheelchair_avoids_steps(campus):
    walk = route(campus, *AT_W3, to_entrance="eA1")
    wc = route(campus, *AT_W3, to_entrance="eA1", mode="wheelchair")
    assert walk.nodes == ("w3", "w1", "eA1") and walk.flags
    assert wc.nodes == ("w3", "w2", "w1", "eA1") and wc.flags == ()


@pytest.mark.parametrize("kwargs, err", [
    ({}, ValueError),
    ({"to_building": "bA", "to_poi": "poi_eA1"}, ValueError),
    ({"to_building": "bA", "to_entrance": "eA1"}, ValueError),
    ({"to_poi": "poi_eA1", "to_entrance": "eA1"}, ValueError),
    ({"to_entrance": "w1"}, KeyError),     # a node, but not an entrance
    ({"to_entrance": "nope"}, KeyError),
    ({"to_entrance": "EA1"}, KeyError),    # case-sensitive
    ({"to_building": "bA", "mode": "bike"}, ValueError),
    ({"to_building": "nope"}, KeyError),
    ({"to_poi": "nope"}, KeyError),
])
def test_caller_bugs_raise(campus, kwargs, err):
    with pytest.raises(err):
        route(campus, *MID_W2_W3, **kwargs)


def test_route_on_real_campus():
    campus = load_campus(REAL_CAMPUS)
    for mode in ("walk", "wheelchair"):
        r = route(campus, 42.3398, -71.0892, to_building="ry", mode=mode)
        assert isinstance(r, Route) and r.building_id == "ry"


def test_real_campus_door_rule_cuts_nothing_off():
    # Every Northeastern door is accessible=True, so wheelchair reachability must be exactly
    # what the edges alone allow. (Two buildings, wve and ha, are reachable only over steps;
    # that's the sidewalk data, not the door rule.)
    campus = load_campus(REAL_CAMPUS)
    start = [campus.entrances_by_building["ry"][0]]
    with_doors, edges_only = wheelchair(campus.nodes, 1.1), wheelchair({}, 1.1)
    for building_id, entrances in campus.entrances_by_building.items():
        assert (shortest_path(campus.adjacency, start, entrances, with_doors)
                == shortest_path(campus.adjacency, start, entrances, edges_only)), building_id


# --- indoor (tiny-indoor fixture) ---
# hq: south door e1 (floor 0, accessible) - c0 - stairs s0-s1 (15 s) / elevator l0-l1 (35 s) - c1 - r101 (floor 1);
# north door e2 (floor 1, accessible=False) - c1. Outdoor sidewalk o1 - o2 - o3 - o4; o1-e1 and o4-e2 connectors.

SOUTH = (42.30000, -71.10010)   # ~5.6 m south of o1; snaps onto o1
NORTH = (42.30040, -71.10010)   # ~5.6 m north of o4; snaps onto o4


def test_walk_to_room_takes_the_stairs(indoor):
    r = route(indoor, *SOUTH, to_poi="poi_r101")
    assert r.nodes == ("o1", "e1", "c0", "s0", "s1", "c1", "r101")
    assert r.floors == (0, 0, 0, 0, 1, 1, 1)
    assert r.indoor == (False, False, True, True, True, True, True)
    assert r.floor_changes == (FloorChange(3, 0, 1, "steps"),)
    assert r.flags == (Flag(3, False, "steps"),)
    assert r.distance_m == pytest.approx(5.6 + 5.6 + 6.9 + 6.9 + 6.2)  # the stairs add no meters
    assert r.duration_s == pytest.approx((r.approach_m + r.distance_m) / 1.4 + 15)
    assert (r.end_id, r.entrance_id, r.entrance_name, r.building_id) == (
        "r101", "e1", "Headquarters (South Entrance)", "hq")


def test_wheelchair_to_room_takes_the_elevator(indoor):
    r = route(indoor, *SOUTH, to_poi="poi_r101", mode="wheelchair")
    assert r.nodes == ("o1", "e1", "c0", "l0", "l1", "c1", "r101")
    assert r.floor_changes == (FloorChange(3, 0, 1, "elevator"),)
    assert r.flags == ()
    assert r.duration_s == pytest.approx((r.approach_m + r.distance_m) / 1.1 + 35)


def test_walk_from_north_enters_on_floor_1(indoor):
    # e2 is on floor 1 (up the hill), so the door itself is where the floor changes: no stairs
    r = route(indoor, *NORTH, to_poi="poi_r101")
    assert r.nodes == ("o4", "e2", "c1", "r101")
    assert r.floor_changes == (FloorChange(0, 0, 1, "connector"),)
    assert r.entrance_id == "e2" and r.flags == ()


def test_wheelchair_from_north_goes_around_the_stepped_door(indoor):
    r = route(indoor, *NORTH, to_poi="poi_r101", mode="wheelchair")
    assert r.nodes == ("o4", "o3", "o2", "o1", "e1", "c0", "l0", "l1", "c1", "r101")
    assert r.entrance_id == "e1"


def test_start_from_room(indoor):
    r = route(indoor, from_poi="poi_r101", to_entrance="e2")
    assert r.nodes == ("r101", "c1", "e2")
    assert r.coords[0] == (indoor.nodes["r101"].x_or_lat, indoor.nodes["r101"].y_or_lon)
    assert r.approach_m == 0 and r.floors == (1, 1, 1) and r.indoor == (True, True, False)


def test_start_from_room_wheelchair_to_stepped_door_is_no_path(indoor):
    assert route(indoor, from_poi="poi_r101", to_entrance="e2", mode="wheelchair") == NoRoute("no_path")


def test_start_from_room_to_building_uses_the_nearest_door(indoor):
    assert route(indoor, from_poi="poi_r101", to_building="hq").end_id == "e2"
    assert route(indoor, from_poi="poi_r101", to_building="hq", mode="wheelchair").end_id == "e1"


def test_start_from_entrance(indoor):
    r = route(indoor, from_entrance="e1", to_poi="poi_r101")
    assert r.nodes == ("e1", "c0", "s0", "s1", "c1", "r101")
    assert r.approach_m == 0 and r.entrance_id == "e1"


def test_start_from_blocked_entrance_wheelchair_is_no_path(indoor):
    assert route(indoor, from_entrance="e2", to_poi="poi_r101", mode="wheelchair") == NoRoute("no_path")


def test_room_to_same_room_is_zero_length(indoor):
    r = route(indoor, from_poi="poi_r101", to_poi="poi_r101")
    assert r.nodes == ("r101",) and r.distance_m == 0 and r.duration_s == 0
    assert r.entrance_id is None and r.entrance_name is None  # no door on the path
    assert r.floors == (1,) and r.floor_changes == ()


def test_start_from_building_leaves_by_the_best_door_for_the_target(indoor):
    r = route(indoor, from_building="hq", to_poi="poi_r101")
    assert r.start_id == "e2" and r.nodes == ("e2", "c1", "r101")
    assert r.coords[0] == (indoor.nodes["e2"].x_or_lat, indoor.nodes["e2"].y_or_lon)
    assert r.approach_m == 0 and r.floors[0] == 1
    assert route(indoor, from_building="hq", to_entrance="e1").start_id == "e1"


def test_start_from_building_wheelchair_skips_the_stepped_door(indoor):
    r = route(indoor, from_building="hq", to_poi="poi_r101", mode="wheelchair")
    assert r.start_id == "e1" and "l0" in r.nodes


def test_start_from_building_to_same_building(indoor):
    walk = route(indoor, from_building="hq", to_building="hq")
    assert walk.nodes == (walk.start_id,) and walk.start_id in ("e1", "e2") and walk.distance_m == 0
    chair = route(indoor, from_building="hq", to_building="hq", mode="wheelchair")
    assert chair.nodes == ("e1",)                    # never the stepped door, even with no edge taken


def test_start_from_building_without_entrances(campus):
    assert route(campus, from_building="bB", to_building="bA") == NoRoute("start_no_entrances")
    assert route(campus, from_building="bB", to_building="bB") == NoRoute("no_entrances")  # target first


def test_start_id(campus, indoor):
    assert route(campus, *AT_W3, to_building="bA").start_id is None        # GPS
    assert route(indoor, from_poi="poi_r101", to_entrance="e2").start_id == "r101"
    assert route(indoor, from_entrance="e1", to_poi="poi_r101").start_id == "e1"


@pytest.mark.parametrize("args, kwargs, err", [
    ((), {"to_building": "hq"}, ValueError),                                       # no start
    ((), {"from_building": "hq", "from_entrance": "e1", "to_poi": "poi_r101"}, ValueError),
    ((), {"from_building": "nope", "to_poi": "poi_r101"}, KeyError),
    ((42.3,), {"to_building": "hq"}, ValueError),                                  # lat without lon
    (SOUTH, {"from_poi": "poi_r101", "to_building": "hq"}, ValueError),            # two starts
    ((), {"from_poi": "poi_r101", "from_entrance": "e1", "to_building": "hq"}, ValueError),
    ((), {"from_poi": "nope", "to_building": "hq"}, KeyError),
    ((), {"from_entrance": "c0", "to_building": "hq"}, KeyError),                  # a node, not an entrance
])
def test_start_caller_bugs_raise(indoor, args, kwargs, err):
    with pytest.raises(err):
        route(indoor, *args, **kwargs)


def test_outdoor_routes_have_flat_floor_info(campus):
    r = route(campus, *AT_W3, to_building="bA")
    assert set(r.floors) == {0} and not any(r.indoor) and r.floor_changes == ()
    assert r.entrance_id == r.end_id == "eA2"

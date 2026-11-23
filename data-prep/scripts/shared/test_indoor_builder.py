"""Run from data-prep/: .venv/bin/python -m pytest scripts/shared"""
import pytest

from indoor_builder import (ELEVATOR_S_PER_FLOOR, ELEVATOR_WAIT_S, NODE_COLS, EDGE_COLS, POI_COLS,
                            STAIRS_S_PER_FLIGHT, Building, Door, build_interior, haversine_m,
                            local_to_latlon, room_name)

ORIGIN = (42.305, -71.093)
DOOR = Door("door", 42.305, -71.093, 0, 0.0)   # at the corridor's start, ground floor


def bldg(**kw):
    spec = dict(building_id="hq", campus_id="demo", origin=ORIGIN, bearing_deg=0, length_m=32,
                floors=(0, 1, 2), stairs_at=(0.0,), elevator_at=16.0, doors=(DOOR,))
    spec.update(kw)
    return Building(**spec)


def by_type(edges, edge_type):
    return [e for e in edges if e["edge_type"] == edge_type]


def floor_of(nodes):
    return {n["node_id"]: n["floor"] for n in nodes}


def test_counts_for_three_floors():
    nodes, edges, pois = build_interior(bldg())
    # per floor: 4 rooms (at 4, 12, 20, 28), corridor stops {0, 4, 12, 16, 20, 28} = 6, 1 stair, 1 lift
    assert sum(n["type"] == "room" for n in nodes) == 12
    assert sum(n["type"] == "corridor" for n in nodes) == 18
    assert sum(n["type"] == "stairs" for n in nodes) == 3
    assert sum(n["type"] == "elevator" for n in nodes) == 3
    assert len(pois) == 12
    # corridor: 5 between stops + 4 to rooms + 1 to stairs + 1 to lift = 11 per floor, + 1 door edge
    assert len(by_type(edges, "corridor")) == 3 * 11 + 1
    assert len(by_type(edges, "steps")) == 2
    assert len(by_type(edges, "elevator")) == 3


def test_elevator_joins_every_pair_with_wait_plus_per_floor():
    nodes, edges, _ = build_interior(bldg(floors=(-1, 0, 1, 2)))
    fl = floor_of(nodes)
    lifts = {frozenset((fl[e["from_node"]], fl[e["to_node"]])): e for e in by_type(edges, "elevator")}
    assert len(lifts) == 6  # every pair of 4 floors
    e = lifts[frozenset((-1, 2))]
    assert e["cost"] == ELEVATOR_WAIT_S + 3 * ELEVATOR_S_PER_FLOOR
    assert e["cost_unit"] == "seconds" and e["accessible"] is True


def test_stairs_join_consecutive_floors_only():
    nodes, edges, _ = build_interior(bldg(floors=(-1, 0, 1, 2)))
    fl = floor_of(nodes)
    steps = by_type(edges, "steps")
    assert sorted(sorted((fl[e["from_node"]], fl[e["to_node"]])) for e in steps) == [[-1, 0], [0, 1], [1, 2]]
    assert all(e["cost"] == STAIRS_S_PER_FLIGHT and e["cost_unit"] == "seconds" and e["accessible"] is False
               for e in steps)


def test_two_staircases_each_get_their_flights():
    _, edges, _ = build_interior(bldg(stairs_at=(0.0, 32.0)))
    assert len(by_type(edges, "steps")) == 4


def test_single_floor_has_no_vertical_edges():
    _, edges, _ = build_interior(bldg(floors=(0,)))
    assert by_type(edges, "steps") == by_type(edges, "elevator") == []


def test_no_elevator_means_stairs_only():
    nodes, edges, _ = build_interior(bldg(elevator_at=None))
    assert by_type(edges, "elevator") == []
    assert not any(n["type"] == "elevator" for n in nodes)


def test_every_edge_end_exists_and_ids_are_unique():
    nodes, edges, pois = build_interior(bldg(floors=(-1, 0, 1)))
    ids = [n["node_id"] for n in nodes]
    assert len(ids) == len(set(ids))
    known = set(ids) | {"door"}
    assert all(e["from_node"] in known and e["to_node"] in known for e in edges)
    assert all(p["node_id"] in known for p in pois)
    assert len({p["poi_id"] for p in pois}) == len(pois)


def test_meters_costs_match_point_distances():
    nodes, edges, _ = build_interior(bldg())
    pos = {n["node_id"]: (n["x_or_lat"], n["y_or_lon"]) for n in nodes} | {"door": (DOOR.lat, DOOR.lon)}
    for e in edges:
        if e["cost_unit"] == "meters":
            assert e["cost"] == pytest.approx(haversine_m(*pos[e["from_node"]], *pos[e["to_node"]]), abs=0.01)


def test_door_edge_lands_on_the_doors_floor():
    upper = Door("north", 42.3053, -71.093, 1, 32.0)
    nodes, edges, _ = build_interior(bldg(doors=(DOOR, upper)))
    fl = floor_of(nodes)
    door_edges = {e["from_node"]: e["to_node"] for e in edges if e["from_node"] in ("door", "north")}
    assert fl[door_edges["door"]] == 0
    assert fl[door_edges["north"]] == 1


def test_bearing_rotates_layout():
    lat, lon = local_to_latlon(ORIGIN, 0, 100, 0)      # 0° runs north
    assert lat > ORIGIN[0] and lon == pytest.approx(ORIGIN[1])
    lat, lon = local_to_latlon(ORIGIN, 90, 100, 0)     # 90° runs east
    assert lon > ORIGIN[1] and lat == pytest.approx(ORIGIN[0])
    lat, lon = local_to_latlon(ORIGIN, 0, 0, 10)       # positive side is to the left: west when facing north
    assert lon < ORIGIN[1]
    assert haversine_m(*ORIGIN, *local_to_latlon(ORIGIN, 37, 100, 0)) == pytest.approx(100, rel=1e-3)


def test_stairs_and_lift_stack_at_same_point_across_floors():
    nodes, _, _ = build_interior(bldg())
    for type_ in ("stairs", "elevator"):
        points = {(n["x_or_lat"], n["y_or_lon"]) for n in nodes if n["type"] == type_}
        assert len(points) == 1


def test_rows_have_contract_columns_and_are_indoor():
    nodes, edges, pois = build_interior(bldg())
    assert all(list(n) == NODE_COLS and n["indoor"] is True for n in nodes)
    assert all(list(e) == EDGE_COLS for e in edges)
    assert all(list(p) == POI_COLS and p["category"] == "room" for p in pois)


def test_room_names():
    assert room_name(1, 1) == "Room 101"
    assert room_name(3, 12) == "Room 312"
    assert room_name(0, 4) == "Room G04"
    assert room_name(-1, 2) == "Room B102"


def test_room_poi_floor_matches_its_node():
    nodes, _, pois = build_interior(bldg(floors=(-1, 0, 2)))
    fl = floor_of(nodes)
    assert all(p["floor"] == fl[p["node_id"]] for p in pois)


@pytest.mark.parametrize("kw", [
    dict(floors=()),
    dict(floors=(0, 0)),
    dict(length_m=0),
    dict(stairs_at=(40.0,)),
    dict(elevator_at=-1.0),
    dict(doors=(Door("d", 42.3, -71.1, 5, 0.0),)),     # floor not in the building
    dict(doors=(Door("d", 42.3, -71.1, 0, 33.0),)),    # past the corridor's end
])
def test_bad_spec_raises(kw):
    with pytest.raises(ValueError):
        build_interior(bldg(**kw))

"""Query layer: building_layout()."""
import pytest

from conftest import INDOOR_FIXTURE
from loader import load_campus
from query import building_layout


def test_layout_floors_points_and_segments(indoor):
    layout = building_layout(indoor, "hq")
    assert layout.floors == (0, 1)
    ground, first = layout.by_floor[0], layout.by_floor[1]
    assert [p.node_id for p in ground.points] == ["c0", "e1", "l0", "s0"]     # sorted; the door included
    assert [p.node_id for p in first.points] == ["c1", "e2", "l1", "r101", "s1"]
    assert len(ground.segments) == 3   # e1-c0, c0-s0, c0-l0
    assert len(first.segments) == 4    # s1-c1, l1-c1, c1-r101, c1-e2


def test_layout_points_carry_first_poi(indoor):
    by_id = {p.node_id: p for p in building_layout(indoor, "hq").by_floor[1].points}
    assert (by_id["r101"].poi_id, by_id["r101"].name, by_id["r101"].type) == ("poi_r101", "Room 101", "room")
    assert by_id["c1"].poi_id is None and by_id["c1"].name is None


def test_layout_has_no_vertical_or_outdoor_segments(indoor):
    layout = building_layout(indoor, "hq")
    nodes = indoor.nodes
    stairs = (nodes["s0"].x_or_lat, nodes["s0"].y_or_lon)
    for fl in layout.by_floor.values():
        for a, b in fl.segments:
            assert a != b                                           # stairs/elevator (same point) aren't segments
    outdoor = {(nodes[n].x_or_lat, nodes[n].y_or_lon) for n in ("o1", "o2", "o3", "o4")}
    assert not any(a in outdoor or b in outdoor for fl in layout.by_floor.values() for a, b in fl.segments)
    assert stairs in {(p.lat, p.lon) for p in layout.by_floor[0].points}


def test_layout_parallel_edges_give_one_segment(broken_campus):
    c = load_campus(broken_campus("edges.csv", lambda rows: rows + [["c1", "r101", "9", "meters", "corridor", "False"]],
                                  fixture=INDOOR_FIXTURE))
    assert len(building_layout(c, "hq").by_floor[1].segments) == 4


def test_layout_building_without_interior(campus):
    layout = building_layout(campus, "bA")
    assert layout.floors == () and dict(layout.by_floor) == {}


def test_layout_unknown_building_raises(campus):
    with pytest.raises(KeyError):
        building_layout(campus, "nope")

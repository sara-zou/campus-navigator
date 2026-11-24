"""The generated demo-university campus (data/demo-university, from data-prep/scripts/demo-university/).

Each test pins one demo case the generator is meant to provide, so a regenerated
campus that loses one fails here.
"""
import csv
import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import create_app
from loader import load_all, load_campus
from query import NoRoute, route, search

DATA = Path(__file__).parents[2] / "data"
DEMO = DATA / "demo-university"

M_PER_DEG = math.pi * 6_371_000 / 180
ORIGIN = (42.305, -71.093)   # the generator's ORIGIN; positions below are metres east/north of it


def at(x, y):
    lat0, lon0 = ORIGIN
    return lat0 + y / M_PER_DEG, lon0 + x / (M_PER_DEG * math.cos(math.radians(lat0)))


SOUTH_STREET = at(24, -40)   # south of Main Hall
EAST_WALK = at(75, 0)        # beside Main Hall's east door
NORTH_PATH = at(16, 88)      # up the hill, north of Hillside Lab
BELOW_HILL = at(-30, 35)     # foot of the hill stairs


@pytest.fixture(scope="module")
def demo():
    return load_campus(DEMO)


def vertical(r):
    """Floor changes that are real vertical moves (not an upper-floor door's connector)."""
    return [c.edge_type for c in r.floor_changes if c.edge_type != "connector"]


def test_all_campuses_in_data_load():
    assert {"demo-university", "northeastern-boston"} <= set(load_all(DATA))


def test_basement_room_by_stairs_walking_and_elevator_wheelchair(demo):
    walk = route(demo, *SOUTH_STREET, to_poi="poi-hall-b1-r1")
    chair = route(demo, *SOUTH_STREET, to_poi="poi-hall-b1-r1", mode="wheelchair")
    assert walk.end_id == chair.end_id == "hall-b1-r1"
    assert walk.floors[-1] == chair.floors[-1] == -1
    assert vertical(walk) == ["steps"]
    assert vertical(chair) == ["elevator"]
    assert chair.flags == ()


def test_wheelchair_avoids_stepped_east_door(demo):
    assert route(demo, *EAST_WALK, to_building="hall").entrance_id == "hall-door-e"
    assert route(demo, *EAST_WALK, to_building="hall", mode="wheelchair").entrance_id == "hall-door-s"


def test_upper_floor_door_skips_the_stairs(demo):
    for mode in ("walk", "wheelchair"):
        r = route(demo, *NORTH_PATH, to_poi="poi-lab-1-r1", mode=mode)
        assert r.entrance_id == "lab-door-n"
        assert vertical(r) == []           # only the door's connector changes floor
        assert r.floors[-1] == 1


def test_stairs_only_building_upper_floors_unreachable_by_wheelchair(demo):
    assert route(demo, *SOUTH_STREET, to_poi="poi-annex-2-r1", mode="wheelchair") == NoRoute("no_path")
    walk = route(demo, *SOUTH_STREET, to_poi="poi-annex-2-r1")
    assert vertical(walk) == ["steps", "steps"]
    assert route(demo, *SOUTH_STREET, to_poi="poi-annex-0-r1", mode="wheelchair").end_id == "annex-0-r1"


def test_hill_stairs_walking_ramp_wheelchair(demo):
    walk = route(demo, *BELOW_HILL, to_entrance="lab-door-n")
    chair = route(demo, *BELOW_HILL, to_entrance="lab-door-n", mode="wheelchair")
    assert [f.edge_type for f in walk.flags] == ["steps"]
    assert "w-r1" not in walk.nodes
    assert "w-r1" in chair.nodes and chair.flags == ()


def test_building_without_entrances(demo):
    assert route(demo, *SOUTH_STREET, to_building="shed") == NoRoute("no_entrances")


def test_search_outdoor_and_in_building(demo):
    assert [r.id for r in search(demo, "bus")] == ["poi-bus"]
    assert search(demo, "room 101") == ()                          # rooms only in building search
    lib = search(demo, "room 101", building="lib")
    assert [(r.name, r.floor) for r in lib] == [("Room 101", 1)]


def test_api_buildings_floors():
    body = TestClient(create_app(DATA)).get("/campuses/demo-university/buildings").json()
    by_id = {b["id"]: b for b in body}
    assert by_id["hall"]["floors"] == [-1, 0, 1, 2]
    assert by_id["lib"]["floors"] == [0, 1, 2, 3]
    assert by_id["cafe"]["floors"] == [] and len(by_id["cafe"]["entrances"]) == 1
    assert by_id["shed"]["entrances"] == []
    doors = {e["node_id"]: e for e in by_id["hall"]["entrances"]}
    assert doors["hall-door-e"]["accessible"] is False
    assert {e["node_id"]: e["floor"] for e in by_id["lab"]["entrances"]} == {"lab-door-s": 0, "lab-door-n": 1}


def test_demo_is_first_campus():
    # the frontend uses the first campus from /campuses until step 6's picker
    ids = [c["id"] for c in TestClient(create_app(DATA)).get("/campuses").json()]
    assert ids[0] == "demo-university"


# --- northeastern-boston-demo: real NEU + mock interiors (data-prep/scripts/northeastern-boston-demo/) ---

REAL_NEU = DATA / "northeastern-boston"
NEU_DEMO = DATA / "northeastern-boston-demo"
MOCK_BUILDINGS = {"sl": [-1, 0, 1, 2, 3], "isec": [0, 1, 2, 3], "exp": [0, 1, 2, 3, 4]}


def csv_rows(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def neu_demo():
    return load_campus(NEU_DEMO)


@pytest.mark.parametrize("file", ["buildings.csv", "edges.csv", "pois.csv"])
def test_neu_demo_keeps_every_real_row(file):
    # fails when the real data changed and the demo wasn't regenerated
    demo = {tuple(r.items()) for r in csv_rows(NEU_DEMO / file)}
    assert all(tuple(r.items()) in demo for r in csv_rows(REAL_NEU / file))


def test_neu_demo_keeps_every_real_node():
    demo = {r["node_id"]: r for r in csv_rows(NEU_DEMO / "nodes.csv")}
    for r in csv_rows(REAL_NEU / "nodes.csv"):
        d = demo[r["node_id"]]
        assert d["campus_id"] == "northeastern-boston-demo" and d["indoor"] == "False"
        assert {k: v for k, v in d.items() if k not in ("campus_id", "indoor")} == \
               {k: v for k, v in r.items() if k != "campus_id"}


def test_neu_demo_mock_pois_are_labelled(neu_demo):
    real_ids = {r["poi_id"] for r in csv_rows(REAL_NEU / "pois.csv")}
    mock = [p for p in neu_demo.pois.values() if p.id not in real_ids]
    assert mock and all(p.notes == "Mock indoor data" and p.building_id in MOCK_BUILDINGS for p in mock)


def test_neu_demo_basement_room_through_a_real_door(neu_demo):
    door = neu_demo.nodes[neu_demo.entrances_for("sl")[0]]
    walk = route(neu_demo, door.x_or_lat, door.y_or_lon, to_poi="poi-sl-b1-r1")
    chair = route(neu_demo, door.x_or_lat, door.y_or_lon, to_poi="poi-sl-b1-r1", mode="wheelchair")
    assert walk.entrance_id in neu_demo.entrances_for("sl")        # a real entrance node
    assert walk.end_id == chair.end_id == "sl-b1-r1"
    assert vertical(walk) == ["steps"] and vertical(chair) == ["elevator"]


def test_neu_demo_top_floor_room(neu_demo):
    door = neu_demo.nodes[neu_demo.entrances_for("exp")[0]]
    r = route(neu_demo, door.x_or_lat, door.y_or_lon, to_poi="poi-exp-4-r1", mode="wheelchair")
    assert r.floors[-1] == 4 and vertical(r) == ["elevator"]


def test_neu_demo_search(neu_demo):
    assert [r.id for r in search(neu_demo, "isec")] == ["isec"]          # door alias still folds
    assert search(neu_demo, "room 101") == ()
    assert [r.name for r in search(neu_demo, "room 101", building="isec")] == ["Room 101"]


def test_neu_demo_api_floors_only_on_mock_buildings():
    body = TestClient(create_app(DATA)).get("/campuses/northeastern-boston-demo/buildings").json()
    assert {b["id"]: b["floors"] for b in body if b["floors"]} == MOCK_BUILDINGS

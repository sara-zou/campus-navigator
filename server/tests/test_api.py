import csv
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import DATA_ENV_VAR, DEFAULT_DATA_ROOT, create_app, resolve_data_root
from conftest import copy_campus
from loader import LoadError


@pytest.fixture
def data_root(tmp_path, tiny_campus):
    """A data folder holding one copy of tiny-campus."""
    copy_campus(tiny_campus, tmp_path, "tiny-campus")
    return tmp_path


def get(root, url):
    return TestClient(create_app(root)).get(url)


# --- data root ---

def test_data_root_argument_beats_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv(DATA_ENV_VAR, "/from/env")
    assert resolve_data_root(tmp_path) == tmp_path


def test_data_root_from_env_var(monkeypatch):
    monkeypatch.setenv(DATA_ENV_VAR, "/from/env")
    assert str(resolve_data_root()) == "/from/env"


def test_data_root_default_is_repo_data(monkeypatch):
    monkeypatch.delenv(DATA_ENV_VAR, raising=False)
    assert resolve_data_root() == DEFAULT_DATA_ROOT
    assert DEFAULT_DATA_ROOT == Path(__file__).resolve().parents[2] / "data"


def test_create_app_uses_env_var(monkeypatch, data_root):
    monkeypatch.setenv(DATA_ENV_VAR, str(data_root))
    res = TestClient(create_app()).get("/campuses")
    assert [c["id"] for c in res.json()] == ["tiny-campus"]


# --- startup ---

def test_create_app_raises_on_bad_campus(broken_campus):
    campus_dir = broken_campus("nodes.csv", lambda rows: rows + [["w1"] + rows[3][1:]])  # duplicate node id
    with pytest.raises(LoadError):
        create_app(campus_dir.parent)


def test_create_app_raises_on_missing_data_folder(tmp_path):
    with pytest.raises(LoadError, match="data folder not found"):
        create_app(tmp_path / "nope")


# --- GET /campuses ---

def test_campuses_lists_id_and_bounds(data_root):
    res = get(data_root, "/campuses")
    assert res.status_code == 200
    assert res.json() == [{"id": "tiny-campus", "bounds": [[42.0005, -71.0050], [42.0055, -71.0005]]}]


def test_campuses_multiple_sorted(tmp_path, tiny_campus):
    copy_campus(tiny_campus, tmp_path, "tiny-campus")
    copy_campus(tiny_campus, tmp_path, "second-campus")
    res = get(tmp_path, "/campuses")
    assert [c["id"] for c in res.json()] == ["second-campus", "tiny-campus"]


# --- GET /campuses/{id}/buildings ---

def fixture_geometry(tiny_campus, building_id):
    with (tiny_campus / "buildings.csv").open(newline="") as f:
        row = next(r for r in csv.DictReader(f) if r["building_id"] == building_id)
    return json.loads(row["polygon_geojson"])


def test_buildings_unknown_campus_404(data_root):
    res = get(data_root, "/campuses/nope/buildings")
    assert res.status_code == 404
    assert res.json() == {"detail": "unknown campus 'nope'"}


def test_buildings_campus_id_is_case_sensitive(data_root):
    assert get(data_root, "/campuses/Tiny-Campus/buildings").status_code == 404


def test_buildings_with_entrances(data_root, tiny_campus):
    res = get(data_root, "/campuses/tiny-campus/buildings")
    assert res.status_code == 200
    by_id = {b["id"]: b for b in res.json()}
    assert [b["id"] for b in res.json()] == ["bA", "bB"]
    bA = by_id["bA"]
    assert bA["name"] == "Building A"
    assert bA["geometry"] == fixture_geometry(tiny_campus, "bA")
    assert bA["entrances"] == [
        {"node_id": "eA1", "name": "Building A (South Entrance)", "lat": 42.0009, "lon": -71.0005},
        {"node_id": "eA2", "name": "Building A (North Entrance)", "lat": 42.0021, "lon": -71.0005},
    ]


def test_buildings_without_entrances(data_root):
    bB = next(b for b in get(data_root, "/campuses/tiny-campus/buildings").json() if b["id"] == "bB")
    assert bB["entrances"] == []


def test_buildings_entrance_without_poi_has_null_name(broken_campus):
    campus_dir = broken_campus("pois.csv", lambda rows: [r for r in rows if r[0] != "poi_eA1"])
    bA = next(b for b in get(campus_dir.parent, "/campuses/tiny-campus/buildings").json() if b["id"] == "bA")
    assert {e["node_id"]: e["name"] for e in bA["entrances"]} == {"eA1": None, "eA2": "Building A (North Entrance)"}


def test_buildings_per_campus_url(tmp_path, tiny_campus):
    copy_campus(tiny_campus, tmp_path, "tiny-campus")
    second = copy_campus(tiny_campus, tmp_path, "second-campus")
    rows = (second / "buildings.csv").read_text().replace("Building B", "Second B")
    (second / "buildings.csv").write_text(rows)
    client = TestClient(create_app(tmp_path))
    names = lambda cid: {b["id"]: b["name"] for b in client.get(f"/campuses/{cid}/buildings").json()}
    assert names("tiny-campus")["bB"] == "Building B"
    assert names("second-campus")["bB"] == "Second B"


# --- GET /campuses/{id}/search ---

def test_search_unknown_campus_404(data_root):
    assert get(data_root, "/campuses/nope/search?q=building").status_code == 404


def test_search_missing_q_422(data_root):
    assert get(data_root, "/campuses/tiny-campus/search").status_code == 422


@pytest.mark.parametrize("q", ["", "%20%20"])
def test_search_blank_q_gives_empty_list(data_root, q):
    res = get(data_root, f"/campuses/tiny-campus/search?q={q}")
    assert res.status_code == 200
    assert res.json() == []


def test_search_results_pass_through(data_root):
    res = get(data_root, "/campuses/tiny-campus/search?q=building")
    assert res.json() == [
        {"kind": "building", "id": "bA", "name": "Building A", "building_id": "bA"},
        {"kind": "building", "id": "bB", "name": "Building B", "building_id": "bB"},
    ]


def test_search_door_name_finds_building(data_root):
    res = get(data_root, "/campuses/tiny-campus/search?q=north%20entrance")
    assert [r["id"] for r in res.json()] == ["bA"]


def test_search_limit(data_root):
    res = get(data_root, "/campuses/tiny-campus/search?q=building&limit=1")
    assert [r["id"] for r in res.json()] == ["bA"]


@pytest.mark.parametrize("limit", ["0", "-1", "101", "abc"])
def test_search_bad_limit_422(data_root, limit):
    assert get(data_root, f"/campuses/tiny-campus/search?q=building&limit={limit}").status_code == 422


# --- GET /campuses/{id}/route ---

AT_W1 = "lat=42.0005&lon=-71.0005"   # exactly on node w1, so approach_m is 0


def route_url(params, campus="tiny-campus"):
    return f"/campuses/{campus}/route?{params}"


def test_route_walk_to_building_picks_best_entrance(data_root):
    res = get(data_root, route_url(f"{AT_W1}&to_building=bA"))
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["entrance_id"] == "eA1"
    assert body["entrance_name"] == "Building A (South Entrance)"
    assert body["building_id"] == "bA"
    assert body["coords"] == [[42.0005, -71.0005], [42.0009, -71.0005]]
    assert body["distance_m"] == pytest.approx(44.5)
    assert body["approach_m"] == pytest.approx(0, abs=1e-6)
    assert body["duration_s"] == pytest.approx(44.5 / 1.4)
    assert set(body) == {"status", "coords", "distance_m", "approach_m", "duration_s",
                         "entrance_id", "entrance_name", "building_id"}


def test_route_to_poi_walk_takes_steps_wheelchair_avoids_them(data_root):
    walk = get(data_root, route_url(f"{AT_W1}&to_poi=poi_eA2")).json()
    chair = get(data_root, route_url(f"{AT_W1}&to_poi=poi_eA2&mode=wheelchair")).json()
    assert walk["entrance_id"] == chair["entrance_id"] == "eA2"
    assert walk["distance_m"] == pytest.approx(240.0 + 93.7)            # w1 -steps- w3 - eA2
    assert chair["distance_m"] == pytest.approx(82.8 + 222.4 + 93.7)    # w1 - w2 - w3 - eA2
    assert len(chair["coords"]) == 4


def test_route_no_entrances(data_root):
    body = get(data_root, route_url(f"{AT_W1}&to_building=bB")).json()
    assert body == {"status": "no_route", "reason": "no_entrances", "distance_m": None}


def test_route_too_far(data_root):
    body = get(data_root, route_url("lat=42.1&lon=-71.0&to_building=bA")).json()
    assert body["status"] == "no_route" and body["reason"] == "too_far"
    assert body["distance_m"] > 200


def test_route_no_path_from_island(data_root):
    body = get(data_root, route_url("lat=42.0050&lon=-71.0050&to_building=bA")).json()
    assert body == {"status": "no_route", "reason": "no_path", "distance_m": None}


def test_route_no_usable_edge_gives_null_distance(broken_campus):
    # every edge inaccessible: wheelchair snapping finds nothing at all -> TooFar(inf) -> null
    campus_dir = broken_campus("edges.csv", lambda rows: [rows[0]] + [r[:5] + ["False"] for r in rows[1:]])
    res = get(campus_dir.parent, route_url(f"{AT_W1}&to_building=bA&mode=wheelchair"))
    assert res.status_code == 200
    assert res.json() == {"status": "no_route", "reason": "too_far", "distance_m": None}


@pytest.mark.parametrize("params, detail", [
    (f"{AT_W1}&to_building=nope", "unknown building 'nope'"),
    (f"{AT_W1}&to_building=ba", "unknown building 'ba'"),   # case-sensitive
    (f"{AT_W1}&to_poi=nope", "unknown poi 'nope'"),
])
def test_route_unknown_target_404(data_root, params, detail):
    res = get(data_root, route_url(params))
    assert res.status_code == 404
    assert res.json() == {"detail": detail}


def test_route_unknown_campus_404(data_root):
    assert get(data_root, route_url(f"{AT_W1}&to_building=bA", campus="nope")).status_code == 404


@pytest.mark.parametrize("params", [
    f"{AT_W1}",                                  # neither target
    f"{AT_W1}&to_building=bA&to_poi=poi_eA1",    # both
    f"{AT_W1}&to_building=bA&mode=distance",     # "distance" is the cost fn, not a mode
    f"{AT_W1}&to_building=bA&mode=fly",
])
def test_route_bad_request_400(data_root, params):
    res = get(data_root, route_url(params))
    assert res.status_code == 400
    assert "detail" in res.json()


@pytest.mark.parametrize("params", [
    "lon=-71.0005&to_building=bA",           # missing lat
    "lat=91&lon=-71.0005&to_building=bA",
    "lat=42&lon=-181&to_building=bA",
    "lat=42&lon=abc&to_building=bA",
    "lat=nan&lon=-71.0005&to_building=bA",
])
def test_route_bad_coords_422(data_root, params):
    assert get(data_root, route_url(params)).status_code == 422

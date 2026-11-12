import json
import shutil
from pathlib import Path

import pytest

from conftest import copy_campus
from loader import (
    BUILDING_COLS, Campus, LoadError, check_latlon, distance_to_bbox_m, load_all, load_campus, check_one_of, load_buildings, load_edges, load_nodes, load_pois, read_rows,
    require, to_bool_or_none, to_float, to_int,
)


def set_cell(line, col, value):
    """An edit for broken_campus: set column `col` on file line `line` (header = 1)."""
    def edit(rows):
        rows[line - 1][rows[0].index(col)] = value
        return rows
    return edit


REAL_DATA = Path(__file__).parents[2] / "data"

SQUARE = [[-71.001, 42.001], [-71.0, 42.001], [-71.0, 42.002], [-71.001, 42.002], [-71.001, 42.001]]


# --- LoadError ---

def test_load_error_format_with_row():
    assert str(LoadError("edges.csv", 5, "bad cost")) == "edges.csv:5: bad cost"


def test_load_error_format_without_row():
    assert str(LoadError("edges.csv", None, "file not found")) == "edges.csv: file not found"


# --- read_rows ---

def test_read_rows_yields_line_numbers_from_2(tiny_campus):
    rows = list(read_rows(tiny_campus / "buildings.csv", BUILDING_COLS))
    assert [n for n, _ in rows] == [2, 3]
    assert rows[0][1]["building_id"] == "bA"


def test_read_rows_missing_file(tmp_path):
    with pytest.raises(LoadError, match="buildings.csv: file not found"):
        list(read_rows(tmp_path / "buildings.csv", BUILDING_COLS))


def test_read_rows_missing_column_names_file_and_column(broken_campus):
    campus_dir = broken_campus("buildings.csv", lambda rows: [r[1:] for r in rows])
    with pytest.raises(LoadError, match="buildings.csv: missing columns: building_id"):
        list(read_rows(campus_dir / "buildings.csv", BUILDING_COLS))


def test_read_rows_extra_column_is_ignored(broken_campus):
    campus_dir = broken_campus("buildings.csv", lambda rows: [r + ["extra"] for r in rows])
    rows = list(read_rows(campus_dir / "buildings.csv", BUILDING_COLS))
    assert len(rows) == 2


def test_read_rows_short_row_raises_with_line_number(broken_campus):
    def drop_last_cell_of_line_3(rows):
        rows[2] = rows[2][:-1]
        return rows

    campus_dir = broken_campus("buildings.csv", drop_last_cell_of_line_3)
    with pytest.raises(LoadError, match="buildings.csv:3: expected 3 cells, got 2"):
        list(read_rows(campus_dir / "buildings.csv", BUILDING_COLS))


def test_read_rows_trims_cells(broken_campus):
    campus_dir = broken_campus("buildings.csv", lambda rows: [[f"  {c} " for c in r] for r in rows])
    _, row = next(read_rows(campus_dir / "buildings.csv", BUILDING_COLS))
    assert row["building_id"] == "bA"
    assert row["name"] == "Building A"


# --- converters ---

def test_to_float_valid():
    assert to_float("6.36", "f.csv", 2, "cost") == 6.36


@pytest.mark.parametrize("val", ["", "abc", "nan", "inf"])
def test_to_float_invalid(val):
    with pytest.raises(LoadError, match="f.csv:2: cost"):
        to_float(val, "f.csv", 2, "cost")


def test_to_int_valid():
    assert to_int("0", "f.csv", 2, "floor") == 0


@pytest.mark.parametrize("val", ["", "1.5", "abc"])
def test_to_int_invalid(val):
    with pytest.raises(LoadError, match="f.csv:2: floor"):
        to_int(val, "f.csv", 2, "floor")


@pytest.mark.parametrize("val, expected", [("True", True), ("False", False), ("", None)])
def test_to_bool_or_none_valid(val, expected):
    assert to_bool_or_none(val, "f.csv", 2, "accessible") is expected


@pytest.mark.parametrize("val", ["true", "false", "yes", "1", "0", "Ture"])
def test_to_bool_or_none_invalid(val):
    with pytest.raises(LoadError, match="f.csv:2: accessible"):
        to_bool_or_none(val, "f.csv", 2, "accessible")


def test_check_one_of_valid():
    assert check_one_of("meters", {"meters"}, "f.csv", 2, "cost_unit") == "meters"


def test_check_one_of_invalid_lists_allowed_values():
    with pytest.raises(LoadError, match=r"cost_unit must be one of \['meters'\], got 'feet'"):
        check_one_of("feet", {"meters"}, "f.csv", 2, "cost_unit")


def test_require_valid():
    assert require("bA", "f.csv", 2, "building_id") == "bA"


def test_require_empty_raises():
    with pytest.raises(LoadError, match="f.csv:2: building_id is required"):
        require("", "f.csv", 2, "building_id")


# --- load_buildings ---

def test_load_buildings_fixture(tiny_campus):
    buildings = load_buildings(tiny_campus)
    assert set(buildings) == {"bA", "bB"}
    assert buildings["bA"].name == "Building A"
    assert buildings["bA"].geometry["type"] == "Polygon"


def test_load_buildings_accepts_multipolygon(broken_campus):
    geom = {"type": "MultiPolygon", "coordinates": [[SQUARE], [SQUARE]]}
    campus_dir = broken_campus("buildings.csv", set_cell(2, "polygon_geojson", json.dumps(geom)))
    assert load_buildings(campus_dir)["bA"].geometry["type"] == "MultiPolygon"


def test_load_buildings_accepts_polygon_with_hole(broken_campus):
    hole = [[-71.0008, 42.0012], [-71.0002, 42.0012], [-71.0002, 42.0018], [-71.0008, 42.0012]]
    geom = {"type": "Polygon", "coordinates": [SQUARE, hole]}
    campus_dir = broken_campus("buildings.csv", set_cell(2, "polygon_geojson", json.dumps(geom)))
    assert len(load_buildings(campus_dir)["bA"].geometry["coordinates"]) == 2


def test_load_buildings_accepts_altitude(broken_campus):
    geom = {"type": "Polygon", "coordinates": [[p + [10.0] for p in SQUARE]]}
    campus_dir = broken_campus("buildings.csv", set_cell(2, "polygon_geojson", json.dumps(geom)))
    assert "bA" in load_buildings(campus_dir)


@pytest.mark.parametrize("col, value, message", [
    ("building_id", "", "building_id is required"),
    ("name", "", "name is required"),
    ("polygon_geojson", "", "polygon_geojson is required"),
    ("polygon_geojson", "{not json", "polygon_geojson is not valid JSON"),
])
def test_load_buildings_bad_cells(broken_campus, col, value, message):
    campus_dir = broken_campus("buildings.csv", set_cell(2, col, value))
    with pytest.raises(LoadError, match=f"buildings.csv:2: {message}"):
        load_buildings(campus_dir)


def test_load_buildings_duplicate_id_reports_second_row(broken_campus):
    campus_dir = broken_campus("buildings.csv", set_cell(3, "building_id", "bA"))
    with pytest.raises(LoadError, match="buildings.csv:3: duplicate building_id 'bA'"):
        load_buildings(campus_dir)


@pytest.mark.parametrize("geom, message", [
    ({"type": "Point", "coordinates": [-71.0, 42.0]}, "type must be one of"),
    ([SQUARE], "type must be one of"),
    ({"type": "Polygon"}, "each polygon must be a non-empty list of rings"),
    ({"type": "MultiPolygon", "coordinates": []}, "coordinates must be a non-empty list"),
    ({"type": "Polygon", "coordinates": [SQUARE[:2] + [SQUARE[0]]]}, "each ring must have at least 4 points"),
    ({"type": "Polygon", "coordinates": [SQUARE[:-1] + [[-71.0005, 42.001]]]}, "ring is not closed"),
    ({"type": "Polygon", "coordinates": [[["-71.0", 42.0]] + SQUARE]}, "point must be"),
    ({"type": "Polygon", "coordinates": [[[-71.0]] + SQUARE]}, "point must be"),
    ({"type": "Polygon", "coordinates": [[[-71.0, 95.0], [-71.0, 42.0], [-71.1, 42.0], [-71.0, 95.0]]]}, r"point \[-71.0, 95.0\]: out of lat/lon range"),
])
def test_load_buildings_bad_geometry(broken_campus, geom, message):
    campus_dir = broken_campus("buildings.csv", set_cell(2, "polygon_geojson", json.dumps(geom)))
    with pytest.raises(LoadError, match=f"buildings.csv:2: polygon_geojson: {message}"):
        load_buildings(campus_dir)


def test_load_buildings_real_northeastern():
    buildings = load_buildings(REAL_DATA / "northeastern-boston")
    assert len(buildings) == 104
    assert buildings["se"].geometry["type"] == "MultiPolygon"


def test_check_latlon_valid():
    check_latlon(42.0, -71.0, "f.csv", 2, "coords")


@pytest.mark.parametrize("lat, lon", [(95.0, -71.0), (-90.1, 0.0), (42.0, 181.0), (42.0, -180.5)])
def test_check_latlon_invalid(lat, lon):
    with pytest.raises(LoadError, match="f.csv:2: coords: out of lat/lon range"):
        check_latlon(lat, lon, "f.csv", 2, "coords")


# --- load_nodes ---
# nodes.csv fixture lines: 2 eA1, 3 eA2, 4 w1, 5 w2, 6 w3, 7 i1, 8 i2

def load_fixture_nodes(campus_dir):
    return load_nodes(campus_dir, load_buildings(campus_dir))


def test_load_nodes_fixture(tiny_campus):
    nodes, entrances = load_fixture_nodes(tiny_campus)
    assert len(nodes) == 7
    assert entrances == {"bA": ["eA1", "eA2"]}
    assert nodes["w1"].building_id is None
    assert nodes["eA1"].floor == 0
    assert nodes["eA1"].x_or_lat == 42.0009 and nodes["eA1"].y_or_lon == -71.0005


@pytest.mark.parametrize("line, col, value", [
    (4, "floor", "-1"),          # basement
    (4, "building_id", "bB"),    # waypoint inside a building
    (2, "floor", "2"),           # entrance not on floor 0
    (4, "type", "gate"),         # open type set
])
def test_load_nodes_accepts(broken_campus, line, col, value):
    nodes, _ = load_fixture_nodes(broken_campus("nodes.csv", set_cell(line, col, value)))
    assert len(nodes) == 7


def test_load_nodes_non_entrance_type_is_not_indexed(broken_campus):
    _, entrances = load_fixture_nodes(broken_campus("nodes.csv", set_cell(2, "type", "gate")))
    assert entrances == {"bA": ["eA2"]}


@pytest.mark.parametrize("line, col, value, message", [
    (2, "node_id", "", "node_id is required"),
    (3, "node_id", "eA1", "duplicate node_id 'eA1'"),
    (4, "node_id", "__start__", "node_id must not start with '__'"),
    (2, "campus_id", "", "campus_id is required"),
    (2, "campus_id", "other-campus", "campus_id must match folder 'tiny-campus', got 'other-campus'"),
    (2, "building_id", "bZ", "unknown building_id 'bZ'"),
    (2, "floor", "1.5", "floor must be an integer"),
    (2, "coord_system", "local", "coord_system must be one of"),
    (2, "x_or_lat", "abc", "x_or_lat must be a number"),
    (2, "y_or_lon", "", "y_or_lon must be a number"),
    (2, "x_or_lat", "95", "x_or_lat/y_or_lon: out of lat/lon range"),
    (4, "type", "", "type is required"),
    (2, "building_id", "", "entrance must have a building_id"),
])
def test_load_nodes_rejects(broken_campus, line, col, value, message):
    campus_dir = broken_campus("nodes.csv", set_cell(line, col, value))
    with pytest.raises(LoadError, match=f"nodes.csv:{line}: {message}"):
        load_fixture_nodes(campus_dir)


def test_load_nodes_real_northeastern():
    campus_dir = REAL_DATA / "northeastern-boston"
    nodes, entrances = load_nodes(campus_dir, load_buildings(campus_dir))
    assert len(nodes) == 2060
    assert sum(len(ids) for ids in entrances.values()) == 82
    assert len(entrances) == 59


# --- load_edges ---
# edges.csv fixture lines: 2 eA1-w1, 3 w1-w2, 4 w2-w3, 5 w3-eA2, 6 w1-w3 (steps, False), 7 i1-i2

def load_fixture_edges(campus_dir):
    nodes, _ = load_fixture_nodes(campus_dir)
    return load_edges(campus_dir, nodes)


def append_row(row):
    return lambda rows: rows + [row]


def test_load_edges_fixture(tiny_campus):
    adjacency = load_fixture_edges(tiny_campus)
    assert set(adjacency) == {"eA1", "eA2", "w1", "w2", "w3", "i1", "i2"}
    assert sum(len(v) for v in adjacency.values()) == 12
    assert [n for n, _ in adjacency["i1"]] == ["i2"]
    steps = next(e for n, e in adjacency["w1"] if n == "w3")
    assert steps.accessible is False and steps.edge_type == "steps" and steps.cost == 240.0


def test_load_edges_symmetric(tiny_campus):
    adjacency = load_fixture_edges(tiny_campus)
    for a, entries in adjacency.items():
        for b, edge in entries:
            assert (a, edge) in adjacency[b]


def test_load_edges_node_without_edges_has_empty_list(broken_campus):
    campus_dir = broken_campus("edges.csv", lambda rows: rows[:-1])  # drop i1-i2
    adjacency = load_fixture_edges(campus_dir)
    assert adjacency["i1"] == [] and adjacency["i2"] == []


@pytest.mark.parametrize("col, value, attr, expected", [
    ("cost", "0", "cost", 0.0),
    ("edge_type", "", "edge_type", None),
    ("edge_type", "boardwalk", "edge_type", "boardwalk"),
    ("accessible", "", "accessible", None),
])
def test_load_edges_accepts(broken_campus, col, value, attr, expected):
    adjacency = load_fixture_edges(broken_campus("edges.csv", set_cell(2, col, value)))
    edge = next(e for n, e in adjacency["eA1"] if n == "w1")
    assert getattr(edge, attr) == expected


def test_load_edges_parallel_edges_both_kept(broken_campus):
    # an accessible ramp beside the steps edge w1-w3
    campus_dir = broken_campus("edges.csv", append_row(["w3", "w1", "260.0", "meters", "footway", "True"]))
    adjacency = load_fixture_edges(campus_dir)
    to_w3 = [e for n, e in adjacency["w1"] if n == "w3"]
    assert sorted(e.accessible for e in to_w3) == [False, True]


@pytest.mark.parametrize("line, col, value, message", [
    (2, "from_node", "", "from_node is required"),
    (2, "to_node", "", "to_node is required"),
    (2, "from_node", "zz", "unknown from_node 'zz'"),
    (2, "to_node", "zz", "unknown to_node 'zz'"),
    (2, "to_node", "eA1", "self-loop on 'eA1'"),
    (2, "cost", "-1", "cost must be >= 0"),
    (2, "cost", "abc", "cost must be a number"),
    (2, "cost_unit", "feet", "cost_unit must be one of"),
    (2, "accessible", "yes", "accessible must be True, False, or empty"),
])
def test_load_edges_rejects(broken_campus, line, col, value, message):
    campus_dir = broken_campus("edges.csv", set_cell(line, col, value))
    with pytest.raises(LoadError, match=f"edges.csv:{line}: {message}"):
        load_fixture_edges(campus_dir)


@pytest.mark.parametrize("row", [
    ["w1", "w3", "240.0", "meters", "steps", "False"],   # same direction
    ["w3", "w1", "240.0", "meters", "steps", "False"],   # reversed
])
def test_load_edges_rejects_exact_duplicate(broken_campus, row):
    campus_dir = broken_campus("edges.csv", append_row(row))
    with pytest.raises(LoadError, match="edges.csv:8: exact duplicate of the edge on row 6"):
        load_fixture_edges(campus_dir)


def test_load_edges_real_northeastern():
    campus_dir = REAL_DATA / "northeastern-boston"
    nodes, _ = load_nodes(campus_dir, load_buildings(campus_dir))
    adjacency = load_edges(campus_dir, nodes)
    assert sum(len(v) for v in adjacency.values()) == 2 * 2727


# --- load_pois ---
# pois.csv fixture lines: 2 poi_eA1 (node eA1, bA), 3 poi_eA2 (node eA2, bA)

def load_fixture_pois(campus_dir):
    buildings = load_buildings(campus_dir)
    nodes, _ = load_nodes(campus_dir, buildings)
    return load_pois(campus_dir, nodes, buildings)


def test_load_pois_fixture(tiny_campus):
    pois = load_fixture_pois(tiny_campus)
    assert set(pois) == {"poi_eA1", "poi_eA2"}
    poi = pois["poi_eA1"]
    assert poi.node_id == "eA1" and poi.building_id == "bA"
    assert poi.floor == 0 and poi.accessible is True
    assert poi.category == "entrance" and poi.notes is None


@pytest.mark.parametrize("col", ["category", "building_id", "floor", "accessible", "notes"])
def test_load_pois_optional_fields_empty_become_none(broken_campus, col):
    pois = load_fixture_pois(broken_campus("pois.csv", set_cell(2, col, "")))
    assert getattr(pois["poi_eA1"], col) is None


@pytest.mark.parametrize("line, col, value, attr, expected", [
    (3, "node_id", "eA1", "node_id", "eA1"),             # two POIs on one node
    (3, "name", "Building A (South Entrance)", "name", "Building A (South Entrance)"),  # duplicate name
    (2, "floor", "-1", "floor", -1),
    (2, "floor", "3", "floor", 3),                      # floor not checked against node's
    (2, "category", "restroom", "category", "restroom"),  # open category
])
def test_load_pois_accepts(broken_campus, line, col, value, attr, expected):
    pois = load_fixture_pois(broken_campus("pois.csv", set_cell(line, col, value)))
    poi_id = "poi_eA1" if line == 2 else "poi_eA2"
    assert getattr(pois[poi_id], attr) == expected


def test_load_pois_building_poi_on_outdoor_node(broken_campus):
    # e.g. a room labelled on a waypoint: the node has no building, so no mismatch
    campus_dir = broken_campus("pois.csv", set_cell(2, "node_id", "w1"))
    assert load_fixture_pois(campus_dir)["poi_eA1"].building_id == "bA"


@pytest.mark.parametrize("line, col, value, message", [
    (2, "poi_id", "", "poi_id is required"),
    (3, "poi_id", "poi_eA1", "duplicate poi_id 'poi_eA1'"),
    (2, "node_id", "", "node_id is required"),
    (2, "node_id", "zz", "unknown node_id 'zz'"),
    (2, "name", "", "name is required"),
    (2, "building_id", "bZ", "unknown building_id 'bZ'"),
    (2, "building_id", "bB", "building_id 'bB' doesn't match node 'eA1''s building 'bA'"),
    (2, "floor", "1.5", "floor must be an integer"),
    (2, "accessible", "yes", "accessible must be True, False, or empty"),
])
def test_load_pois_rejects(broken_campus, line, col, value, message):
    campus_dir = broken_campus("pois.csv", set_cell(line, col, value))
    with pytest.raises(LoadError, match=f"pois.csv:{line}: {message}"):
        load_fixture_pois(campus_dir)


def test_load_pois_real_northeastern():
    pois = load_fixture_pois(REAL_DATA / "northeastern-boston")
    assert len(pois) == 82


# --- load_campus / Campus ---

def test_load_campus_fixture(tiny_campus):
    campus = load_campus(tiny_campus)
    assert isinstance(campus, Campus) and campus.id == "tiny-campus"
    assert (len(campus.buildings), len(campus.nodes), len(campus.pois)) == (2, 7, 2)
    assert sum(len(v) for v in campus.adjacency.values()) == 12
    assert campus.entrances_for("bA") == ("eA1", "eA2")


def test_entrances_for_building_without_entrances(tiny_campus):
    assert load_campus(tiny_campus).entrances_for("bB") == ()


def test_entrances_for_unknown_building_raises(tiny_campus):
    with pytest.raises(KeyError):
        load_campus(tiny_campus).entrances_for("bZ")


def test_campus_is_read_only(tiny_campus):
    campus = load_campus(tiny_campus)
    with pytest.raises(AttributeError):
        campus.id = "other"
    with pytest.raises(TypeError):
        campus.nodes["new"] = campus.nodes["w1"]
    with pytest.raises(AttributeError):
        campus.adjacency["w1"].append(("w2", None))  # tuples have no append


def test_load_campus_errors_name_campus_and_file(broken_campus):
    campus_dir = broken_campus("edges.csv", set_cell(2, "cost", "-1"))
    with pytest.raises(LoadError, match="tiny-campus/edges.csv:2: cost must be >= 0"):
        load_campus(campus_dir)


@pytest.mark.parametrize("name", ["Bad Name", "UPPER", "under_score", "-leading", "double--hyphen"])
def test_load_campus_rejects_bad_folder_name(tmp_path, tiny_campus, name):
    shutil.copytree(tiny_campus, tmp_path / name)
    with pytest.raises(LoadError, match="campus folder name must be"):
        load_campus(tmp_path / name)


# --- cross-file checks ---

def test_distance_to_bbox_inside_is_zero():
    assert distance_to_bbox_m(42.0015, -71.0005, (42.001, 42.002, -71.001, -71.0)) == 0


def test_distance_to_bbox_outside():
    # 0.001 deg of latitude is ~111 m
    assert distance_to_bbox_m(42.003, -71.0005, (42.001, 42.002, -71.001, -71.0)) == pytest.approx(111, abs=1)


def shifted_square(dlat):
    return json.dumps({"type": "Polygon", "coordinates": [[[lon, lat + dlat] for lon, lat in SQUARE]]})


def test_swap_check_rejects_swapped_building(broken_campus):
    swapped = json.dumps({"type": "Polygon", "coordinates": [[[lat, lon] for lon, lat in SQUARE]]})
    campus_dir = broken_campus("buildings.csv", set_cell(2, "polygon_geojson", swapped))
    with pytest.raises(LoadError, match=r"tiny-campus/buildings.csv: building 'bA' is [\d,]+ km .*lat/lon swapped"):
        load_campus(campus_dir)


def test_swap_check_rejects_swapped_nodes(broken_campus):
    def swap_coords(rows):
        lat, lon = rows[0].index("x_or_lat"), rows[0].index("y_or_lon")
        for r in rows[1:]:
            r[lat], r[lon] = r[lon], r[lat]
        return rows
    with pytest.raises(LoadError, match="lat/lon swapped"):
        load_campus(broken_campus("nodes.csv", swap_coords))


def test_swap_check_allows_satellite_building(broken_campus):
    # bB moved ~5 km north, like an off-campus boathouse; it has no entrances
    campus_dir = broken_campus("buildings.csv", set_cell(3, "polygon_geojson", shifted_square(0.045)))
    assert "bB" in load_campus(campus_dir).buildings


def test_entrance_check_rejects_far_entrance(broken_campus):
    # eA1 moved to lat 41.9982: ~310 m south of bA's bbox (lat 42.001-42.002)
    campus_dir = broken_campus("nodes.csv", set_cell(2, "x_or_lat", "41.9982"))
    with pytest.raises(LoadError, match=r"tiny-campus/nodes.csv: entrance 'eA1' is [\d,]+ m from its building 'bA'"):
        load_campus(campus_dir)


def test_entrance_check_allows_nearby_entrance(broken_campus):
    # ~50 m south of bA's bbox
    campus_dir = broken_campus("nodes.csv", set_cell(2, "x_or_lat", "42.00055"))
    assert load_campus(campus_dir).entrances_for("bA") == ("eA1", "eA2")


# --- load_all ---

def test_load_all_multiple_campuses(tmp_path, tiny_campus):
    copy_campus(tiny_campus, tmp_path, "tiny-campus")
    copy_campus(tiny_campus, tmp_path, "second-campus")
    campuses = load_all(tmp_path)
    assert list(campuses) == ["second-campus", "tiny-campus"]
    assert campuses["second-campus"].nodes["w1"].campus_id == "second-campus"


def test_load_all_skips_hidden_folders_and_files(tmp_path, tiny_campus):
    copy_campus(tiny_campus, tmp_path, "tiny-campus")
    (tmp_path / ".cache").mkdir()
    (tmp_path / ".DS_Store").write_text("")
    assert list(load_all(tmp_path)) == ["tiny-campus"]


def test_load_all_raises_on_any_bad_campus(broken_campus, tiny_campus):
    campus_dir = broken_campus("pois.csv", set_cell(2, "node_id", "zz"))
    copy_campus(tiny_campus, campus_dir.parent, "good-campus")
    with pytest.raises(LoadError, match="tiny-campus/pois.csv:2: unknown node_id 'zz'"):
        load_all(campus_dir.parent)


def test_load_all_campus_missing_a_file(tmp_path, tiny_campus):
    copy_campus(tiny_campus, tmp_path, "tiny-campus")
    (tmp_path / "tiny-campus" / "pois.csv").unlink()
    with pytest.raises(LoadError, match="tiny-campus/pois.csv: file not found"):
        load_all(tmp_path)


def test_load_all_empty_root_raises(tmp_path):
    with pytest.raises(LoadError, match="no campus folders found"):
        load_all(tmp_path)


def test_load_all_missing_root_raises(tmp_path):
    with pytest.raises(LoadError, match="data folder not found"):
        load_all(tmp_path / "nope")


def test_load_all_real_data():
    campus = load_all(REAL_DATA)["northeastern-boston"]
    assert (len(campus.buildings), len(campus.nodes), len(campus.pois)) == (104, 2060, 82)
    assert len(campus.entrances_by_building) == 59
    assert sum(len(v) for v in campus.adjacency.values()) == 2 * 2727
    assert campus.nodes["entrance_ff41500c-c189-48c6-9e53-7bed42cce8af"].building_id == "sn"

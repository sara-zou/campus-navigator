import json
from pathlib import Path

import pytest

from loader import (
    BUILDING_COLS, LoadError, check_latlon, check_one_of, load_buildings, load_edges, load_nodes, read_rows,
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

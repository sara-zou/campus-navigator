"""Load every data/{campus_id}/ folder into an in-memory Campus, validating as it goes.

One pass per file: read a row, check it, convert it, store it. Any bad row raises
LoadError naming the file and row; a campus is only built once all its files pass.
"""
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path

BUILDING_COLS = ["building_id", "name", "polygon_geojson"]
GEOMETRY_TYPES = {"Polygon", "MultiPolygon"}

NODE_COLS = ["node_id", "campus_id", "building_id", "floor", "coord_system", "x_or_lat", "y_or_lon", "type"]
COORD_SYSTEMS = {"latlon"}  # "local" (indoor x/y) gets added with indoor support


@dataclass(frozen=True)
class Building:
    id: str
    name: str
    geometry: dict  # parsed GeoJSON Polygon or MultiPolygon, [lon, lat] order


@dataclass(frozen=True)
class Node:
    id: str
    campus_id: str
    building_id: str | None  # None for outdoor waypoints
    floor: int               # integer index; negatives are basements
    coord_system: str
    x_or_lat: float
    y_or_lon: float
    type: str                # open set; only "entrance" has special rules


class LoadError(Exception):
    """A data file broke the contract. `row` is the line number (header = 1), or None for file-level errors."""

    def __init__(self, file, row, msg):
        self.file, self.row, self.msg = file, row, msg
        where = file if row is None else f"{file}:{row}"
        super().__init__(f"{where}: {msg}")


# --- row helpers ---

def read_rows(path, required_cols):
    """Yield (row_num, row_dict) for each data row, with every cell trimmed.

    Raises if the file is missing, the header lacks a required column, or a row
    has the wrong number of cells. Extra columns are allowed and ignored.
    """
    path = Path(path)
    file = path.name
    if not path.is_file():
        raise LoadError(file, None, "file not found")

    # utf-8-sig drops the BOM that Excel adds when saving CSVs
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = [h.strip() for h in next(reader, [])]
        missing = [c for c in required_cols if c not in header]
        if missing:
            raise LoadError(file, None, f"missing columns: {', '.join(missing)}")

        for row_num, cells in enumerate(reader, start=2):
            if not cells:  # blank line, e.g. a trailing newline
                continue
            if len(cells) != len(header):
                raise LoadError(file, row_num, f"expected {len(header)} cells, got {len(cells)}")
            yield row_num, {col: cell.strip() for col, cell in zip(header, cells)}


def require(val, file, row, col):
    if val == "":
        raise LoadError(file, row, f"{col} is required")
    return val


def to_float(val, file, row, col):
    try:
        x = float(val)
    except ValueError:
        raise LoadError(file, row, f"{col} must be a number, got {val!r}") from None
    if not math.isfinite(x):
        raise LoadError(file, row, f"{col} must be a finite number, got {val!r}")
    return x


def to_int(val, file, row, col):
    try:
        return int(val)
    except ValueError:
        raise LoadError(file, row, f"{col} must be an integer, got {val!r}") from None


def to_bool_or_none(val, file, row, col):
    """'True' -> True, 'False' -> False, '' -> None (unknown). Anything else raises."""
    if val == "True":
        return True
    if val == "False":
        return False
    if val == "":
        return None
    raise LoadError(file, row, f"{col} must be True, False, or empty, got {val!r}")


def check_one_of(val, allowed, file, row, col):
    if val not in allowed:
        raise LoadError(file, row, f"{col} must be one of {sorted(allowed)}, got {val!r}")
    return val


def check_latlon(lat, lon, file, row, label):
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise LoadError(file, row, f"{label}: out of lat/lon range (lat={lat}, lon={lon})")


# --- buildings ---

def check_geometry(geom, file, row):
    """Raise unless geom is a well-formed GeoJSON Polygon or MultiPolygon with valid lon/lat points."""
    def fail(msg):
        raise LoadError(file, row, f"polygon_geojson: {msg}")

    if not isinstance(geom, dict) or geom.get("type") not in GEOMETRY_TYPES:
        fail(f"type must be one of {sorted(GEOMETRY_TYPES)}")
    coords = geom.get("coordinates")
    polygons = [coords] if geom["type"] == "Polygon" else coords
    if not isinstance(polygons, list) or not polygons:
        fail("coordinates must be a non-empty list")

    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            fail("each polygon must be a non-empty list of rings")
        for ring in polygon:
            if not isinstance(ring, list) or len(ring) < 4:
                fail("each ring must have at least 4 points")
            for point in ring:
                # GeoJSON allows an optional third value (altitude)
                if not (isinstance(point, list) and len(point) in (2, 3)
                        and all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in point)):
                    fail(f"point must be [lon, lat], got {point!r}")
                check_latlon(point[1], point[0], file, row, f"polygon_geojson: point {point!r}")
            if ring[0] != ring[-1]:
                fail("ring is not closed (first point must equal last)")


def load_buildings(campus_dir):
    file = "buildings.csv"
    buildings = {}
    for row, r in read_rows(Path(campus_dir) / file, BUILDING_COLS):
        building_id = require(r["building_id"], file, row, "building_id")
        if building_id in buildings:
            raise LoadError(file, row, f"duplicate building_id {building_id!r}")
        name = require(r["name"], file, row, "name")
        try:
            geometry = json.loads(require(r["polygon_geojson"], file, row, "polygon_geojson"))
        except json.JSONDecodeError as e:
            raise LoadError(file, row, f"polygon_geojson is not valid JSON: {e.msg}") from None
        check_geometry(geometry, file, row)
        buildings[building_id] = Building(building_id, name, geometry)
    return buildings


# --- nodes ---

def load_nodes(campus_dir, buildings):
    """Return (nodes by id, building_id -> [entrance node ids]). Buildings without entrances have no key."""
    file = "nodes.csv"
    expected_campus_id = Path(campus_dir).name
    nodes, entrances_by_building = {}, {}
    for row, r in read_rows(Path(campus_dir) / file, NODE_COLS):
        node_id = require(r["node_id"], file, row, "node_id")
        if node_id in nodes:
            raise LoadError(file, row, f"duplicate node_id {node_id!r}")

        campus_id = require(r["campus_id"], file, row, "campus_id")
        if campus_id != expected_campus_id:
            raise LoadError(file, row, f"campus_id must match folder {expected_campus_id!r}, got {campus_id!r}")

        building_id = r["building_id"] or None
        if building_id is not None and building_id not in buildings:
            raise LoadError(file, row, f"unknown building_id {building_id!r}")

        floor = to_int(r["floor"], file, row, "floor")
        coord_system = check_one_of(r["coord_system"], COORD_SYSTEMS, file, row, "coord_system")
        x = to_float(r["x_or_lat"], file, row, "x_or_lat")
        y = to_float(r["y_or_lon"], file, row, "y_or_lon")
        if coord_system == "latlon":
            check_latlon(x, y, file, row, "x_or_lat/y_or_lon")

        node_type = require(r["type"], file, row, "type")
        if node_type == "entrance":
            if building_id is None:
                raise LoadError(file, row, "entrance must have a building_id")
            entrances_by_building.setdefault(building_id, []).append(node_id)

        nodes[node_id] = Node(node_id, campus_id, building_id, floor, coord_system, x, y, node_type)
    return nodes, entrances_by_building

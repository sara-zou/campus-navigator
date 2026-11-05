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


@dataclass(frozen=True)
class Building:
    id: str
    name: str
    geometry: dict  # parsed GeoJSON Polygon or MultiPolygon, [lon, lat] order


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
                lon, lat = point[0], point[1]
                if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                    fail(f"point out of lon/lat range: {point!r}")
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

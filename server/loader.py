"""Load every data/{campus_id}/ folder into an in-memory Campus, validating as it goes.

One pass per file: read a row, check it, convert it, store it. Any bad row raises
LoadError naming the file and row; a campus is only built once all its files pass.
"""
import csv
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

CAMPUS_ID_PATTERN = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")  # becomes /campuses/{id} in the API
SWAP_CHECK_M = 50_000     # building points must be this close to the nodes' bbox
ENTRANCE_MAX_M = 100      # entrances must be this close to their building's bbox

BUILDING_COLS = ["building_id", "name", "polygon_geojson"]
GEOMETRY_TYPES = {"Polygon", "MultiPolygon"}

NODE_COLS = ["node_id", "campus_id", "building_id", "floor", "coord_system", "x_or_lat", "y_or_lon", "type"]
COORD_SYSTEMS = {"latlon"}  # "local" (indoor x/y) gets added with indoor support

EDGE_COLS = ["from_node", "to_node", "cost", "cost_unit", "edge_type", "accessible"]
COST_UNITS = {"meters"}  # "seconds" gets added with indoor support

POI_COLS = ["poi_id", "node_id", "name", "category", "building_id", "floor", "accessible", "notes"]


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


@dataclass(frozen=True)
class Edge:
    from_node: str
    to_node: str
    cost: float
    cost_unit: str
    edge_type: str | None    # open set; None if not given
    accessible: bool | None  # None = unknown


@dataclass(frozen=True)
class POI:
    id: str
    node_id: str             # where routing goes; not part of the graph itself
    name: str
    category: str | None     # open set
    building_id: str | None
    floor: int | None        # the place's floor; may differ from its node's (e.g. a room reached via an entrance)
    accessible: bool | None  # the place itself (e.g. an accessible restroom), separate from edges
    notes: str | None


@dataclass(frozen=True)
class Campus:
    """One fully validated campus. Read-only: mappings are MappingProxyType, sequences are tuples."""
    id: str
    buildings: Mapping[str, Building]
    nodes: Mapping[str, Node]
    adjacency: Mapping[str, tuple[tuple[str, Edge], ...]]     # node_id -> ((neighbor_id, Edge), ...)
    entrances_by_building: Mapping[str, tuple[str, ...]]     # only buildings that have entrances
    pois: Mapping[str, POI]

    def entrances_for(self, building_id):
        """Entrance node ids for a building; () if it has none. KeyError if the building doesn't exist."""
        if building_id not in self.buildings:
            raise KeyError(building_id)
        return self.entrances_by_building.get(building_id, ())


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


# --- edges ---

def add_undirected(adjacency, edge):
    """The only place edge direction is decided: every edge is walkable both ways."""
    adjacency[edge.from_node].append((edge.to_node, edge))
    adjacency[edge.to_node].append((edge.from_node, edge))


def load_edges(campus_dir, nodes):
    """Return adjacency: node_id -> [(neighbor_id, Edge), ...]. Every node has a key, even with no edges.

    Parallel edges (same pair, different attributes) are allowed; exact duplicates are not.
    """
    file = "edges.csv"
    adjacency = {node_id: [] for node_id in nodes}
    seen = {}  # exact-duplicate key -> row it first appeared on
    for row, r in read_rows(Path(campus_dir) / file, EDGE_COLS):
        from_node = require(r["from_node"], file, row, "from_node")
        to_node = require(r["to_node"], file, row, "to_node")
        for col, node_id in (("from_node", from_node), ("to_node", to_node)):
            if node_id not in nodes:
                raise LoadError(file, row, f"unknown {col} {node_id!r}")
        if from_node == to_node:
            raise LoadError(file, row, f"self-loop on {from_node!r}")

        cost = to_float(r["cost"], file, row, "cost")
        if cost < 0:
            raise LoadError(file, row, f"cost must be >= 0, got {cost}")
        cost_unit = check_one_of(r["cost_unit"], COST_UNITS, file, row, "cost_unit")
        edge_type = r["edge_type"] or None
        accessible = to_bool_or_none(r["accessible"], file, row, "accessible")

        dup_key = (frozenset((from_node, to_node)), cost, cost_unit, edge_type, accessible)
        if dup_key in seen:
            raise LoadError(file, row, f"exact duplicate of the edge on row {seen[dup_key]}")
        seen[dup_key] = row

        add_undirected(adjacency, Edge(from_node, to_node, cost, cost_unit, edge_type, accessible))
    return adjacency


# --- POIs ---

def load_pois(campus_dir, nodes, buildings):
    """Return POIs by id. Several POIs may share a node, and names needn't be unique."""
    file = "pois.csv"
    pois = {}
    for row, r in read_rows(Path(campus_dir) / file, POI_COLS):
        poi_id = require(r["poi_id"], file, row, "poi_id")
        if poi_id in pois:
            raise LoadError(file, row, f"duplicate poi_id {poi_id!r}")

        node_id = require(r["node_id"], file, row, "node_id")
        if node_id not in nodes:
            raise LoadError(file, row, f"unknown node_id {node_id!r}")
        name = require(r["name"], file, row, "name")

        building_id = r["building_id"] or None
        if building_id is not None:
            if building_id not in buildings:
                raise LoadError(file, row, f"unknown building_id {building_id!r}")
            # Only checked when both have one: outdoor nodes may carry building POIs.
            node_building = nodes[node_id].building_id
            if node_building is not None and node_building != building_id:
                raise LoadError(file, row, f"building_id {building_id!r} doesn't match node "
                                           f"{node_id!r}'s building {node_building!r}")

        floor = to_int(r["floor"], file, row, "floor") if r["floor"] else None
        accessible = to_bool_or_none(r["accessible"], file, row, "accessible")

        pois[poi_id] = POI(poi_id, node_id, name, r["category"] or None, building_id,
                           floor, accessible, r["notes"] or None)
    return pois


# --- cross-file checks ---

def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlmb = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(a))


def geometry_latlons(geometry):
    """Every (lat, lon) point in a Polygon or MultiPolygon (GeoJSON stores [lon, lat])."""
    polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    return [(p[1], p[0]) for polygon in polygons for ring in polygon for p in ring]


def bbox(latlons):
    lats, lons = [p[0] for p in latlons], [p[1] for p in latlons]
    return min(lats), max(lats), min(lons), max(lons)


def distance_to_bbox_m(lat, lon, box):
    """Straight-line meters from a point to the nearest spot on a bbox (0 if inside)."""
    min_lat, max_lat, min_lon, max_lon = box
    return haversine_m(lat, lon, min(max(lat, min_lat), max_lat), min(max(lon, min_lon), max_lon))


def check_cross_file(buildings, nodes, entrances_by_building):
    # Lat/lon swap: a swapped file lands thousands of km away, so a generous
    # limit catches it without rejecting satellite buildings.
    node_latlons = [(n.x_or_lat, n.y_or_lon) for n in nodes.values() if n.coord_system == "latlon"]
    if node_latlons:
        node_box = bbox(node_latlons)
        for building in buildings.values():
            worst = max(distance_to_bbox_m(lat, lon, node_box) for lat, lon in geometry_latlons(building.geometry))
            if worst > SWAP_CHECK_M:
                raise LoadError("buildings.csv", None, f"building {building.id!r} is {worst / 1000:,.0f} km from "
                                                       "the campus's nodes (lat/lon swapped in buildings.csv or nodes.csv?)")

    # Entrance near its building: catches a wrong building_id on an entrance.
    for building_id, entrance_ids in entrances_by_building.items():
        building_box = bbox(geometry_latlons(buildings[building_id].geometry))
        for node_id in entrance_ids:
            node = nodes[node_id]
            if node.coord_system != "latlon":
                continue
            d = distance_to_bbox_m(node.x_or_lat, node.y_or_lon, building_box)
            if d > ENTRANCE_MAX_M:
                raise LoadError("nodes.csv", None, f"entrance {node_id!r} is {d:,.0f} m from its building "
                                                   f"{building_id!r} (wrong building_id?)")


# --- campus ---

def load_campus(campus_dir):
    """Load and validate one campus folder. Errors are prefixed with the campus folder name."""
    campus_dir = Path(campus_dir)
    campus_id = campus_dir.name
    if not CAMPUS_ID_PATTERN.fullmatch(campus_id):
        raise LoadError(campus_id, None, "campus folder name must be lowercase letters, digits, and single hyphens")
    try:
        buildings = load_buildings(campus_dir)
        nodes, entrances_by_building = load_nodes(campus_dir, buildings)
        adjacency = load_edges(campus_dir, nodes)
        pois = load_pois(campus_dir, nodes, buildings)
        check_cross_file(buildings, nodes, entrances_by_building)
    except LoadError as e:
        raise LoadError(f"{campus_id}/{e.file}", e.row, e.msg) from None

    return Campus(
        id=campus_id,
        buildings=MappingProxyType(buildings),
        nodes=MappingProxyType(nodes),
        adjacency=MappingProxyType({k: tuple(v) for k, v in adjacency.items()}),
        entrances_by_building=MappingProxyType({k: tuple(v) for k, v in entrances_by_building.items()}),
        pois=MappingProxyType(pois),
    )


def load_all(data_root):
    """Load every campus folder under data_root. The first bad campus raises; nothing is skipped."""
    data_root = Path(data_root)
    if not data_root.is_dir():
        raise LoadError(str(data_root), None, "data folder not found")
    campus_dirs = sorted(p for p in data_root.iterdir() if p.is_dir() and not p.name.startswith("."))
    if not campus_dirs:
        raise LoadError(str(data_root), None, "no campus folders found")
    return {d.name: load_campus(d) for d in campus_dirs}

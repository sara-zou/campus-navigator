"""Schematic floor plans for mock indoor data, in the indoor data contract (see CLAUDE.md).

Nothing campus-specific lives here: a campus generator describes each building with a
Building spec and writes the returned rows. Pure functions, no file I/O.

Template: one straight corridor per floor, rooms alternating sides every room_spacing_m,
stairs and an optional elevator beside the corridor. Positions are metres in a local
frame (along the corridor, to its side) and are georeferenced to lat/lon here, the
same way a real converter would.

Vertical edges follow the contract: stairs join consecutive floors (seconds per flight,
steps, not accessible); the elevator joins every pair of floors (wait + per floor).
"""
import math
from dataclasses import dataclass, field

NODE_COLS = ["node_id", "campus_id", "building_id", "floor", "coord_system",
             "x_or_lat", "y_or_lon", "type", "indoor", "accessible"]
EDGE_COLS = ["from_node", "to_node", "cost", "cost_unit", "edge_type", "accessible"]
POI_COLS = ["poi_id", "node_id", "name", "category", "building_id", "floor", "accessible", "notes"]

STAIRS_S_PER_FLIGHT = 15
ELEVATOR_WAIT_S = 30
ELEVATOR_S_PER_FLOOR = 5
CORE_OFFSET_M = 3        # stairs sit this far to the corridor's right, the elevator to its left
EARTH_R_M = 6_371_000
M_PER_DEG_LAT = math.pi * EARTH_R_M / 180   # same sphere as haversine_m, so costs match placement


@dataclass(frozen=True)
class Door:
    """An entrance node the caller already has, and where it meets the corridor."""
    node_id: str
    lat: float
    lon: float
    floor: int
    along_m: float


@dataclass(frozen=True)
class Building:
    building_id: str
    campus_id: str
    origin: tuple[float, float]   # (lat, lon) of the corridor's start
    bearing_deg: float            # corridor direction, clockwise from north
    length_m: float
    floors: tuple[int, ...]       # e.g. tuple(range(-1, 3))
    stairs_at: tuple[float, ...] = (0.0,)   # metres along the corridor
    elevator_at: float | None = None        # None: stairs only
    room_spacing_m: float = 8
    room_offset_m: float = 5                # rooms alternate sides, this far off the corridor
    doors: tuple[Door, ...] = field(default=())


def build_interior(b):
    """(nodes, edges, pois): lists of dicts keyed by the contract's columns."""
    _check(b)
    nodes, edges, pois = [], [], []
    coords = {}  # node_id -> (lat, lon), for edge costs

    def add_node(node_id, floor, along, side, type_):
        lat, lon = local_to_latlon(b.origin, b.bearing_deg, along, side)
        coords[node_id] = (lat, lon)
        nodes.append({"node_id": node_id, "campus_id": b.campus_id, "building_id": b.building_id,
                      "floor": floor, "coord_system": "latlon", "x_or_lat": lat, "y_or_lon": lon,
                      "type": type_, "indoor": True, "accessible": ""})

    def add_edge(u, v, cost, unit, edge_type, accessible):
        edges.append({"from_node": u, "to_node": v, "cost": round(cost, 2), "cost_unit": unit,
                      "edge_type": edge_type, "accessible": accessible})

    def add_walk(u, v):
        add_edge(u, v, haversine_m(*coords[u], *coords[v]), "meters", "corridor", True)

    rooms = [b.room_spacing_m * (k + 0.5) for k in range(int(b.length_m // b.room_spacing_m))]
    door_coords = {d.node_id: (d.lat, d.lon) for d in b.doors}

    for floor in b.floors:
        tag = floor_tag(floor)
        stops = set(rooms) | set(b.stairs_at) | {d.along_m for d in b.doors if d.floor == floor}
        if b.elevator_at is not None:
            stops.add(b.elevator_at)
        corridor = {}  # along -> corridor node id
        for i, along in enumerate(sorted(stops)):
            corridor[along] = f"{b.building_id}-{tag}-c{i}"
            add_node(corridor[along], floor, along, 0, "corridor")
        ids = [corridor[a] for a in sorted(corridor)]
        for u, v in zip(ids, ids[1:]):
            add_walk(u, v)

        for k, along in enumerate(rooms):
            n = k + 1
            room = f"{b.building_id}-{tag}-r{n}"
            add_node(room, floor, along, b.room_offset_m if k % 2 == 0 else -b.room_offset_m, "room")
            add_walk(corridor[along], room)
            pois.append({"poi_id": f"poi-{room}", "node_id": room, "name": room_name(floor, n),
                         "category": "room", "building_id": b.building_id, "floor": floor,
                         "accessible": "", "notes": ""})

        for j, along in enumerate(b.stairs_at):
            stair = f"{b.building_id}-{tag}-s{j}"
            add_node(stair, floor, along, -CORE_OFFSET_M, "stairs")
            add_walk(corridor[along], stair)
        if b.elevator_at is not None:
            lift = f"{b.building_id}-{tag}-l"
            add_node(lift, floor, b.elevator_at, CORE_OFFSET_M, "elevator")
            add_walk(corridor[b.elevator_at], lift)

        for d in b.doors:
            if d.floor == floor:
                coords[d.node_id] = door_coords[d.node_id]
                add_walk(d.node_id, corridor[d.along_m])

    floors = sorted(b.floors)
    for j in range(len(b.stairs_at)):
        for lo, hi in zip(floors, floors[1:]):
            add_edge(f"{b.building_id}-{floor_tag(lo)}-s{j}", f"{b.building_id}-{floor_tag(hi)}-s{j}",
                     STAIRS_S_PER_FLIGHT * (hi - lo), "seconds", "steps", False)
    if b.elevator_at is not None:
        for i, lo in enumerate(floors):
            for hi in floors[i + 1:]:
                add_edge(f"{b.building_id}-{floor_tag(lo)}-l", f"{b.building_id}-{floor_tag(hi)}-l",
                         ELEVATOR_WAIT_S + ELEVATOR_S_PER_FLOOR * (hi - lo), "seconds", "elevator", True)
    return nodes, edges, pois


def footprint(b, margin_m=3):
    """GeoJSON Polygon ([lon, lat]) around the corridor and its rooms, margin_m beyond them."""
    half = b.room_offset_m + margin_m
    corners = [(-margin_m, -half), (b.length_m + margin_m, -half),
               (b.length_m + margin_m, half), (-margin_m, half)]
    ring = [local_to_latlon(b.origin, b.bearing_deg, a, s) for a, s in corners]
    ring.append(ring[0])
    return {"type": "Polygon", "coordinates": [[[lon, lat] for lat, lon in ring]]}


def _check(b):
    if not b.floors or len(set(b.floors)) != len(b.floors):
        raise ValueError(f"{b.building_id}: floors must be non-empty and distinct")
    if b.room_spacing_m <= 0 or b.length_m <= 0:
        raise ValueError(f"{b.building_id}: length_m and room_spacing_m must be positive")
    points = list(b.stairs_at) + [d.along_m for d in b.doors]
    if b.elevator_at is not None:
        points.append(b.elevator_at)
    for p in points:
        if not 0 <= p <= b.length_m:
            raise ValueError(f"{b.building_id}: position {p} is outside the corridor (0..{b.length_m})")
    for d in b.doors:
        if d.floor not in b.floors:
            raise ValueError(f"{b.building_id}: door {d.node_id!r} is on floor {d.floor}, not one of {b.floors}")


def floor_tag(floor):
    """Floor as it appears in ids: b1 for -1, 0, 1, 2, ..."""
    return f"b{-floor}" if floor < 0 else str(floor)


def room_name(floor, n):
    """Room 101 (floor 1), Room G01 (floor 0), Room B101 (floor -1). Labels only."""
    if floor > 0:
        return f"Room {floor}{n:02d}"
    if floor == 0:
        return f"Room G{n:02d}"
    return f"Room B{-floor}{n:02d}"


def local_to_latlon(origin, bearing_deg, along_m, side_m):
    """Metres along a bearing (clockwise from north) and to its left -> (lat, lon), flat-earth approx."""
    t = math.radians(bearing_deg)
    east = along_m * math.sin(t) - side_m * math.cos(t)
    north = along_m * math.cos(t) + side_m * math.sin(t)
    lat0, lon0 = origin
    lat = lat0 + north / M_PER_DEG_LAT
    lon = lon0 + east / (M_PER_DEG_LAT * math.cos(math.radians(lat0)))
    return round(lat, 7), round(lon, 7)


def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R_M * math.asin(math.sqrt(a))

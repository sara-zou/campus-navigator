"""Generate data/demo-university/: a made-up campus with mock indoor floor plans.

Entirely fake (Franklin Park golf course, Boston: open ground, so the fake buildings
don't sit on real ones). Each building covers one demo case:

  hall   Main Hall      floors -1..2  basement; south door accessible, east door not
  lib    Library        floors 0..3   stairs at both ends + elevator
  lab    Hillside Lab   floors 0..1   north door opens onto floor 1 (up the hill)
  annex  Old Annex      floors 0..2   stairs only: wheelchair can't reach floors 1-2
  cafe   Cafe           no interior   doors only (floors [] in the API)
  shed   Maint. Shed    no interior   no entrances

Outdoors is a hand-written sidewalk network, including one steps edge (the hill stairs)
with a longer accessible ramp beside it, and a bus stop POI.

Everything is placed in metres east/north of ORIGIN. Rerunning overwrites all four CSVs.
Run from data-prep/: .venv/bin/python scripts/demo-university/generate.py
"""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared"))
from indoor_builder import (EDGE_COLS, NODE_COLS, POI_COLS, Building, Door,  # noqa: E402
                            build_interior, footprint, haversine_m, local_to_latlon)

CAMPUS_ID = "demo-university"
OUT_DIR = Path(__file__).resolve().parents[3] / "data" / CAMPUS_ID
ORIGIN = (42.305, -71.093)


def at(x, y):
    """Local metres (east, north) -> (lat, lon)."""
    return local_to_latlon(ORIGIN, 90, x, y)


def rect(x0, y0, x1, y1):
    """GeoJSON Polygon for a local-metre rectangle."""
    ring = [at(x0, y0), at(x1, y0), at(x1, y1), at(x0, y1), at(x0, y0)]
    return {"type": "Polygon", "coordinates": [[[lon, lat] for lat, lon in ring]]}


# --- outdoor sidewalks: waypoint id -> (east, north) ---
WAYPOINTS = {
    "w-s1": (-50, -30), "w-sw": (-30, -30), "w-s2": (24, -30), "w-se": (70, -30),
    "w-s3": (90, -30), "w-s4": (110, -30),                       # south street
    "w-m1": (-30, 30), "w-m2": (16, 30), "w-m3": (48, 30), "w-m4": (70, 30),  # middle walk
    "w-e1": (70, 8),                                             # east walk
    "w-r1": (-55, 55),                                           # ramp bend
    "w-n1": (-30, 80), "w-n2": (16, 80),                         # north path, up the hill
}
# (from, to, edge_type, accessible)
SIDEWALKS = [
    ("w-s1", "w-sw", "footway", True), ("w-sw", "w-s2", "footway", True),
    ("w-s2", "w-se", "footway", True), ("w-se", "w-s3", "footway", True),
    ("w-s3", "w-s4", "footway", True),
    ("w-sw", "w-m1", "footway", True),
    ("w-m1", "w-m2", "footway", True), ("w-m2", "w-m3", "footway", True), ("w-m3", "w-m4", "footway", True),
    ("w-se", "w-e1", "footway", True), ("w-e1", "w-m4", "footway", True),
    ("w-m1", "w-n1", "steps", False),                            # hill stairs: 50 m
    ("w-m1", "w-r1", "footway", True), ("w-r1", "w-n1", "footway", True),  # ramp: ~71 m
    ("w-n1", "w-n2", "footway", True),
]

# --- buildings with interiors ---
HALL = Building("hall", CAMPUS_ID, at(0, 0), 90, 48, tuple(range(-1, 3)), stairs_at=(0.0,), elevator_at=24.0)
LIB = Building("lib", CAMPUS_ID, at(90, -20), 0, 56, tuple(range(0, 4)), stairs_at=(0.0, 56.0), elevator_at=28.0)
LAB = Building("lab", CAMPUS_ID, at(0, 60), 90, 32, (0, 1), stairs_at=(0.0,), elevator_at=16.0)
ANNEX = Building("annex", CAMPUS_ID, at(-50, -10), 0, 24, (0, 1, 2), stairs_at=(0.0,))

# (building, name, door id, door label, (east, north), floor, accessible, along_m, sidewalk waypoint)
# along_m None = a door into a building without an interior.
DOORS = [
    (HALL, "Main Hall", "hall-door-s", "South", (24, -11), 0, True, 24.0, "w-s2"),
    (HALL, "Main Hall", "hall-door-e", "East", (54, 0), 0, False, 48.0, "w-e1"),
    (LIB, "Library", "lib-door-s", "South", (90, -26), 0, True, 0.0, "w-s3"),
    (LIB, "Library", "lib-door-w", "West", (79, 8), 0, True, 28.0, "w-e1"),
    (LAB, "Hillside Lab", "lab-door-s", "South", (16, 49), 0, True, 16.0, "w-m2"),
    (LAB, "Hillside Lab", "lab-door-n", "North", (16, 71), 1, True, 16.0, "w-n2"),
    (ANNEX, "Old Annex", "annex-door-s", "South", (-50, -16), 0, True, 0.0, "w-s1"),
    ("cafe", "Cafe", "cafe-door-s", "South", (48, 37), 0, True, None, "w-m3"),
]
PLAIN_BUILDINGS = [  # (id, name, rectangle in local metres): no interior
    ("cafe", "Cafe", (40, 40, 56, 52)),
    ("shed", "Maintenance Shed", (-50, 50, -40, 58)),
]
OUTDOOR_POIS = [("poi-bus", "w-s4", "Bus Stop", "transit")]


def generate():
    buildings, nodes, edges, pois = [], [], [], []
    coords = {}

    def node(node_id, building_id, floor, lat, lon, type_, accessible=""):
        coords[node_id] = (lat, lon)
        nodes.append({"node_id": node_id, "campus_id": CAMPUS_ID, "building_id": building_id, "floor": floor,
                      "coord_system": "latlon", "x_or_lat": lat, "y_or_lon": lon, "type": type_,
                      "indoor": False, "accessible": accessible})

    def walk(u, v, edge_type, accessible):
        edges.append({"from_node": u, "to_node": v, "cost": round(haversine_m(*coords[u], *coords[v]), 2),
                      "cost_unit": "meters", "edge_type": edge_type, "accessible": accessible})

    for wid, (x, y) in WAYPOINTS.items():
        node(wid, "", 0, *at(x, y), "waypoint")
    for u, v, edge_type, accessible in SIDEWALKS:
        walk(u, v, edge_type, accessible)

    doors_by_building = {}
    for b, name, door_id, label, (x, y), floor, accessible, along, waypoint in DOORS:
        bid = b if isinstance(b, str) else b.building_id
        lat, lon = at(x, y)
        node(door_id, bid, floor, lat, lon, "entrance", accessible)
        walk(door_id, waypoint, "connector", True)
        pois.append({"poi_id": f"poi-{door_id}", "node_id": door_id, "name": f"{name} ({label} Entrance)",
                     "category": "entrance", "building_id": bid, "floor": floor, "accessible": accessible,
                     "notes": "" if accessible else "Steps at the door"})
        if along is not None:
            doors_by_building.setdefault(bid, []).append(Door(door_id, lat, lon, floor, along))

    for b, name in [(HALL, "Main Hall"), (LIB, "Library"), (LAB, "Hillside Lab"), (ANNEX, "Old Annex")]:
        spec = Building(**{**b.__dict__, "doors": tuple(doors_by_building[b.building_id])})
        buildings.append({"building_id": b.building_id, "name": name, "polygon_geojson": json.dumps(footprint(spec))})
        n, e, p = build_interior(spec)
        nodes += n
        edges += e
        pois += p
    for bid, name, box in PLAIN_BUILDINGS:
        buildings.append({"building_id": bid, "name": name, "polygon_geojson": json.dumps(rect(*box))})

    for poi_id, node_id, name, category in OUTDOOR_POIS:
        pois.append({"poi_id": poi_id, "node_id": node_id, "name": name, "category": category,
                     "building_id": "", "floor": 0, "accessible": "", "notes": ""})
    return buildings, nodes, edges, pois


def write(path, cols, rows):
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def main():
    buildings, nodes, edges, pois = generate()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write(OUT_DIR / "buildings.csv", ["building_id", "name", "polygon_geojson"], buildings)
    write(OUT_DIR / "nodes.csv", NODE_COLS, nodes)
    write(OUT_DIR / "edges.csv", EDGE_COLS, edges)
    write(OUT_DIR / "pois.csv", POI_COLS, pois)
    print(f"{OUT_DIR}: {len(buildings)} buildings, {len(nodes)} nodes, {len(edges)} edges, {len(pois)} pois")


if __name__ == "__main__":
    main()

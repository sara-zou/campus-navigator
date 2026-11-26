"""Generate data/northeastern-boston-demo/: the real Northeastern data plus MOCK interiors.

The real campus (data/northeastern-boston/) is read-only input and is never written.
Its rows are copied unchanged, except two things the loader requires: nodes.csv's
campus_id becomes this campus's id, and nodes gain indoor=False. Fake interiors are then
added to a few real buildings, attached to their real entrance nodes. Fake room POIs
carry notes = MOCK_NOTE, so they can't be mistaken for real data.

Placement is automatic: the corridor runs along the long axis of the building's minimum
rotated rectangle, through its centre, MARGIN_M short of each end. OVERRIDES can replace
a building's origin/bearing/length by hand if a corridor looks wrong on the map. Real
polygons are irregular, so some rooms can fall outside the outline; the count is printed.

Rerun after any change to the real data (a server test fails while this copy is stale).
Run from data-prep/: .venv/bin/python scripts/northeastern-boston-demo/generate.py
"""
import csv
import json
import math
import sys
from pathlib import Path

from shapely.geometry import Point, shape
from shapely.ops import transform

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared"))
from indoor_builder import M_PER_DEG_LAT, NODE_COLS, Building, Door, build_interior  # noqa: E402

CAMPUS_ID = "northeastern-boston-demo"
CAMPUS_NAME = "Northeastern (demo interiors)"  # not copied from the real campus.csv: says it's a demo
DATA = Path(__file__).resolve().parents[3] / "data"
REAL_DIR = DATA / "northeastern-boston"
OUT_DIR = DATA / CAMPUS_ID
MOCK_NOTE = "Mock indoor data"
MARGIN_M = 6

# building_id -> floors, staircases ("start", "end"), elevator
INTERIORS = {
    "sl": dict(floors=tuple(range(-1, 4)), stairs=("start",), elevator=True),
    "isec": dict(floors=tuple(range(0, 4)), stairs=("start", "end"), elevator=True),
    "exp": dict(floors=tuple(range(0, 5)), stairs=("start",), elevator=True),
}
# building_id -> {"origin": (lat, lon), "bearing_deg": ..., "length_m": ...}, any subset
OVERRIDES = {}


def read(path):
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def write(path, cols, rows):
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def local_frame(lat0, lon0):
    """(to_m, to_deg): lon/lat <-> metres east/north of (lat0, lon0), flat-earth."""
    k = M_PER_DEG_LAT * math.cos(math.radians(lat0))
    to_m = lambda lon, lat, z=None: ((lon - lon0) * k, (lat - lat0) * M_PER_DEG_LAT)  # noqa: E731
    to_deg = lambda x, y: (lat0 + y / M_PER_DEG_LAT, lon0 + x / k)  # noqa: E731
    return to_m, to_deg


def place(building_id, polygon_geojson, entrances, spec):
    """A Building spec for one real building, and its outline in local metres (for the outside count)."""
    geom = shape(json.loads(polygon_geojson))
    c = geom.centroid
    to_m, to_deg = local_frame(c.y, c.x)
    local = transform(to_m, geom)
    rect = list(local.minimum_rotated_rectangle.exterior.coords)[:4]
    edges = [(rect[i], rect[(i + 1) % 4]) for i in range(2)]
    (ax, ay), (bx, by) = max(edges, key=lambda e: math.dist(*e))
    long_m = math.dist((ax, ay), (bx, by))
    ux, uy = (bx - ax) / long_m, (by - ay) / long_m           # unit vector along the long axis
    cx, cy = local.minimum_rotated_rectangle.centroid.coords[0]
    length = long_m - 2 * MARGIN_M
    ox, oy = cx - ux * length / 2, cy - uy * length / 2
    o = OVERRIDES.get(building_id, {})
    origin = o.get("origin", to_deg(ox, oy))
    bearing = o.get("bearing_deg", math.degrees(math.atan2(ux, uy)) % 360)
    length = o.get("length_m", length)
    if o:  # recompute the axis from the overridden spec, for door projection
        ox, oy = to_m(origin[1], origin[0])
        ux, uy = math.sin(math.radians(bearing)), math.cos(math.radians(bearing))

    doors = []
    for e in entrances:
        lat, lon = float(e["x_or_lat"]), float(e["y_or_lon"])
        ex, ey = to_m(lon, lat)
        along = round(min(max((ex - ox) * ux + (ey - oy) * uy, 0.0), length), 2)
        doors.append(Door(e["node_id"], lat, lon, int(e["floor"]), along))

    stairs = tuple({"start": 0.0, "end": round(length, 2)}[s] for s in spec["stairs"])
    b = Building(building_id, CAMPUS_ID, origin, bearing, round(length, 2), spec["floors"],
                 stairs_at=stairs, elevator_at=round(length / 2, 2) if spec["elevator"] else None,
                 doors=tuple(doors))
    return b, local, to_m


def main():
    b_cols, buildings = read(REAL_DIR / "buildings.csv")
    _, nodes = read(REAL_DIR / "nodes.csv")
    e_cols, edges = read(REAL_DIR / "edges.csv")
    p_cols, pois = read(REAL_DIR / "pois.csv")

    nodes = [{**n, "campus_id": CAMPUS_ID, "indoor": False} for n in nodes]
    by_building = {b["building_id"]: b for b in buildings}
    for bid, spec in INTERIORS.items():
        entrances = [n for n in nodes if n["building_id"] == bid and n["type"] == "entrance"]
        b, outline, to_m = place(bid, by_building[bid]["polygon_geojson"], entrances, spec)
        n, e, p = build_interior(b)
        outside = sum(not outline.contains(Point(to_m(r["y_or_lon"], r["x_or_lat"]))) for r in n)
        print(f"{bid}: bearing {b.bearing_deg:.0f}°, corridor {b.length_m:.0f} m, floors {b.floors}, "
              f"{len(n)} nodes ({outside} outside the outline)")
        nodes += n
        edges += e
        pois += [{**r, "notes": MOCK_NOTE} for r in p]

    ids = [n["node_id"] for n in nodes]
    assert len(ids) == len(set(ids)), "a mock node id collides with a real one"
    OUT_DIR.mkdir(exist_ok=True)
    write(OUT_DIR / "campus.csv", ["name"], [{"name": CAMPUS_NAME}])
    write(OUT_DIR / "buildings.csv", b_cols, buildings)
    write(OUT_DIR / "nodes.csv", NODE_COLS, nodes)
    write(OUT_DIR / "edges.csv", e_cols, edges)
    write(OUT_DIR / "pois.csv", p_cols, pois)
    print(f"{OUT_DIR}: {len(buildings)} buildings, {len(nodes)} nodes, {len(edges)} edges, {len(pois)} pois")


if __name__ == "__main__":
    main()

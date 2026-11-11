"""
Snap the 82 entrance nodes onto the filtered OSM path network by splitting
the nearest edge at the entrance's projected point, then connecting the
entrance to that split point. Appends new waypoint rows (the split points)
to nodes.csv, and fully regenerates edges.csv to include both the
untouched backbone edges and the new split/connector edges.

Approach: for each entrance, find the nearest edge (not just nearest node)
using the edge's real curve geometry, and project the entrance onto it to
get a fractional position along the edge (0 = at u, 1 = at v). Entrances
are grouped by which edge they land on and sorted by that fraction, so an
edge with multiple nearby entrances is split into one ordered chain in a
single pass -- splitting the same edge independently per entrance, without
this grouping step, would produce duplicate/overlapping edges.

Sub-edge lengths are the original edge's real (geometry-following) meter
length scaled by the fraction between consecutive points -- not a
straight-line approximation. Connector edges (entrance -> split point) are
straight-line (haversine), since that distance is always short.

Idempotent: split-point rows in nodes.csv are replaced each run (they move
if an entrance snaps to a different edge); all other nodes.csv rows are left
alone. edges.csv is fully regenerated each run.
"""

import csv
import math
from collections import defaultdict
from pathlib import Path

import networkx as nx
import osmnx as ox
from shapely.geometry import LineString, Point

from osm_graph import CAMPUS_ID, drop_exact_duplicate_rows, load_filtered_graph, waypoint_id

NODES_CSV = Path(__file__).parent.parent.parent.parent / "data" / CAMPUS_ID / "nodes.csv"
EDGES_CSV = Path(__file__).parent.parent.parent.parent / "data" / CAMPUS_ID / "edges.csv"

NODES_FIELDNAMES = ["node_id", "campus_id", "building_id", "floor", "coord_system", "x_or_lat", "y_or_lon", "type"]
EDGES_FIELDNAMES = ["from_node", "to_node", "cost", "cost_unit", "edge_type", "accessible"]


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def build_kept_subgraph(G, kept_edges) -> nx.MultiDiGraph:
    # Each edge carries its kept_edges key, so a nearest-edge hit maps back
    # to exactly one kept edge even when parallel edges share a node pair.
    H = nx.MultiDiGraph(**G.graph)
    for edge_key, (u, v, data, tags) in kept_edges.items():
        if u not in H:
            H.add_node(u, **G.nodes[u])
        if v not in H:
            H.add_node(v, **G.nodes[v])
        H.add_edge(u, v, **data, kept_key=edge_key)
    return H


def edge_geometry(H, u, v, key) -> LineString:
    data = H[u][v][key]
    geom = data.get("geometry")
    if geom is not None:
        return geom
    return LineString([(H.nodes[u]["x"], H.nodes[u]["y"]), (H.nodes[v]["x"], H.nodes[v]["y"])])


def main():
    G, kept_edges, surviving_node_ids = load_filtered_graph()
    with open(NODES_CSV, newline="") as f:
        entrances = [row for row in csv.DictReader(f) if row["type"] == "entrance"]
    print(f"Loaded {len(entrances)} entrances to snap")

    H = build_kept_subgraph(G, kept_edges)

    xs = [float(e["y_or_lon"]) for e in entrances]  # osmnx x = longitude
    ys = [float(e["x_or_lat"]) for e in entrances]  # osmnx y = latitude
    nearest = ox.distance.nearest_edges(H, X=xs, Y=ys)

    # Group entrances by which edge they landed on, so an edge with
    # multiple nearby entrances gets split once, in position order.
    groups = defaultdict(list)  # {kept_edges key: [(frac, entrance, split_lat, split_lon, connector_m)]}
    for entrance, (u, v, key) in zip(entrances, nearest):
        line = edge_geometry(H, u, v, key)
        point = Point(float(entrance["y_or_lon"]), float(entrance["x_or_lat"]))
        frac = line.project(point) / line.length
        split_point = line.interpolate(frac, normalized=True)
        split_lon, split_lat = split_point.x, split_point.y
        connector_m = haversine_m(float(entrance["x_or_lat"]), float(entrance["y_or_lon"]), split_lat, split_lon)
        groups[H[u][v][key]["kept_key"]].append((frac, entrance, split_lat, split_lon, connector_m))

    print(f"{len(entrances)} entrances land on {len(groups)} distinct edges")

    new_node_rows = []
    edge_rows = []

    for edge_key, (u, v, data, tags) in kept_edges.items():
        total_length_m = data.get("length")
        edge_type = "+".join(tags) if tags else "unknown"
        accessible = "steps" not in tags

        if edge_key not in groups:
            edge_rows.append({
                "from_node": waypoint_id(u),
                "to_node": waypoint_id(v),
                "cost": total_length_m,
                "cost_unit": "meters",
                "edge_type": edge_type,
                "accessible": accessible,
            })
            continue

        entries = sorted(groups[edge_key], key=lambda e: e[0])
        chain_nodes = [waypoint_id(u)]
        fracs = [0.0]
        for frac, entrance, split_lat, split_lon, connector_m in entries:
            node_id = f"waypoint_split_{entrance['node_id']}"
            chain_nodes.append(node_id)
            fracs.append(frac)
            new_node_rows.append({
                "node_id": node_id,
                "campus_id": CAMPUS_ID,
                "building_id": "",
                "floor": 0,
                "coord_system": "latlon",
                "x_or_lat": split_lat,
                "y_or_lon": split_lon,
                "type": "waypoint",
            })
            edge_rows.append({
                "from_node": entrance["node_id"],
                "to_node": node_id,
                "cost": connector_m,
                "cost_unit": "meters",
                "edge_type": "connector",
                "accessible": True,
            })
        chain_nodes.append(waypoint_id(v))
        fracs.append(1.0)

        for i in range(len(chain_nodes) - 1):
            sub_length = (fracs[i + 1] - fracs[i]) * total_length_m
            edge_rows.append({
                "from_node": chain_nodes[i],
                "to_node": chain_nodes[i + 1],
                "cost": sub_length,
                "cost_unit": "meters",
                "edge_type": edge_type,
                "accessible": accessible,
            })

    # --- nodes.csv: replace all split-point rows (idempotent) ---
    # Split points are derived from the current edges, so a rerun must
    # replace them, not skip them: if an entrance now snaps to a different
    # edge, its split point moves. Other rows are kept as-is.
    with open(NODES_CSV, newline="") as f:
        all_rows = list(csv.DictReader(f))
    kept_rows = [row for row in all_rows if not row["node_id"].startswith("waypoint_split_")]
    removed = len(all_rows) - len(kept_rows)

    with open(NODES_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=NODES_FIELDNAMES)
        writer.writeheader()
        writer.writerows(kept_rows)
        writer.writerows(new_node_rows)

    print(f"Replaced {removed} old split-point rows with {len(new_node_rows)} in {NODES_CSV}")

    # --- edges.csv: fully regenerated each run ---
    edge_rows = drop_exact_duplicate_rows(edge_rows)
    with open(EDGES_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=EDGES_FIELDNAMES)
        writer.writeheader()
        for row in edge_rows:
            writer.writerow(row)

    print(f"Wrote {len(edge_rows)} edges to {EDGES_CSV}")


if __name__ == "__main__":
    main()

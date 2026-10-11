"""
Filter and normalize the raw OSM walk graph (sidewalks.graphml) into the
project schema: appends waypoint rows to the existing nodes.csv, and writes
a new edges.csv.

Filtering: osmnx's network_type="walk" already restricted the pull to ways
pedestrians are legally allowed on, so this script does NOT re-filter on
most highway tags (footway/path/steps/pedestrian/service/residential/
primary/secondary/trunk/busway/etc. are all kept). It only drops two
highway types that represent INDOOR infrastructure, out of scope for this
outdoor-only phase: "corridor" (indoor hallway) and "elevator" (vertical,
indoor). It also drops self-loops (same node on both ends).

Directed -> undirected: the raw graph is a MultiDiGraph (most path segments
appear twice, once per direction). Since campus paths are walkable both
ways, this collapses each (u, v) / (v, u) pair into a single undirected row
in edges.csv, keyed on the unordered node pair.

Idempotent: running this twice will not duplicate waypoint rows in
nodes.csv (it skips any waypoint_<osmid> already present). edges.csv is
fully regenerated each run.
"""

import csv
from pathlib import Path

import osmnx as ox

CAMPUS_ID = "northeastern-boston"
RAW_PATH = Path(__file__).parent.parent.parent / "raw" / CAMPUS_ID / "sidewalks.graphml"
NODES_CSV = Path(__file__).parent.parent.parent.parent / "data" / CAMPUS_ID / "nodes.csv"
EDGES_CSV = Path(__file__).parent.parent.parent.parent / "data" / CAMPUS_ID / "edges.csv"

# Indoor infrastructure -- out of scope for the outdoor-only phase.
EXCLUDED_HIGHWAY_TYPES = {"corridor", "elevator"}

NODES_FIELDNAMES = ["node_id", "campus_id", "building_id", "floor", "coord_system", "x_or_lat", "y_or_lon", "type"]
EDGES_FIELDNAMES = ["from_node", "to_node", "cost", "cost_unit", "edge_type", "accessible"]


def waypoint_id(osmid) -> str:
    return f"waypoint_{osmid}"


def load_existing_waypoint_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with open(path, newline="") as f:
        return {row["node_id"] for row in csv.DictReader(f) if row["node_id"].startswith("waypoint_")}


def main():
    G = ox.load_graphml(RAW_PATH)
    print(f"Loaded raw graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    # Collapse the directed multigraph into unique undirected (u, v) edges,
    # dropping self-loops and indoor-infrastructure highway types.
    kept_edges = {}  # {frozenset({u, v}): edge_data}
    dropped_indoor = 0
    dropped_self_loop = 0

    for u, v, data in G.edges(data=True):
        if u == v:
            dropped_self_loop += 1
            continue

        raw_highway = data.get("highway")
        if raw_highway is None:
            tags = []
        elif isinstance(raw_highway, list):
            tags = raw_highway
        else:
            tags = [raw_highway]
        if any(t in EXCLUDED_HIGHWAY_TYPES for t in tags):
            dropped_indoor += 1
            continue

        key = frozenset((u, v))
        if key not in kept_edges:
            kept_edges[key] = (u, v, data, tags)

    print(f"Dropped {dropped_self_loop} self-loop edges, {dropped_indoor} indoor-infrastructure edges")
    print(f"Kept {len(kept_edges)} unique undirected edges")

    # Only waypoints that are an endpoint of at least one kept edge survive.
    surviving_node_ids = {n for key in kept_edges for n in key}
    print(f"Surviving nodes: {len(surviving_node_ids)} (of {G.number_of_nodes()} raw)")

    # --- nodes.csv: append new waypoint rows (idempotent) ---
    # Append-only: a waypoint already written here never gets pruned later,
    # even if EXCLUDED_HIGHWAY_TYPES changes and a rerun would now exclude it.
    # Only edges.csv (rewritten in full each run) reflects filter changes.
    already_present = load_existing_waypoint_ids(NODES_CSV)
    new_node_rows = []
    for n in surviving_node_ids:
        node_id = waypoint_id(n)
        if node_id in already_present:
            continue
        attrs = G.nodes[n]
        new_node_rows.append({
            "node_id": node_id,
            "campus_id": CAMPUS_ID,
            "building_id": "",
            "floor": 0,
            "coord_system": "latlon",
            "x_or_lat": attrs["y"],
            "y_or_lon": attrs["x"],
            "type": "waypoint",
        })

    with open(NODES_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=NODES_FIELDNAMES)
        for row in new_node_rows:
            writer.writerow(row)

    print(f"Appended {len(new_node_rows)} new waypoint rows to {NODES_CSV}")
    print(f"Skipped {len(surviving_node_ids) - len(new_node_rows)} waypoints already present")

    # --- edges.csv: fully regenerated each run ---
    edge_rows = []
    for u, v, data, tags in kept_edges.values():
        edge_type = "+".join(tags) if tags else "unknown"
        accessible = "steps" not in tags
        edge_rows.append({
            "from_node": waypoint_id(u),
            "to_node": waypoint_id(v),
            "cost": data.get("length"),
            "cost_unit": "meters",
            "edge_type": edge_type,
            "accessible": accessible,
        })

    with open(EDGES_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=EDGES_FIELDNAMES)
        writer.writeheader()
        for row in edge_rows:
            writer.writerow(row)

    print(f"Wrote {len(edge_rows)} edges to {EDGES_CSV}")


if __name__ == "__main__":
    main()

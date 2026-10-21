"""
Normalize the filtered raw OSM walk graph (sidewalks.graphml) into the
project schema: appends waypoint rows to the existing nodes.csv, and writes
a new edges.csv. Filtering/collapsing logic lives in osm_graph.py, shared
with snap_entrances.py.

Idempotent: running this twice will not duplicate waypoint rows in
nodes.csv (it skips any waypoint_<osmid> already present). edges.csv is
fully regenerated each run.
"""

import csv
from pathlib import Path

from osm_graph import CAMPUS_ID, load_filtered_graph, waypoint_id

NODES_CSV = Path(__file__).parent.parent.parent.parent / "data" / CAMPUS_ID / "nodes.csv"
EDGES_CSV = Path(__file__).parent.parent.parent.parent / "data" / CAMPUS_ID / "edges.csv"

NODES_FIELDNAMES = ["node_id", "campus_id", "building_id", "floor", "coord_system", "x_or_lat", "y_or_lon", "type"]
EDGES_FIELDNAMES = ["from_node", "to_node", "cost", "cost_unit", "edge_type", "accessible"]


def main():
    G, kept_edges, surviving_node_ids = load_filtered_graph()

    # --- nodes.csv: append new waypoint rows (idempotent) ---
    # Append-only: a waypoint already written here never gets pruned later,
    # even if EXCLUDED_HIGHWAY_TYPES changes and a rerun would now exclude it.
    # Only edges.csv (rewritten in full each run) reflects filter changes.
    if NODES_CSV.exists():
        with open(NODES_CSV, newline="") as f:
            already_present = {row["node_id"] for row in csv.DictReader(f) if row["node_id"].startswith("waypoint_")}
    else:
        already_present = set()
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

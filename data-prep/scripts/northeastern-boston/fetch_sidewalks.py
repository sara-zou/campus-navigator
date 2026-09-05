"""
Pull Northeastern's Boston campus pedestrian network from OpenStreetMap via osmnx as raw info
"""

from pathlib import Path

import osmnx as ox

CAMPUS_ID = "northeastern-boston"
OUT_PATH = Path(__file__).parent.parent.parent / "raw" / CAMPUS_ID / "sidewalks.graphml"

# excludes properties that sit far outside the walkable core
WEST, SOUTH, EAST, NORTH = -71.095625, 42.333189, -71.080543, 42.347835


def main():
    print(f"Downloading walk network for bbox ({WEST}, {SOUTH}, {EAST}, {NORTH})...")
    G = ox.graph_from_bbox(bbox=(WEST, SOUTH, EAST, NORTH), network_type="walk")
    print(f"Downloaded {len(G.nodes)} nodes, {len(G.edges)} edges")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ox.save_graphml(G, OUT_PATH)
    print(f"Saved raw graph to {OUT_PATH}")


if __name__ == "__main__":
    main()

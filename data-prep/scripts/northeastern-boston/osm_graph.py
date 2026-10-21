"""
Shared logic for loading and filtering the raw OSM walk graph
(sidewalks.graphml). Used by both transform_sidewalks.py and
snap_entrances.py so the filtering rules can't drift between them.

"""

from pathlib import Path

import osmnx as ox

CAMPUS_ID = "northeastern-boston"
RAW_PATH = Path(__file__).parent.parent.parent / "raw" / CAMPUS_ID / "sidewalks.graphml"

# Indoor infrastructure -- out of scope for the outdoor-only phase.
EXCLUDED_HIGHWAY_TYPES = {"corridor", "elevator"}


def waypoint_id(osmid) -> str:
    return f"waypoint_{osmid}"


def load_filtered_graph():
    """
    Returns (G, kept_edges, surviving_node_ids):
      G                  -- the raw networkx MultiDiGraph, unmodified
      kept_edges         -- {frozenset({u, v}): (u, v, data, tags)}
      surviving_node_ids -- node ids that are an endpoint of >=1 kept edge
    """
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

    return G, kept_edges, surviving_node_ids

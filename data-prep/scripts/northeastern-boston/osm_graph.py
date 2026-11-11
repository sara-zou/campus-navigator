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
      kept_edges         -- {(frozenset({u, v}), osm_way_ids): (u, v, data, tags)}
      surviving_node_ids -- node ids that are an endpoint of >=1 kept edge
    """
    G = ox.load_graphml(RAW_PATH)
    print(f"Loaded raw graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    # Collapse the directed multigraph into undirected edges, dropping
    # self-loops and indoor-infrastructure highway types. osmnx stores every
    # way in both directions; keying on (node pair, OSM way ids) merges those
    # reverse copies but keeps genuinely parallel ways between the same two
    # nodes (e.g. a staircase and an accessible footway side by side).
    kept_edges = {}  # {(frozenset({u, v}), osm_way_ids): edge_data}
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

        osmid = data.get("osmid")
        way_ids = tuple(sorted(osmid)) if isinstance(osmid, list) else (osmid,)
        key = (frozenset((u, v)), way_ids)
        if key not in kept_edges:
            kept_edges[key] = (u, v, data, tags)

    n_pairs = len({pair for pair, _ in kept_edges})
    print(f"Dropped {dropped_self_loop} self-loop edges, {dropped_indoor} indoor-infrastructure edges")
    print(f"Kept {len(kept_edges)} undirected edges over {n_pairs} node pairs "
          f"({len(kept_edges) - n_pairs} parallel)")

    # Only waypoints that are an endpoint of at least one kept edge survive.
    surviving_node_ids = {n for pair, _ in kept_edges for n in pair}
    print(f"Surviving nodes: {len(surviving_node_ids)} (of {G.number_of_nodes()} raw)")

    return G, kept_edges, surviving_node_ids


def drop_exact_duplicate_rows(rows):
    """Remove edge rows identical in every column (e.g. two parallel ways
    with the same length and tags), keeping first-seen order. Edges are
    undirected, so A->B and B->A count as the same. The server loader
    rejects exact duplicate edges."""
    seen = set()
    unique = []
    for row in rows:
        rest = tuple((k, v) for k, v in row.items() if k not in ("from_node", "to_node"))
        key = (frozenset((row["from_node"], row["to_node"])), rest)
        if key not in seen:
            seen.add(key)
            unique.append(row)
    return unique

"""Query layer: turns user-facing requests into routing calls and readable results.

search.py  name lookup over buildings and POIs; never touches the graph
snap.py    GPS point -> nearest outdoor edge, via a temporary START node over the adjacency
route.py   start -> building / POI / entrance, with totals, flags and floor info
layout.py  a building's schematic floor plans (the frontend's floor view)

Callers import from `query`; the split into modules is internal.
"""
from .layout import BuildingLayout, FloorLayout, LayoutPoint, building_layout
from .route import MODES, Flag, FloorChange, NoRoute, Route, flags_for, is_entrance, poi_name_at, route
from .search import DEFAULT_SEARCH_LIMIT, SearchResult, poi_building, search
from .snap import START, Snap, TooFar, snap

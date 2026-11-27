"""The in-memory campus: what the loader builds and every other layer reads. All frozen."""
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Building:
    id: str
    name: str
    geometry: dict  # parsed GeoJSON Polygon or MultiPolygon, [lon, lat] order


@dataclass(frozen=True)
class Node:
    id: str
    campus_id: str
    building_id: str | None  # None for outdoor waypoints
    floor: int               # integer index; negatives are basements
    coord_system: str
    x_or_lat: float
    y_or_lon: float
    type: str                # open set; only "entrance" has special rules
    accessible: bool | None = None  # read for entrances only: is the door wheelchair-accessible? None = unknown
    indoor: bool = False     # inside a building or enclosed space; snapping uses only edges with both ends outdoor


@dataclass(frozen=True)
class Edge:
    from_node: str
    to_node: str
    cost: float
    cost_unit: str
    edge_type: str | None    # open set; None if not given
    accessible: bool | None  # None = unknown


@dataclass(frozen=True)
class POI:
    id: str
    node_id: str             # where routing goes; not part of the graph itself
    name: str
    category: str | None     # open set
    building_id: str | None
    floor: int | None        # the place's floor; may differ from its node's (e.g. a room reached via an entrance)
    accessible: bool | None  # the place itself (e.g. an accessible restroom), separate from edges
    notes: str | None


@dataclass(frozen=True)
class Campus:
    """One fully validated campus. Read-only: mappings are MappingProxyType, sequences are tuples."""
    id: str
    name: str                # display name from campus.csv, else the id
    buildings: Mapping[str, Building]
    nodes: Mapping[str, Node]
    adjacency: Mapping[str, tuple[tuple[str, Edge], ...]]     # node_id -> ((neighbor_id, Edge), ...)
    entrances_by_building: Mapping[str, tuple[str, ...]]     # only buildings that have entrances
    pois: Mapping[str, POI]

    def entrances_for(self, building_id):
        """Entrance node ids for a building; () if it has none. KeyError if the building doesn't exist."""
        if building_id not in self.buildings:
            raise KeyError(building_id)
        return self.entrances_by_building.get(building_id, ())

"""Building layout: a building's schematic floor plans from the graph (the frontend's floor view)."""
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class LayoutPoint:
    node_id: str
    type: str                # open set: room, corridor, stairs, elevator, entrance, ...
    lat: float
    lon: float
    poi_id: str | None       # the node's first POI by poi_id, if any (what "Route here" routes to)
    name: str | None         # that POI's name


@dataclass(frozen=True)
class FloorLayout:
    segments: tuple[tuple[tuple[float, float], tuple[float, float]], ...]  # ((lat, lon), (lat, lon)) per edge
    points: tuple[LayoutPoint, ...]


@dataclass(frozen=True)
class BuildingLayout:
    floors: tuple[int, ...]               # floors of the building's indoor nodes, ascending; () = no interior
    by_floor: Mapping[int, FloorLayout]   # one entry per floor in `floors`


def building_layout(campus, building_id):
    """A building's schematic floor plans, from the graph: what the frontend draws for each floor.

    Points: every node with this building_id on a floor that has indoor nodes (rooms,
    corridors, stairs, elevators, and doors on that floor). Segments: edges whose two
    ends are both in this building, on the same floor, with at least one end indoors
    (corridors, door -> corridor). Stairs/elevator edges join two floors, so they're never
    segments. Parallel edges give one segment. Unknown building raises KeyError.
    """
    if building_id not in campus.buildings:
        raise KeyError(building_id)
    mine = {nid: n for nid, n in campus.nodes.items() if n.building_id == building_id}
    floors = tuple(sorted({n.floor for n in mine.values() if n.indoor}))
    if not floors:
        return BuildingLayout((), MappingProxyType({}))

    first_poi = {}  # node_id -> its first POI by poi_id
    for p in sorted(campus.pois.values(), key=lambda p: p.id):
        if p.node_id in mine:
            first_poi.setdefault(p.node_id, p)

    points = {f: [] for f in floors}
    segments = {f: [] for f in floors}
    seen = set()
    for nid in sorted(mine):
        n = mine[nid]
        if n.floor not in points:
            continue
        p = first_poi.get(nid)
        points[n.floor].append(LayoutPoint(nid, n.type, n.x_or_lat, n.y_or_lon,
                                           p.id if p else None, p.name if p else None))
        for other_id, _ in campus.adjacency[nid]:
            other = mine.get(other_id)
            pair = frozenset((nid, other_id))
            if other is None or other.floor != n.floor or not (n.indoor or other.indoor) or pair in seen:
                continue
            seen.add(pair)
            segments[n.floor].append(((n.x_or_lat, n.y_or_lon), (other.x_or_lat, other.y_or_lon)))
    return BuildingLayout(floors, MappingProxyType(
        {f: FloorLayout(tuple(segments[f]), tuple(points[f])) for f in floors}))

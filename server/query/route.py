"""Routes: a GPS point, POI, entrance or building -> a building's best entrance, one POI's
node, or one specific entrance. Totals, flags and floor info come from the edges taken."""
from dataclasses import dataclass

from models import Edge
from routing import IMPASSABLE, NoPath, shortest_path, walk, wheelchair

from .snap import START, TooFar, snap

MODES = {  # mode name -> (cost function factory, travel speed in m/s); wheelchair speed is a placeholder
    "walk": (walk, 1.4),
    "wheelchair": (wheelchair, 1.1),
}


@dataclass(frozen=True)
class Flag:
    """A route segment whose edge isn't known to be wheelchair-accessible (for walking-route warnings)."""
    index: int                 # segment coords[index] -> coords[index + 1], i.e. Route.edges[index]
    accessible: bool | None    # False = known not accessible, None = unknown
    edge_type: str | None      # copied from the edge; the frontend uses it for wording ("steps")


@dataclass(frozen=True)
class FloorChange:
    """A route segment whose ends are on different floors (stairs, elevator, ramp)."""
    index: int                 # segment coords[index] -> coords[index + 1], i.e. Route.edges[index]
    from_floor: int
    to_floor: int
    edge_type: str | None      # copied from the edge ("steps", "elevator"); for wording later


@dataclass(frozen=True)
class Route:
    coords: tuple[tuple[float, float], ...]  # (lat, lon) polyline: the start (snapped point or node), then each node
    distance_m: float          # along the graph: sum of the meters edges taken (floor changes excluded)
    approach_m: float          # GPS point -> snapped point, off the graph (not in coords); 0 for a node start
    duration_s: float          # (approach_m + distance_m) / the mode's speed + seconds edges
    start_id: str | None       # node the path starts from (the door left by, for from_building); None for GPS
    end_id: str                # node reached
    entrance_id: str | None    # the door used: the last entrance on the path (= end_id when routing to a door)
    entrance_name: str | None  # name of a POI on that door (first by poi_id), if any
    building_id: str | None    # the reached node's building
    nodes: tuple[str, ...]     # node ids, parallel to coords; may start with START (not in campus.nodes)
    edges: tuple[Edge, ...]    # edge taken between each pair (len(nodes) - 1); START's is a half-edge
    flags: tuple[Flag, ...]    # segments not known to be accessible, by index; always () for wheelchair
    floors: tuple[int, ...]    # floor per coord (parallel to coords)
    indoor: tuple[bool, ...]   # indoor per coord (parallel to coords); floor 0 exists outside and in
    floor_changes: tuple[FloorChange, ...]  # segments whose ends are on different floors, by index


@dataclass(frozen=True)
class NoRoute:
    reason: str                       # "too_far" | "no_entrances" | "start_no_entrances" | "no_path"
    distance_m: float | None = None   # too_far only: GPS point -> nearest usable edge


def is_entrance(campus, node_id):
    """True if node_id is a node of type "entrance" (the only nodes to_entrance accepts)."""
    node = campus.nodes.get(node_id)
    return node is not None and node.type == "entrance"


def route(campus, lat=None, lon=None, *, from_poi=None, from_entrance=None, from_building=None,
          to_building=None, to_poi=None, to_entrance=None, mode="walk"):
    """Route from a start to a building (its best entrance), a POI, or one specific entrance.

    Start: a GPS point (lat and lon, snapped onto an outdoor edge), a POI (its node), an
    entrance's node_id, or a building (leaving by its best entrance: every entrance is a
    source, like to_building's targets). Exactly one start and exactly one of to_building /
    to_poi / to_entrance. Caller bugs raise: not exactly one start or target, lat without lon,
    or unknown mode -> ValueError; unknown building or POI, or a from_/to_entrance that isn't
    an entrance node -> KeyError; bad lat/lon -> ValueError. A target building with no
    entrances gives NoRoute("no_entrances"), checked before a start building with none
    ("start_no_entrances").
    """
    gps = lat is not None or lon is not None
    if gps and (lat is None or lon is None):
        raise ValueError("give both lat and lon")
    if gps + sum(s is not None for s in (from_poi, from_entrance, from_building)) != 1:
        raise ValueError("give exactly one start: lat/lon, from_poi, from_entrance, from_building")
    if sum(t is not None for t in (to_building, to_poi, to_entrance)) != 1:
        raise ValueError("give exactly one of to_building, to_poi, to_entrance")
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; expected one of {sorted(MODES)}")
    make_cost_fn, speed = MODES[mode]
    cost_fn = make_cost_fn(campus.nodes, speed)

    if to_building is not None:
        targets = campus.entrances_for(to_building)
    elif to_poi is not None:
        targets = (campus.pois[to_poi].node_id,)
    else:
        targets = (_entrance(campus, to_entrance),)
    if from_poi is not None:
        sources = (campus.pois[from_poi].node_id,)
    elif from_entrance is not None:
        sources = (_entrance(campus, from_entrance),)
    elif from_building is not None:
        sources = campus.entrances_for(from_building)
    if not targets:
        return NoRoute("no_entrances")
    if not gps and not sources:
        return NoRoute("start_no_entrances")
    if from_building is not None:
        # Leave only by a door passable in the mode. The door rule blocks a door's edges, but
        # a source that is also a target needs none (X -> X would end at a stepped door).
        sources = tuple(n for n in sources
                        if any(cost_fn(e, n) is not IMPASSABLE for _, e in campus.adjacency[n]))

    # A GPS point snaps onto an outdoor edge passable in the mode (maybe inserting START);
    # picked nodes (POI, entrance, a building's entrances) need no snapping and may be indoors.
    s = None
    if gps:
        s = snap(campus, lat, lon, cost_fn)
        if isinstance(s, TooFar):
            return NoRoute("too_far", s.distance_m)
        sources, adjacency, approach = (s.node_id,), s.adjacency, s.distance_m
    else:
        adjacency, approach = campus.adjacency, 0.0

    path = shortest_path(adjacency, set(sources), targets, cost_fn)
    if isinstance(path, NoPath):
        return NoRoute("no_path")

    first = (s.lat, s.lon) if gps else (campus.nodes[path.nodes[0]].x_or_lat, campus.nodes[path.nodes[0]].y_or_lon)
    coords = (first,) + tuple(
        (campus.nodes[n].x_or_lat, campus.nodes[n].y_or_lon) for n in path.nodes[1:])
    meters, secs = _edge_totals(path.edges)
    floors, indoor, floor_changes = _floor_info(campus, path, s)
    end = campus.nodes[path.nodes[-1]]
    door = next((n for n in reversed(path.nodes) if is_entrance(campus, n)), None)
    return Route(
        coords=coords,
        distance_m=meters,
        approach_m=approach,
        duration_s=(approach + meters) / speed + secs,
        start_id=None if gps else path.nodes[0],
        end_id=end.id,
        entrance_id=door,
        entrance_name=poi_name_at(campus, door) if door is not None else None,
        building_id=end.building_id,
        nodes=path.nodes,
        edges=path.edges,
        flags=flags_for(path.edges),
        floors=floors,
        indoor=indoor,
        floor_changes=floor_changes,
    )


def _entrance(campus, node_id):
    """node_id if it's an entrance node, else KeyError (from_entrance / to_entrance)."""
    if not is_entrance(campus, node_id):
        raise KeyError(f"unknown entrance {node_id!r}")
    return node_id


def _floor_info(campus, path, start):
    """(floors, indoor) per path node, and a FloorChange per edge whose ends' floors differ.

    START isn't in campus.nodes: its floor comes from the Snap (`start`, None for a node
    start), and it's always outdoors (snapping only uses outdoor edges).
    """
    floors, indoor = [], []
    for n in path.nodes:
        if n == START:
            floors.append(start.floor)
            indoor.append(False)
        else:
            floors.append(campus.nodes[n].floor)
            indoor.append(campus.nodes[n].indoor)
    changes = tuple(FloorChange(i, floors[i], floors[i + 1], e.edge_type)
                    for i, e in enumerate(path.edges) if floors[i] != floors[i + 1])
    return tuple(floors), tuple(indoor), changes


def flags_for(edges):
    """One Flag per edge that isn't known to be accessible (False or None), in route order.

    A half-edge from START keeps its edge's accessible/edge_type, so starting partway along
    steps flags index 0. Consecutive flags are not merged; grouping is a display question.
    """
    return tuple(Flag(i, e.accessible, e.edge_type) for i, e in enumerate(edges) if e.accessible is not True)


def _edge_totals(edges):
    """(meters, seconds) summed from the edges' own costs, by unit.

    Independent of the cost function, which may add penalties that are neither. Seconds
    edges (stairs, elevators) count toward time only, never toward distance.
    """
    totals = {"meters": 0.0, "seconds": 0.0}
    for e in edges:
        if e.cost_unit not in totals:
            raise ValueError(f"route totals expect meters or seconds, got {e.cost_unit!r}")
        totals[e.cost_unit] += e.cost
    return totals["meters"], totals["seconds"]


def poi_name_at(campus, node_id):
    """Display name for a node: its first POI by poi_id, or None if it has no POI."""
    names = [p for p in campus.pois.values() if p.node_id == node_id]
    return min(names, key=lambda p: p.id).name if names else None

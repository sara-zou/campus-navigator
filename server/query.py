"""Query layer: turns user-facing requests into routing calls and readable results.

Search is a pure lookup over names; it never touches the graph.
Snapping puts a GPS point onto the nearest edge via a temporary node, layered
over the campus adjacency without mutating it. Routing goes GPS point -> a
building's best entrance, or -> one POI's node.
"""
import math
from collections.abc import Mapping
from dataclasses import dataclass

from loader import Edge, haversine_m
from routing import IMPASSABLE, NoPath, distance, shortest_path, wheelchair

DEFAULT_SEARCH_LIMIT = 20

SNAP_MAX_M = 200          # GPS points farther than this from any usable edge get TooFar
ENDPOINT_EPS_M = 0.5      # a projection this close to an existing node just uses that node
START = "__start__"       # id of the temporary node; the loader rejects node ids starting with "__"
EARTH_R_M = 6_371_000

MODES = {  # mode name -> (cost function, travel speed in m/s); wheelchair speed is a placeholder
    "walk": (distance, 1.4),
    "wheelchair": (wheelchair, 1.1),
}

# Rank tiers, best first. Lower number = earlier in results.
EXACT, PREFIX, WORD_PREFIX, SUBSTRING, ID_EXACT = range(5)
KIND_ORDER = {"building": 0, "poi": 1}  # tie-break within a tier
# POI categories that search reports as their building: a door's name is just another
# way to find the building, and routing to the building picks its best door anyway.
FOLD_INTO_BUILDING = frozenset({"entrance"})


@dataclass(frozen=True)
class SearchResult:
    kind: str                # "building" | "poi"
    id: str                  # building_id or poi_id
    name: str
    building_id: str | None  # a building's own id; a POI's building, if any


# --- search ---

def search(campus, q, limit=DEFAULT_SEARCH_LIMIT):
    """Buildings and POIs whose name matches q, best first, at most `limit`.

    Case-insensitive; q is trimmed and its inner whitespace collapsed. Blank q gives ().
    Ranking: exact name, name prefix, word prefix, other substring, and last,
    buildings whose id equals q (only if not already matched by name).
    Ties: buildings before POIs, then name, then id.

    POIs in FOLD_INTO_BUILDING (with a building_id) are reported as their building,
    once, at the best tier among the building's name and those POIs' names. Folding
    happens before `limit`, so folded POIs never take up result slots.
    """
    needle = _normalize(q)
    if not needle:
        return ()

    ranked = []          # (tier, kind order, name, id, result)
    building_tier = {}   # building_id -> best tier from its name, its id, or its folded POIs

    def add(tier, result):
        ranked.append((tier, KIND_ORDER[result.kind], result.name.casefold(), result.id, result))

    def match_building(building_id, tier):
        building_tier[building_id] = min(tier, building_tier.get(building_id, tier))

    for b in campus.buildings.values():
        tier = _name_tier(b.name, needle)
        if tier is None and b.id.casefold() == needle:
            tier = ID_EXACT
        if tier is not None:
            match_building(b.id, tier)

    for p in campus.pois.values():
        tier = _name_tier(p.name, needle)
        if tier is None:
            continue
        if p.category in FOLD_INTO_BUILDING and p.building_id is not None:
            match_building(p.building_id, tier)
        else:
            add(tier, SearchResult("poi", p.id, p.name, p.building_id))

    for building_id, tier in building_tier.items():
        b = campus.buildings[building_id]
        add(tier, SearchResult("building", b.id, b.name, b.id))

    ranked.sort(key=lambda r: r[:4])
    return tuple(r[4] for r in ranked[:limit])


def _normalize(s):
    return " ".join(s.split()).casefold()


def _name_tier(name, needle):
    """Which rank tier `name` falls in for an already-normalized needle, or None if no match."""
    hay = _normalize(name)
    if hay == needle:
        return EXACT
    if hay.startswith(needle):
        return PREFIX
    i = hay.find(needle)
    if i < 0:
        return None
    while i >= 0:  # word prefix: some occurrence starts right after a non-alphanumeric char
        if not hay[i - 1].isalnum():
            return WORD_PREFIX
        i = hay.find(needle, i + 1)
    return SUBSTRING


# --- snapping ---

@dataclass(frozen=True)
class Snap:
    node_id: str          # START, or an existing node if the point snapped onto an endpoint
    lat: float            # the snapped point (where the route's polyline starts)
    lon: float
    distance_m: float     # GPS point -> snapped point
    adjacency: Mapping    # campus.adjacency, or an overlay that also contains START


@dataclass(frozen=True)
class TooFar:
    """The nearest usable edge is beyond max_m. distance_m is inf if no edge is usable at all."""
    distance_m: float


def snap(campus, lat, lon, cost_fn=None, max_m=SNAP_MAX_M):
    """Snap a GPS point to the nearest point on an edge, as Snap or TooFar.

    With cost_fn, only edges passable (from either end) in that mode count, so a
    wheelchair start never lands on a steps edge. Mid-edge, every parallel edge
    between the chosen pair is split at that point into two halves around a
    temporary START node, keeping edge_type and accessible so cost functions still
    apply. Invalid lat/lon raises ValueError.
    """
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError(f"invalid lat/lon: {lat}, {lon}")

    # local flat-earth meters around the GPS point, which sits at the origin
    kx = EARTH_R_M * math.cos(math.radians(lat)) * math.pi / 180  # meters per degree lon
    ky = EARTH_R_M * math.pi / 180                                 # meters per degree lat

    def to_xy(node):
        return (node.y_or_lon - lon) * kx, (node.x_or_lat - lat) * ky

    best = None  # (planar distance, (u, v), t, (qx, qy), (ax, ay, bx, by)); u < v so ties are deterministic
    seen = set()  # each undirected Edge object appears under both of its ends
    for n1, neighbors in campus.adjacency.items():
        for n2, edge in neighbors:
            if id(edge) in seen:
                continue
            seen.add(id(edge))
            if cost_fn is not None and cost_fn(edge, n1) is IMPASSABLE and cost_fn(edge, n2) is IMPASSABLE:
                continue
            u, v = sorted((n1, n2))
            a, b = campus.nodes[u], campus.nodes[v]
            if a.coord_system != "latlon" or b.coord_system != "latlon":
                continue
            (ax, ay), (bx, by) = to_xy(a), to_xy(b)
            t, q = _project_origin(ax, ay, bx, by)
            d = math.hypot(*q)
            if best is None or (d, (u, v)) < best[:2]:
                best = (d, (u, v), t, q, (ax, ay, bx, by))

    if best is None:
        return TooFar(math.inf)
    _, (u, v), t, (qx, qy), (ax, ay, bx, by) = best
    q_lat, q_lon = lat + qy / ky, lon + qx / kx
    dist = haversine_m(lat, lon, q_lat, q_lon)
    if dist > max_m:
        return TooFar(dist)

    for node_id, (nx, ny) in ((u, (ax, ay)), (v, (bx, by))):
        if math.hypot(qx - nx, qy - ny) <= ENDPOINT_EPS_M:
            n = campus.nodes[node_id]
            return Snap(node_id, n.x_or_lat, n.y_or_lon, haversine_m(lat, lon, n.x_or_lat, n.y_or_lon),
                        campus.adjacency)

    return Snap(START, q_lat, q_lon, dist, _overlay(campus.adjacency, u, v, t))


def _project_origin(ax, ay, bx, by):
    """Closest point to the origin on segment A-B: (t along A->B in [0, 1], (x, y))."""
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    t = 0.0 if length_sq == 0 else min(1.0, max(0.0, -(ax * dx + ay * dy) / length_sq))
    return t, (ax + t * dx, ay + t * dy)


def _overlay(adjacency, u, v, t):
    """Adjacency with START inserted at fraction t along every u-v edge (u-side half costs t * cost)."""
    to_u, to_v = [], []
    for neighbor, e in adjacency[u]:
        if neighbor == v:
            to_u.append(Edge(START, u, t * e.cost, e.cost_unit, e.edge_type, e.accessible))
            to_v.append(Edge(START, v, (1 - t) * e.cost, e.cost_unit, e.edge_type, e.accessible))
    extra = {
        START: tuple((u, h) for h in to_u) + tuple((v, h) for h in to_v),
        u: adjacency[u] + tuple((START, h) for h in to_u),
        v: adjacency[v] + tuple((START, h) for h in to_v),
    }
    return _Overlay(adjacency, extra)


class _Overlay(Mapping):
    """Read-only view: `extra` entries win, everything else falls through to `base`."""

    def __init__(self, base, extra):
        self._base, self._extra = base, extra

    def __getitem__(self, key):
        return self._extra[key] if key in self._extra else self._base[key]

    def __iter__(self):
        yield from self._base
        yield from (k for k in self._extra if k not in self._base)

    def __len__(self):
        return len(self._base) + sum(k not in self._base for k in self._extra)


# --- routes ---

@dataclass(frozen=True)
class Route:
    coords: tuple[tuple[float, float], ...]  # (lat, lon) polyline: the snapped point, then each node
    distance_m: float          # along the graph: sum of the edges taken, in meters
    approach_m: float          # GPS point -> snapped point, off the graph (not in coords)
    duration_s: float          # (approach_m + distance_m) / the mode's speed
    entrance_id: str           # node reached
    entrance_name: str | None  # name of a POI on that node (first by poi_id), if any
    building_id: str | None    # the reached node's building
    nodes: tuple[str, ...]     # node ids, parallel to coords; may start with START (not in campus.nodes)
    edges: tuple[Edge, ...]    # edge taken between each pair (len(nodes) - 1); START's is a half-edge


@dataclass(frozen=True)
class NoRoute:
    reason: str                       # "too_far" | "no_entrances" | "no_path"
    distance_m: float | None = None   # too_far only: GPS point -> nearest usable edge


def route(campus, lat, lon, *, to_building=None, to_poi=None, mode="walk"):
    """Route from a GPS point to a building (its best entrance) or a POI, as Route or NoRoute.

    Exactly one of to_building / to_poi. Caller bugs raise: both or neither given or
    unknown mode -> ValueError, unknown building or POI -> KeyError, bad lat/lon -> ValueError.
    """
    if (to_building is None) == (to_poi is None):
        raise ValueError("give exactly one of to_building, to_poi")
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; expected one of {sorted(MODES)}")
    cost_fn, speed = MODES[mode]

    if to_building is not None:
        targets = campus.entrances_for(to_building)
        if not targets:
            return NoRoute("no_entrances")
    else:
        targets = (campus.pois[to_poi].node_id,)

    s = snap(campus, lat, lon, cost_fn)
    if isinstance(s, TooFar):
        return NoRoute("too_far", s.distance_m)

    path = shortest_path(s.adjacency, {s.node_id}, targets, cost_fn)
    if isinstance(path, NoPath):
        return NoRoute("no_path")

    coords = ((s.lat, s.lon),) + tuple(
        (campus.nodes[n].x_or_lat, campus.nodes[n].y_or_lon) for n in path.nodes[1:])
    meters = sum(_edge_meters(e) for e in path.edges)
    end = campus.nodes[path.nodes[-1]]
    return Route(
        coords=coords,
        distance_m=meters,
        approach_m=s.distance_m,
        duration_s=(s.distance_m + meters) / speed,
        entrance_id=end.id,
        entrance_name=poi_name_at(campus, end.id),
        building_id=end.building_id,
        nodes=path.nodes,
        edges=path.edges,
    )


def _edge_meters(edge):
    """Real length, independent of the cost function (which may add penalties that aren't meters)."""
    if edge.cost_unit != "meters":
        raise ValueError(f"route distance expects meters, got {edge.cost_unit!r}")
    return edge.cost


def poi_name_at(campus, node_id):
    """Display name for a node: its first POI by poi_id, or None if it has no POI."""
    names = [p for p in campus.pois.values() if p.node_id == node_id]
    return min(names, key=lambda p: p.id).name if names else None

"""Query layer: turns user-facing requests into routing calls and readable results.

Search is a pure lookup over names; it never touches the graph.
Snapping puts a GPS point onto the nearest edge via a temporary node, layered
over the campus adjacency without mutating it.
"""
import math
from collections.abc import Mapping
from dataclasses import dataclass

from loader import Edge, haversine_m
from routing import IMPASSABLE

DEFAULT_SEARCH_LIMIT = 20

SNAP_MAX_M = 200          # GPS points farther than this from any usable edge get TooFar
ENDPOINT_EPS_M = 0.5      # a projection this close to an existing node just uses that node
START = "__start__"       # id of the temporary node; can't collide with a CSV node id in practice
EARTH_R_M = 6_371_000

# Rank tiers, best first. Lower number = earlier in results.
EXACT, PREFIX, WORD_PREFIX, SUBSTRING, ID_EXACT = range(5)
KIND_ORDER = {"building": 0, "poi": 1}  # tie-break within a tier


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
    """
    needle = _normalize(q)
    if not needle:
        return ()

    ranked = []  # (tier, kind order, name, id, result)

    def add(tier, result):
        ranked.append((tier, KIND_ORDER[result.kind], result.name.casefold(), result.id, result))

    for b in campus.buildings.values():
        tier = _name_tier(b.name, needle)
        if tier is None and b.id.casefold() == needle:
            tier = ID_EXACT
        if tier is not None:
            add(tier, SearchResult("building", b.id, b.name, b.id))

    for p in campus.pois.values():
        tier = _name_tier(p.name, needle)
        if tier is not None:
            add(tier, SearchResult("poi", p.id, p.name, p.building_id))

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

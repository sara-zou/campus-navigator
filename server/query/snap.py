"""Snapping: puts a GPS point onto the nearest outdoor edge via a temporary START node,
layered over the campus adjacency without mutating it."""
import math
from collections.abc import Mapping
from dataclasses import dataclass

from geo import EARTH_R_M, haversine_m
from models import Edge
from routing import IMPASSABLE

SNAP_MAX_M = 200          # GPS points farther than this from any usable edge get TooFar
ENDPOINT_EPS_M = 0.5      # a projection this close to an existing node just uses that node
START = "__start__"       # id of the temporary node; the loader rejects node ids starting with "__"


@dataclass(frozen=True)
class Snap:
    """Where a route starts: a GPS point snapped onto the graph, or a picked node (approach 0)."""
    node_id: str          # START, or an existing node if the point snapped onto an endpoint
    lat: float            # the snapped point (where the route's polyline starts)
    lon: float
    distance_m: float     # GPS point -> snapped point
    adjacency: Mapping    # campus.adjacency, or an overlay that also contains START
    floor: int            # the start's floor; for START, the floor of the nearer edge end


@dataclass(frozen=True)
class TooFar:
    """The nearest usable edge is beyond max_m. distance_m is inf if no edge is usable at all."""
    distance_m: float


def snap(campus, lat, lon, cost_fn=None, max_m=SNAP_MAX_M):
    """Snap a GPS point to the nearest point on an edge, as Snap or TooFar.

    Only outdoor edges count (both ends indoor=False): GPS has no floor and is unreliable
    indoors, so an indoor snap could pick the wrong floor. Indoor starts are picked nodes
    instead (route's from_poi / from_entrance). With cost_fn, only edges passable (from
    either end) in that mode count, so a wheelchair start never lands on a steps edge. Mid-edge, every parallel edge
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
            if a.coord_system != "latlon" or b.coord_system != "latlon" or a.indoor or b.indoor:
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
                        campus.adjacency, n.floor)

    nearer = campus.nodes[u if t <= 0.5 else v]
    return Snap(START, q_lat, q_lon, dist, _overlay(campus.adjacency, u, v, t), nearer.floor)


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

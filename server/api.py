"""HTTP API over the loader and query layers. Thin: no routing or search logic of its own.

Coordinates: everything is (lat, lon) except building geometry, which stays GeoJSON [lon, lat].
"""
import math
import os
from dataclasses import asdict
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from loader import load_all
from query import DEFAULT_SEARCH_LIMIT, MODES, NoRoute, is_entrance, poi_name_at, route, search

DATA_ENV_VAR = "CAMPUS_DATA"
DEFAULT_DATA_ROOT = Path(__file__).resolve().parents[1] / "data"
APP_DIR = Path(__file__).resolve().parents[1] / "app"  # the frontend, served at /
MAX_SEARCH_LIMIT = 100


def resolve_data_root(data_root=None):
    """The data folder: the argument if given, else $CAMPUS_DATA, else <repo>/data."""
    if data_root is not None:
        return Path(data_root)
    env = os.environ.get(DATA_ENV_VAR)
    return Path(env) if env else DEFAULT_DATA_ROOT


def campus_bounds(campus):
    """[[south, west], [north, east]] over the campus's latlon nodes (Leaflet fitBounds order), or None."""
    points = [(n.x_or_lat, n.y_or_lon) for n in campus.nodes.values() if n.coord_system == "latlon"]
    if not points:
        return None
    lats, lons = zip(*points)
    return [[min(lats), min(lons)], [max(lats), max(lons)]]


def building_summaries(campus):
    """Every building with its GeoJSON geometry ([lon, lat]) and entrances (lat/lon), sorted by id."""
    out = []
    for bid in sorted(campus.buildings):
        b = campus.buildings[bid]
        entrances = []
        for nid in campus.entrances_for(bid):
            n = campus.nodes[nid]
            entrances.append({"node_id": nid, "name": poi_name_at(campus, nid), "lat": n.x_or_lat, "lon": n.y_or_lon})
        out.append({"id": bid, "name": b.name, "geometry": b.geometry, "entrances": entrances})
    return out


def create_app(data_root=None):
    """Load every campus up front; bad data raises LoadError here, so the server never starts."""
    campuses = load_all(resolve_data_root(data_root))
    summaries = [{"id": cid, "bounds": campus_bounds(c)} for cid, c in campuses.items()]
    buildings = {cid: building_summaries(c) for cid, c in campuses.items()}

    app = FastAPI(title="Campus Navigator")
    app.state.campuses = campuses

    def get_campus(campus_id: str):
        """Path-param dependency: the campus id, 404 if unknown (case-sensitive)."""
        if campus_id not in campuses:
            raise HTTPException(404, f"unknown campus {campus_id!r}")
        return campus_id

    @app.get("/campuses")
    def list_campuses():
        return summaries

    @app.get("/campuses/{campus_id}/buildings")
    def list_buildings(campus_id: str = Depends(get_campus)):
        return buildings[campus_id]

    @app.get("/campuses/{campus_id}/search")
    def search_campus(campus_id: str = Depends(get_campus), q: str = Query(),
                      limit: int = Query(DEFAULT_SEARCH_LIMIT, ge=1, le=MAX_SEARCH_LIMIT)):
        """[{kind, id, name, building_id}]: route to a building by id, or to a POI by id."""
        return [asdict(r) for r in search(campuses[campus_id], q, limit)]

    @app.get("/campuses/{campus_id}/route")
    def route_campus(campus_id: str = Depends(get_campus),
                     lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180),
                     to_building: str | None = None, to_poi: str | None = None,
                     to_entrance: str | None = None, mode: str = "walk"):
        """GPS point -> a building's best entrance, a POI, or one entrance (by node_id).

        "No route" is a normal 200 answer.

        Inputs are checked here rather than by catching route()'s ValueError/KeyError,
        so anything route() raises after these checks is a bug and surfaces as 500.
        """
        campus = campuses[campus_id]
        if sum(t is not None for t in (to_building, to_poi, to_entrance)) != 1:
            raise HTTPException(400, "give exactly one of to_building, to_poi, to_entrance")
        if mode not in MODES:
            raise HTTPException(400, f"unknown mode {mode!r}; expected one of {sorted(MODES)}")
        if to_building is not None and to_building not in campus.buildings:
            raise HTTPException(404, f"unknown building {to_building!r}")
        if to_poi is not None and to_poi not in campus.pois:
            raise HTTPException(404, f"unknown poi {to_poi!r}")
        if to_entrance is not None and not is_entrance(campus, to_entrance):
            raise HTTPException(404, f"unknown entrance {to_entrance!r}")  # also a node that isn't an entrance

        result = route(campus, lat, lon, to_building=to_building, to_poi=to_poi,
                       to_entrance=to_entrance, mode=mode)
        if isinstance(result, NoRoute):
            d = result.distance_m  # inf (no usable edge at all) isn't valid JSON, so it becomes null
            return {"status": "no_route", "reason": result.reason,
                    "distance_m": d if d is not None and math.isfinite(d) else None}
        return {
            "status": "ok",
            "coords": [list(c) for c in result.coords],  # (lat, lon)
            "distance_m": result.distance_m,
            "approach_m": result.approach_m,
            "duration_s": result.duration_s,
            "entrance_id": result.entrance_id,
            "entrance_name": result.entrance_name,
            "building_id": result.building_id,
            "flags": [asdict(f) for f in result.flags],  # index i = segment coords[i] -> coords[i + 1]
        }

    # Mounted last: routes match in order, so /campuses/... is always the API, never a file.
    app.mount("/", StaticFiles(directory=APP_DIR, html=True), name="app")
    return app

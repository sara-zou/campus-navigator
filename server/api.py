"""HTTP API over the loader and query layers. Thin: no routing or search logic of its own.

Coordinates: everything is (lat, lon) except building geometry, which stays GeoJSON [lon, lat].
"""
import os
from dataclasses import asdict
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query

from loader import load_all
from query import DEFAULT_SEARCH_LIMIT, poi_name_at, search

DATA_ENV_VAR = "CAMPUS_DATA"
DEFAULT_DATA_ROOT = Path(__file__).resolve().parents[1] / "data"
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

    return app

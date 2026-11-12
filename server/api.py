"""HTTP API over the loader and query layers. Thin: no routing or search logic of its own.

Coordinates: everything is (lat, lon) except building geometry, which stays GeoJSON [lon, lat].
"""
import os
from pathlib import Path

from fastapi import FastAPI

from loader import load_all

DATA_ENV_VAR = "CAMPUS_DATA"
DEFAULT_DATA_ROOT = Path(__file__).resolve().parents[1] / "data"


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


def create_app(data_root=None):
    """Load every campus up front; bad data raises LoadError here, so the server never starts."""
    campuses = load_all(resolve_data_root(data_root))
    summaries = [{"id": cid, "bounds": campus_bounds(c)} for cid, c in campuses.items()]

    app = FastAPI(title="Campus Navigator")
    app.state.campuses = campuses

    @app.get("/campuses")
    def list_campuses():
        return summaries

    return app

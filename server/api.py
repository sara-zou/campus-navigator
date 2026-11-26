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
from query import (DEFAULT_SEARCH_LIMIT, MODES, NoRoute, building_layout, is_entrance, poi_name_at, route,
                   search)

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
    """Every building with its GeoJSON geometry ([lon, lat]), entrances (lat/lon) and indoor floors, sorted by id.

    `floors` is the sorted distinct floors of the building's indoor nodes; [] means no indoor map.
    """
    indoor_floors = {}
    for n in campus.nodes.values():
        if n.indoor and n.building_id is not None:
            indoor_floors.setdefault(n.building_id, set()).add(n.floor)
    out = []
    for bid in sorted(campus.buildings):
        b = campus.buildings[bid]
        entrances = []
        for nid in campus.entrances_for(bid):
            n = campus.nodes[nid]
            entrances.append({"node_id": nid, "name": poi_name_at(campus, nid), "lat": n.x_or_lat, "lon": n.y_or_lon,
                              "floor": n.floor, "accessible": n.accessible})
        out.append({"id": bid, "name": b.name, "geometry": b.geometry, "entrances": entrances,
                    "floors": sorted(indoor_floors.get(bid, ()))})
    return out


def layout_summary(campus, building_id):
    """/indoor response: {floors, by_floor: {"<floor>": {segments, points}}}. JSON keys are strings."""
    layout = building_layout(campus, building_id)
    return {
        "floors": list(layout.floors),
        "by_floor": {
            str(f): {
                "segments": [[list(a), list(b)] for a, b in fl.segments],  # [[[lat, lon], [lat, lon]], ...]
                "points": [asdict(p) for p in fl.points],
            }
            for f, fl in layout.by_floor.items()
        },
    }


def create_app(data_root=None):
    """Load every campus up front; bad data raises LoadError here, so the server never starts."""
    campuses = load_all(resolve_data_root(data_root))
    summaries = [{"id": cid, "name": c.name, "bounds": campus_bounds(c)} for cid, c in campuses.items()]
    buildings = {cid: building_summaries(c) for cid, c in campuses.items()}
    layouts = {cid: {bid: layout_summary(c, bid) for bid in c.buildings} for cid, c in campuses.items()}

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

    @app.get("/campuses/{campus_id}/buildings/{building_id}/indoor")
    def building_indoor(building_id: str, campus_id: str = Depends(get_campus)):
        """A building's schematic floor plans for the floor view; {floors: [], by_floor: {}} without an interior."""
        if building_id not in layouts[campus_id]:
            raise HTTPException(404, f"unknown building {building_id!r}")
        return layouts[campus_id][building_id]

    @app.get("/campuses/{campus_id}/search")
    def search_campus(campus_id: str = Depends(get_campus), q: str = Query(),
                      limit: int = Query(DEFAULT_SEARCH_LIMIT, ge=1, le=MAX_SEARCH_LIMIT),
                      building: str | None = None):
        """[{kind, id, name, building_id, floor}]: route to a building by id, or to a POI by id.

        Without `building`: buildings and outdoor POIs. With it: only POIs in that building (rooms, doors).
        """
        campus = campuses[campus_id]
        if building is not None and building not in campus.buildings:
            raise HTTPException(404, f"unknown building {building!r}")
        return [asdict(r) for r in search(campus, q, limit, building=building)]

    @app.get("/campuses/{campus_id}/route")
    def route_campus(campus_id: str = Depends(get_campus),
                     lat: float | None = Query(None, ge=-90, le=90),
                     lon: float | None = Query(None, ge=-180, le=180),
                     from_poi: str | None = None, from_entrance: str | None = None,
                     to_building: str | None = None, to_poi: str | None = None,
                     to_entrance: str | None = None, mode: str = "walk"):
        """GPS point, POI or entrance -> a building's best entrance, a POI, or one entrance (by node_id).

        "No route" is a normal 200 answer.

        Inputs are checked here rather than by catching route()'s ValueError/KeyError,
        so anything route() raises after these checks is a bug and surfaces as 500.
        """
        campus = campuses[campus_id]
        if (lat is None) != (lon is None):
            raise HTTPException(400, "give both lat and lon")
        if sum(s is not None for s in (lat, from_poi, from_entrance)) != 1:
            raise HTTPException(400, "give exactly one start: lat/lon, from_poi, from_entrance")
        if sum(t is not None for t in (to_building, to_poi, to_entrance)) != 1:
            raise HTTPException(400, "give exactly one of to_building, to_poi, to_entrance")
        if mode not in MODES:
            raise HTTPException(400, f"unknown mode {mode!r}; expected one of {sorted(MODES)}")
        if from_poi is not None and from_poi not in campus.pois:
            raise HTTPException(404, f"unknown poi {from_poi!r}")
        if from_entrance is not None and not is_entrance(campus, from_entrance):
            raise HTTPException(404, f"unknown entrance {from_entrance!r}")
        if to_building is not None and to_building not in campus.buildings:
            raise HTTPException(404, f"unknown building {to_building!r}")
        if to_poi is not None and to_poi not in campus.pois:
            raise HTTPException(404, f"unknown poi {to_poi!r}")
        if to_entrance is not None and not is_entrance(campus, to_entrance):
            raise HTTPException(404, f"unknown entrance {to_entrance!r}")  # also a node that isn't an entrance

        result = route(campus, lat, lon, from_poi=from_poi, from_entrance=from_entrance, to_building=to_building, to_poi=to_poi,
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
            "end_id": result.end_id,
            "entrance_id": result.entrance_id,  # the door used; null if the path has none (room -> same room)
            "entrance_name": result.entrance_name,
            "building_id": result.building_id,
            "flags": [asdict(f) for f in result.flags],  # index i = segment coords[i] -> coords[i + 1]
            "floors": list(result.floors),  # parallel to coords
            "indoor": list(result.indoor),  # parallel to coords
            "floor_changes": [asdict(c) for c in result.floor_changes],  # same index convention as flags
        }

    # Mounted last: routes match in order, so /campuses/... is always the API, never a file.
    app.mount("/", StaticFiles(directory=APP_DIR, html=True), name="app")
    return app

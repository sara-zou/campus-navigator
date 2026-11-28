// The controller: both ends of the route, the route itself, the mode and the campus. The only writer of
// state other than floor-view.js (which owns the floor-view fields). The leaf modules report user actions
// to the exported functions here through the callbacks main.js gives them.

import { campusLabel, campusUrl, chooseCampus, placeBuildingId } from "./helpers/common.js";
import { describeFloors } from "./helpers/indoor.js";
import { describeFlags, describeNoRoute, describeRoute, routeParams } from "./helpers/route.js";
import * as api from "./api.js";
import { clearFloorView, refreshFloorView, showRoomFloor, showRouteFloor, updateFocusChoices } from "./floor-view.js";
import {
  clearBuildings, clearRouteLayers, drawBuildings, fitBuilding, highlightBuildings, map, placeStartMarker,
} from "./map-layers.js";
import { fillCampusSelect, savedMode, showRouteInfo, showStatus, updateInsidePrompt, updateSwap } from "./panel.js";
import { createEndpoints } from "./search.js";
import { state } from "./state.js";

let endpoints = null; // {from, to} search boxes, from initController()

// Before initPanel(): the mode radios read state.mode.
export function initController() {
  state.mode = savedMode();
  endpoints = createEndpoints({ onPick: setPlace });
}

// A map click: the user has moved on from typing.
export function closeSearchLists() {
  for (const end of Object.values(endpoints)) end.close();
}

// --- the two ends: start and destination are places (see helpers/common.js) ---

// Highlights both ends' buildings and keeps the floor view on one of them. Once a route is in, the
// destination's building is the one it ends in.
function updateEnds() {
  highlightBuildings(
    placeBuildingId(state.start) ?? state.offeredId,
    state.route?.building_id ?? placeBuildingId(state.destination),
  );
  updateFocusChoices();
}

// The one way to change either end, or both at once (a swap): the state, highlights and boxes, then one
// re-route. changes: {from?: place | null, to?: place | null}; a point can only be a start.
function setPlaces(changes) {
  if (changes.to?.kind === "point") throw new Error("a point can't be a destination"); // a frontend bug
  if ("from" in changes) {
    state.start = changes.from;
    state.offeredId = null; // a new start ends any [Pick a room] offer
    updateInsidePrompt();
  }
  if ("to" in changes) state.destination = changes.to;
  for (const role of Object.keys(changes)) endpoints[role].show(changes[role]);
  showStatus("");
  clearRoute(); // the old route's end building mustn't decide the highlights or the focus
  updateEnds();
  // Only one end set: no route will come to fit the map, so show that end's building and its room's floor.
  // (With both, the route fits the map once it arrives; zooming here too would jump twice.)
  const only = (state.start === null) !== (state.destination === null) ? state.start ?? state.destination : null;
  fitBuilding(placeBuildingId(only));
  if (only !== null) showRoomFloor();
  updateSwap();
  updateRoute();
}

export function setPlace(role, place) {
  setPlaces({ [role]: place });
}

// --- route: re-run whenever the start, the destination or the mode changes ---

let routeAbort = null; // cancels the in-flight request so an old route is never drawn

function clearRoute() {
  routeAbort?.abort();
  clearRouteLayers();
  state.route = null;
  placeStartMarker(); // a picked place's dot leaves with its route
  showRouteInfo(null);
  refreshFloorView(); // the route's floors leave the switcher; a focused building's stay
}

function drawRoute(res) {
  state.route = res;
  placeStartMarker(); // a picked start's dot goes on the route's first point
  updateEnds(); // the building the route ends in is now known; may change the focus
  showRouteFloor(res); // the focused building's part of the route
  const bounds = L.latLngBounds(res.coords);
  if (state.start?.kind === "point") bounds.extend([state.start.lat, state.start.lon]); // the approach line's far end
  map.fitBounds(bounds, { maxZoom: 18, padding: [40, 40] });
  const { title, details } = describeRoute(res, state.start, state.destination, (id) => state.doors.get(id) ?? null);
  showRouteInfo(title, [...details, describeFloors(res)], describeFlags(res.flags));
}

async function updateRoute() {
  clearRoute();
  if (state.start === null || state.destination === null || state.campusId === null) return;
  const ctrl = new AbortController();
  routeAbort = ctrl;
  const [from, dest] = [state.start, state.destination]; // the values this request was made for
  const reqMode = state.mode;
  showRouteInfo("Finding route…");
  try {
    const params = routeParams(from, dest, reqMode);
    const res = await api.route(params, ctrl.signal);
    if (res.status === "ok") drawRoute(res);
    else showRouteInfo("No route", [describeNoRoute(res, dest.name, reqMode, from.kind === "point" ? null : from.name)]);
  } catch (err) {
    if (err.name === "AbortError") return; // superseded by a newer start or destination
    showRouteInfo(null);
    // Inputs come from our own data, so a 400/404 here is a frontend bug, not the user's fault.
    showStatus(`Routing failed: ${err.message}`);
    console.error(err);
  }
}

// --- campus: picked in the dropdown, kept in the URL as ?campus=<id> ---

let campuses = []; // from /campuses, for pickCampus()
let campusAbort = null; // cancels the previous campus's /buildings request, so a slow one never draws late

// Everything tied to the current campus: its ids mean nothing on another campus.
function clearCampus() {
  for (const end of Object.values(endpoints)) end.show(null);
  state.destination = null;
  state.start = null;
  state.offeredId = null;
  updateInsidePrompt(); // no start: hides the prompt
  clearRoute(); // also removes the start marker (no start)
  clearFloorView();
  updateSwap();
  clearBuildings();
  state.buildings.clear();
  state.doors.clear();
  state.campusBounds = null;
  showStatus("");
}

async function loadCampus(campus) {
  campusAbort?.abort();
  const ctrl = new AbortController();
  campusAbort = ctrl;
  clearCampus();
  state.campusId = campus.id;
  if (campus.bounds) {
    state.campusBounds = L.latLngBounds(campus.bounds);
    map.fitBounds(campus.bounds); // [[south, west], [north, east]] is Leaflet's order already
  } else {
    map.setView([0, 0], 2);
    showStatus(`${campusLabel(campus)} has no mapped points`);
  }

  try {
    const buildings = await api.buildings(ctrl.signal);
    for (const b of buildings) {
      state.buildings.set(b.id, b);
      for (const e of b.entrances) state.doors.set(e.node_id, { name: e.name ?? `Entrance of ${b.name}`, building_id: b.id });
    }
    drawBuildings(buildings);
  } catch (err) {
    if (err.name === "AbortError") return; // another campus was picked meanwhile
    showStatus(`Could not load buildings: ${err.message}`); // the map itself stays usable
    console.error(err);
  }
}

// The page's first campus: the one ?campus= asks for, else the first.
export async function openFirstCampus() {
  campuses = await api.campuses();
  const requested = new URLSearchParams(location.search).get("campus");
  const campus = chooseCampus(campuses, requested);
  if (campus === null) throw new Error("no campuses");
  fillCampusSelect(campuses, campus.id);
  await loadCampus(campus);
}

// --- panel actions ---

export function setMode(mode) {
  state.mode = mode;
  updateRoute();
}

export function swapEnds() {
  setPlaces({ from: state.destination, to: state.start });
}

// [Pick a room] in the "you're inside" prompt: the From room box opens for that building while the point
// stays the start.
export function offerRoomsIn(b) {
  state.offeredId = b.id;
  endpoints.from.offerRooms(b);
  updateEnds(); // highlights it as the start's building and opens its floor view
}

export function pickCampus(id) {
  const picked = campuses.find((c) => c.id === id);
  history.replaceState(null, "", campusUrl(location.href, picked.id)); // no reload; a link reopens it
  loadCampus(picked);
}

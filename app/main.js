// Entry point. Leaflet is loaded as a global `L` by index.html.
// Coordinates: the API gives (lat, lon) everywhere except building geometry (GeoJSON [lon, lat]).

import {
  campusLabel, campusUrl, chooseCampus, doorDetails, describeRoomResult, searchParams, classifySegments, describeFlags, describeFloors,
  describeNoRoute, describeRoute, flagLabel, floorLabel, focusChoices, initialFloor, layoutPointStyle, moveBadge,
  placeBuildingId, routeFloorFor, routeFloors,
  routeParams, routeRuns, segmentVisible, switcherFloors, verticalMoves,
} from "./helpers.js";

const map = L.map("map");
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
}).addTo(map);

function showStatus(text) {
  const el = document.getElementById("status");
  el.textContent = text;
  el.hidden = !text;
}

async function getJSON(url, signal) {
  const res = await fetch(url, { signal });
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
  return res.json();
}

let campusId = null; // set by loadCampus(); every campus-scoped URL uses it

// Leaflet treats string tooltips as HTML; build a text node so names can't inject markup.
function textEl(text) {
  const span = document.createElement("span");
  span.textContent = text;
  return span;
}

const BUILDING_STYLE = { color: "#2563eb", weight: 2, fillOpacity: 0.15 };
const NO_ENTRANCE_STYLE = { color: "#6b7280", weight: 1, dashArray: "4 4", fillOpacity: 0.08 };
// bubblingMouseEvents: false keeps a click on a door from also reaching the map (which would move the start).
const ENTRANCE_STYLE = {
  radius: 5, color: "#fff", weight: 1.5, fillColor: "#dc2626", fillOpacity: 1, bubblingMouseEvents: false,
};
// A door not known to be wheelchair-accessible (false or unknown): a hollow red ring.
const STEPPED_ENTRANCE_STYLE = { ...ENTRANCE_STYLE, color: "#dc2626", weight: 2.5, fillColor: "#fff" };

const HIGHLIGHT_STYLE = { weight: 4, fillOpacity: 0.3 }; // the destination's building
const START_HIGHLIGHT_STYLE = { color: "#16a34a", weight: 3, fillOpacity: 0.2 }; // the start's (green, like its dot)

const buildingsById = new Map(); // id -> building from /buildings
const doorsById = new Map(); // entrance node_id -> {name, building_id}, for the result box's door lines
const buildingLayers = new Map(); // id -> its Leaflet polygon layer, for highlighting
let buildingsLayer = null; // the L.geoJSON group; resetStyle() restores a building's normal style
const entrancesLayer = L.layerGroup().addTo(map); // every door dot, so a campus switch can clear them together

function drawBuildings(buildings) {
  for (const b of buildings) buildingsById.set(b.id, b);
  // geometry is GeoJSON [lon, lat]; L.geoJSON handles the order, Polygon, MultiPolygon and holes.
  const features = buildings.map((b) => ({
    type: "Feature",
    geometry: b.geometry,
    properties: { id: b.id, name: b.name, hasEntrances: b.entrances.length > 0 },
  }));
  buildingsLayer = L.geoJSON(features, {
    style: (f) => (f.properties.hasEntrances ? BUILDING_STYLE : NO_ENTRANCE_STYLE),
    onEachFeature: (f, layer) => {
      const label = f.properties.hasEntrances ? f.properties.name : `${f.properties.name} (no entrances mapped)`;
      layer.bindTooltip(textEl(label), { sticky: true });
      buildingLayers.set(f.properties.id, layer);
    },
  }).addTo(map);

  // Entrances are (lat, lon). Added after the polygons so they sit on top.
  for (const b of buildings) {
    for (const e of b.entrances) {
      doorsById.set(e.node_id, { name: e.name ?? `Entrance of ${b.name}`, building_id: b.id });
      const marker = L.circleMarker([e.lat, e.lon], e.accessible === true ? ENTRANCE_STYLE : STEPPED_ENTRANCE_STYLE)
        .bindTooltip(textEl(e.name ?? "Entrance"))
        .addTo(entrancesLayer);
      marker.bindPopup(() => entrancePopup(b, e));
    }
  }
}

// Door popup, built from elements (never an HTML string): name, building (and floor, off the ground),
// accessibility, a wheelchair-mode warning, "Route here" / "Start here". Built when it opens, so it
// follows the current mode.
function entrancePopup(building, entrance) {
  const label = entrance.name ?? `Entrance of ${building.name}`;
  const details = doorDetails(entrance, mode);
  const box = document.createElement("div");
  box.className = "entrance-popup";
  const title = document.createElement("strong");
  title.textContent = label;
  const sub = document.createElement("div");
  sub.textContent = details.floor ? `${building.name} · ${details.floor}` : building.name;
  const access = document.createElement("div");
  access.textContent = details.access;
  box.append(title, sub, access);
  if (details.warning) {
    const warning = document.createElement("div");
    warning.className = "popup-warning";
    warning.textContent = details.warning;
    box.append(warning);
  }
  const buttons = document.createElement("div");
  buttons.className = "entrance-popup-buttons";
  const routeHere = document.createElement("button");
  routeHere.type = "button";
  routeHere.textContent = "Route here";
  const door = { kind: "entrance", id: entrance.node_id, name: label, building_id: building.id };
  routeHere.addEventListener("click", () => {
    map.closePopup();
    setPlace("to", door);
  });
  const startHere = document.createElement("button");
  startHere.type = "button";
  startHere.textContent = "Start here";
  startHere.addEventListener("click", () => {
    map.closePopup();
    setPlace("from", door); // from_entrance: starts at the door node itself, no snapping
  });
  buttons.append(routeHere, startHere);
  box.append(buttons);
  return box;
}

// --- start: a place (see helpers.js): a map click or "use my location" gives a point, search and
// popups give a building, POI or entrance ---

let start = null; // a place, or null
let campusBounds = null; // L.LatLngBounds, set by loadCampus() when the campus has bounds
const START_STYLE = { radius: 8, color: "#fff", weight: 3, fillColor: "#16a34a", fillOpacity: 1 };
const startMarker = L.circleMarker([0, 0], START_STYLE); // moved, never recreated; added on first use

// The green dot: on a point start as soon as it's set. A picked place's position isn't known until the
// route arrives (a building's door, a room), so its dot waits for the route's first point.
function placeStartMarker() {
  const at = start === null ? null : start.kind === "point" ? [start.lat, start.lon] : currentRoute?.coords[0] ?? null;
  if (at === null) {
    startMarker.remove();
    return;
  }
  startMarker.setLatLng(at);
  if (!map.hasLayer(startMarker)) startMarker.addTo(map);
  startMarker.bringToFront();
}

// Clicks on buildings bubble up to the map, so they set the start too. Entrance dots don't (they open
// their popup instead). A map click also closes the search lists: the user has moved on from typing.
map.on("click", (e) => {
  for (const end of Object.values(endpoints)) end.close();
  setPlace("from", { kind: "point", lat: e.latlng.lat, lon: e.latlng.lng, name: "Point on map" });
});

const GEO_ERRORS = {
  1: "Location permission was denied. Click the map to choose a start.",
  2: "Your location isn't available right now. Click the map to choose a start.",
  3: "Finding your location timed out. Try again, or click the map.",
};

const LocateControl = L.Control.extend({
  options: { position: "topleft" }, // added after the zoom control, so it sits below it
  onAdd() {
    const button = L.DomUtil.create("button", "locate-button");
    button.type = "button";
    button.textContent = "Use my location";
    L.DomEvent.disableClickPropagation(button); // the click must not also set the start where the button is
    L.DomEvent.on(button, "click", () => {
      if (button.disabled) return;
      button.disabled = true;
      button.textContent = "Locating…";
      const done = () => {
        button.disabled = false;
        button.textContent = "Use my location";
      };
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          done();
          const { latitude: lat, longitude: lon } = pos.coords;
          setPlace("from", { kind: "point", lat, lon, name: "My location" });
          // Pad ~10% so someone just past the outermost path still counts as on campus.
          if (!campusBounds || campusBounds.pad(0.1).contains([lat, lon])) {
            map.panTo([lat, lon]);
          } else {
            showStatus("You're outside the campus. Click the map to choose a start.");
          }
        },
        (err) => {
          done();
          showStatus(GEO_ERRORS[err.code] ?? `Couldn't get your location: ${err.message}`);
        },
        { enableHighAccuracy: true, timeout: 10000 },
      );
    });
    return button;
  },
});

// Geolocation only exists in secure contexts (https, or localhost); otherwise there's no button.
if ("geolocation" in navigator) new LocateControl().addTo(map);

// --- destination: a place picked from search, a door popup or a floor-view room (never a point) ---

let destination = null; // a place (kind "building" | "poi" | "entrance"), or null
let highlighted = { start: null, end: null }; // building ids drawn highlighted at each end

function layerId(id) {
  return id !== null && buildingLayers.has(id) ? id : null;
}

// Highlights both ends' buildings (one building at both ends gets the destination's style) and keeps the
// floor view on one of them. Once a route is in, the destination's building is the one it ends in.
function updateEnds() {
  for (const id of new Set([highlighted.start, highlighted.end])) {
    if (id !== null) buildingsLayer.resetStyle(buildingLayers.get(id));
  }
  highlighted = {
    start: layerId(placeBuildingId(start)),
    end: layerId(currentRoute?.building_id ?? placeBuildingId(destination)),
  };
  if (highlighted.start !== null && highlighted.start !== highlighted.end) {
    buildingLayers.get(highlighted.start).setStyle(START_HIGHLIGHT_STYLE);
  }
  if (highlighted.end !== null) buildingLayers.get(highlighted.end).setStyle(HIGHLIGHT_STYLE);
  updateFocusChoices();
}

// The one way to change either end, or both at once (a swap): the state, highlights and boxes, then one
// re-route. changes: {from?: place | null, to?: place | null}; a point can only be a start.
function setPlaces(changes) {
  if (changes.to?.kind === "point") throw new Error("a point can't be a destination"); // a frontend bug
  if ("from" in changes) start = changes.from;
  if ("to" in changes) destination = changes.to;
  for (const role of Object.keys(changes)) endpoints[role].show(changes[role]);
  showStatus("");
  clearRoute(); // the old route's end building mustn't decide the highlights or the focus
  updateEnds();
  // Only one end set: no route will come to fit the map, so show that end's building and its room's floor.
  // (With both, the route fits the map once it arrives; zooming here too would jump twice.)
  const only = (start === null) !== (destination === null) ? start ?? destination : null;
  const onlyId = layerId(placeBuildingId(only));
  if (onlyId !== null) map.fitBounds(buildingLayers.get(onlyId).getBounds(), { maxZoom: 18, padding: [40, 40] });
  const floor = preferredFloor();
  if (only !== null && floorsInView().includes(floor)) setViewedFloor(floor);
  updateSwap();
  updateRoute();
}

function setPlace(role, place) {
  setPlaces({ [role]: place });
}

// --- mode: the radio buttons' values are the backend's MODES keys ---

const MODE_STORAGE_KEY = "campus-navigator.mode";
const modeInputs = [...document.querySelectorAll('#mode-toggle input[name="mode"]')];
const knownModes = new Set(modeInputs.map((i) => i.value));

// Storage can throw (private browsing, blocked site data); the page then just starts in walk.
function loadMode() {
  try {
    const saved = localStorage.getItem(MODE_STORAGE_KEY);
    if (knownModes.has(saved)) return saved;
  } catch {}
  return "walk";
}

let mode = loadMode();
for (const input of modeInputs) {
  input.checked = input.value === mode;
  input.addEventListener("change", () => {
    if (!input.checked) return;
    mode = input.value;
    try {
      localStorage.setItem(MODE_STORAGE_KEY, mode);
    } catch {}
    updateRoute();
  });
}

// --- route: re-run whenever the start, the destination or the mode changes ---

map.createPane("route").style.zIndex = 410; // above the floor layout (see the pane order there)
const ROUTE_STYLE = { pane: "route", color: "#6d28d9", weight: 6, opacity: 0.9 };
const APPROACH_STYLE = { pane: "route", color: "#6d28d9", weight: 3, dashArray: "6 8", opacity: 0.9 };
// interactive: false lets clicks pass through the ring to the door dot underneath, so the door's popup
// still opens. Otherwise a tap on the ring would count as a map click and move the start onto the destination.
const ROUTE_ENTRANCE_STYLE = {
  pane: "route", radius: 9, color: "#6d28d9", weight: 4, fillColor: "#fff", fillOpacity: 1, interactive: false,
};
const FLAG_STYLE = { pane: "route", color: "#ea580c", weight: 6, opacity: 1 }; // drawn over the route line
// Indoor parts on floors other than the one selected: faded, so the route's shape stays readable.
const FADED_ROUTE_STYLE = { pane: "route", color: "#6d28d9", weight: 4, opacity: 0.3, dashArray: "4 8" };
const FADED_FLAG_STYLE = { pane: "route", color: "#ea580c", weight: 4, opacity: 0.3, dashArray: "4 8" };
const MIN_APPROACH_DRAWN_M = 1;

const routeLayer = L.layerGroup().addTo(map); // everything drawn for the current route
const routeInfo = document.getElementById("route-info");
let routeAbort = null; // cancels the in-flight request so an old route is never drawn

// details: extra lines under the title; null/empty entries are skipped.
function showRouteInfo(title, details = [], warning = null) {
  routeInfo.replaceChildren();
  routeInfo.hidden = !title;
  if (!title) return;
  const strong = document.createElement("strong");
  strong.textContent = title;
  routeInfo.append(strong);
  for (const detail of details) {
    if (!detail) continue;
    const div = document.createElement("div");
    div.textContent = detail;
    routeInfo.append(div);
  }
  if (warning) {
    const div = document.createElement("div");
    div.className = "route-warning";
    div.textContent = warning;
    routeInfo.append(div);
  }
}

// --- floors: an indoor route is drawn one floor at a time ---

let currentRoute = null; // the "ok" /route response being shown, or null
let viewedFloor = null; // the floor drawn at full strength (route and layout); null when no floors are in view

// A vertical stack of floor buttons, top floor first, under a building switch when both ends are in
// different buildings with indoor maps. Shown while a route goes indoors or a building's floor view is open.
const FloorControl = L.Control.extend({
  options: { position: "bottomright" },
  onAdd() {
    const box = L.DomUtil.create("div", "floor-switcher");
    box.hidden = true;
    this.buildingList = L.DomUtil.create("div", "focus-switch", box);
    this.floorList = L.DomUtil.create("div", "floor-list", box);
    L.DomEvent.disableClickPropagation(box); // a click here must not also move the start
    L.DomEvent.disableScrollPropagation(box);
    return box;
  },
});
const floorControl = new FloorControl().addTo(map);

// Same floors as already shown: only the pressed state changes, and the buttons stay in the page.
// Rebuilding them mid-click would detach the clicked button; Leaflet then can't see that the click
// came from a control and treats it as a map click, which moves the start. Same for the building switch.
function renderFloorControl(floors) {
  const switchIds = focusChoiceIds.length > 1 ? focusChoiceIds : [];
  floorControl.getContainer().hidden = floors.length === 0 && switchIds.length === 0;
  renderFocusSwitch(switchIds);
  const box = floorControl.floorList;
  const shownFloors = [...box.children].map((b) => Number(b.dataset.floor));
  if (shownFloors.length !== floors.length || shownFloors.some((f, i) => f !== floors[i])) {
    box.replaceChildren();
    for (const f of floors) {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.floor = String(f);
      button.textContent = floorLabel(f);
      button.title = `Floor ${floorLabel(f)}`;
      button.addEventListener("click", (e) => {
        e.stopPropagation(); // never reaches the map, even if the buttons are rebuilt meanwhile
        setViewedFloor(f);
      });
      box.append(button);
    }
  }
  for (const button of box.children) {
    button.setAttribute("aria-pressed", String(Number(button.dataset.floor) === viewedFloor));
  }
}

// One button per building the floor view can show (start's first); [] hides the switch.
function renderFocusSwitch(ids) {
  const box = floorControl.buildingList;
  box.hidden = ids.length === 0;
  const shown = [...box.children].map((b) => b.dataset.building);
  if (shown.length !== ids.length || shown.some((id, i) => id !== ids[i])) {
    box.replaceChildren();
    for (const id of ids) {
      const name = buildingsById.get(id)?.name ?? id;
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.building = id;
      button.textContent = name;
      button.title = `Show the floor plan of ${name}`;
      button.addEventListener("click", (e) => {
        e.stopPropagation();
        setFocus(id);
      });
      box.append(button);
    }
  }
  for (const button of box.children) {
    button.setAttribute("aria-pressed", String(button.dataset.building === focusId));
  }
}

// --- floor view: the focused building's layout on viewedFloor (from /buildings/{id}/indoor) ---

// Pane order: buildings and door dots (overlay, 400) < floor layout (405) < route (410) < markers (600).
// The layout must sit above the building polygons, or their fill would take the clicks meant for room dots.
map.createPane("layout").style.zIndex = 405;
const layoutLayer = L.layerGroup().addTo(map);
const LAYOUT_SEGMENT_STYLE = { pane: "layout", color: "#6b7280", weight: 2, opacity: 0.8, interactive: false };
const LAYOUT_PLACE_STYLE = {
  pane: "layout", radius: 4, color: "#fff", weight: 1, fillColor: "#475569", fillOpacity: 1, bubblingMouseEvents: false,
};

let focusId = null; // building whose floor view is open (one of focusChoiceIds), or null
let focusLayout = null; // its /indoor response once loaded
let focusChoiceIds = []; // focusChoices() for the current ends: the buildings the floor view can show
const layoutCache = new Map(); // building id -> /indoor response, for the current campus
let layoutAbort = null;

// New choices (an end moved to another building) reset the focus to the first one: the start's building
// (Sara's call: the route's first indoor floor is there). Same choices keep a building picked in the switch.
function updateFocusChoices() {
  const ids = focusChoices(start, destination, (id) => (buildingsById.get(id)?.floors.length ?? 0) > 0);
  const same = ids.length === focusChoiceIds.length && ids.every((id, i) => id === focusChoiceIds[i]);
  focusChoiceIds = ids;
  if (!same || !ids.includes(focusId)) setFocus(ids[0] ?? null);
  else renderFloorControl(floorsInView());
}

// Which end the focused building is: its route floor is the route's first indoor floor ("start") or last.
function focusEnd() {
  return focusId !== null && focusId === placeBuildingId(start) && start?.kind === "poi" ? "start" : "end";
}

// A picked room's floor at the focused end: shown while there's no route (see refreshFloorView).
function preferredFloor() {
  const place = focusEnd() === "start" ? start : destination;
  return place?.kind === "poi" && placeBuildingId(place) === focusId ? place.floor ?? null : null;
}

function floorsInView() {
  return switcherFloors(focusLayout?.floors ?? [], currentRoute ? routeFloors(currentRoute) : []);
}

// Redraw everything that depends on viewedFloor; pick a floor if the current one isn't in view.
function refreshFloorView() {
  const floors = floorsInView();
  if (!floors.includes(viewedFloor)) {
    const room = preferredFloor();
    const roomFloor = currentRoute === null && floors.includes(room) ? room : null;
    viewedFloor = roomFloor ?? (floors.length > 0 ? initialFloor(focusLayout?.floors ?? [], currentRoute, focusEnd()) : null);
  }
  renderLayout();
  if (currentRoute !== null) renderRouteLayers();
  renderFloorControl(floors);
}

function setViewedFloor(floor) {
  if (floor === viewedFloor) return;
  viewedFloor = floor;
  refreshFloorView();
}

async function setFocus(id) {
  const building = id === null ? null : buildingsById.get(id);
  const next = building && building.floors.length > 0 ? id : null; // no indoor map: no floor view
  if (next === focusId) return;
  layoutAbort?.abort();
  focusId = next;
  focusLayout = next === null ? null : layoutCache.get(next) ?? null;
  viewedFloor = null; // a newly focused building opens on its initial floor
  refreshFloorView();
  if (next === null || focusLayout !== null) return;
  const ctrl = new AbortController();
  layoutAbort = ctrl;
  try {
    const url = `/campuses/${encodeURIComponent(campusId)}/buildings/${encodeURIComponent(next)}/indoor`;
    const layout = await getJSON(url, ctrl.signal);
    layoutCache.set(next, layout);
    if (focusId !== next) return;
    focusLayout = layout;
    viewedFloor = null;
    refreshFloorView();
  } catch (err) {
    if (err.name === "AbortError") return; // focus moved on
    showStatus(`Could not load the floor plan: ${err.message}`);
    console.error(err);
  }
}

// Room popup, built from elements: name, floor, "Route here" / "Start here".
function placePopup(point, floor) {
  const box = document.createElement("div");
  box.className = "entrance-popup";
  const title = document.createElement("strong");
  title.textContent = point.name;
  const sub = document.createElement("div");
  sub.textContent = `${buildingsById.get(focusId)?.name ?? focusId} · Floor ${floorLabel(floor)}`;
  const buttons = document.createElement("div");
  buttons.className = "entrance-popup-buttons";
  const routeHere = document.createElement("button");
  routeHere.type = "button";
  routeHere.textContent = "Route here";
  const room = { kind: "poi", id: point.poi_id, name: point.name, building_id: focusId, floor };
  routeHere.addEventListener("click", () => {
    map.closePopup();
    setPlace("to", room);
  });
  const startHere = document.createElement("button");
  startHere.type = "button";
  startHere.textContent = "Start here";
  startHere.addEventListener("click", () => {
    map.closePopup();
    setPlace("from", room);
  });
  buttons.append(routeHere, startHere);
  box.append(title, sub, buttons);
  return box;
}

function renderLayout() {
  layoutLayer.clearLayers();
  if (focusLayout === null || viewedFloor === null) return;
  const plan = focusLayout.by_floor[String(viewedFloor)]; // keys are strings in JSON
  if (!plan) return; // a route floor this building doesn't have
  for (const seg of plan.segments) L.polyline(seg, LAYOUT_SEGMENT_STYLE).addTo(layoutLayer); // (lat, lon)
  const floor = viewedFloor;
  for (const point of plan.points) {
    const style = layoutPointStyle(point);
    if (style === null) continue;
    if (style === "place") {
      L.circleMarker([point.lat, point.lon], LAYOUT_PLACE_STYLE)
        .bindTooltip(textEl(point.name))
        .bindPopup(() => placePopup(point, floor))
        .addTo(layoutLayer);
    } else {
      const el = document.createElement("span");
      el.textContent = style === "stairs" ? "S" : "E";
      L.marker([point.lat, point.lon], {
        pane: "layout",
        icon: L.divIcon({ className: `layout-core layout-${style}`, html: el, iconSize: null }),
        interactive: false,
      }).addTo(layoutLayer); // not interactive, so no tooltip: the letter and colour say which it is
    }
  }
}

function clearRoute() {
  routeAbort?.abort();
  routeLayer.clearLayers();
  currentRoute = null;
  placeStartMarker(); // a picked place's dot leaves with its route
  showRouteInfo(null);
  refreshFloorView(); // the route's floors leave the switcher; a focused building's stay
}

// Everything on the map for currentRoute, as seen from viewedFloor. Re-run when the floor changes.
function renderRouteLayers() {
  const res = currentRoute;
  routeLayer.clearLayers();
  // Faded runs first, so the selected floor's line sits on top where they overlap.
  const runs = routeRuns(res, viewedFloor).sort((a, b) => a.visible - b.visible);
  for (const run of runs) L.polyline(run.coords, run.visible ? ROUTE_STYLE : FADED_ROUTE_STYLE).addTo(routeLayer);
  // The approach (your point -> where you join the path) is off the graph, so it isn't in coords.
  if (res.approach_m > MIN_APPROACH_DRAWN_M && start?.kind === "point") {
    L.polyline([[start.lat, start.lon], res.coords[0]], APPROACH_STYLE).addTo(routeLayer);
  }
  // Flag i is the segment coords[i] -> coords[i + 1]; only walking routes have any.
  const segments = classifySegments(res);
  for (const flag of res.flags) {
    const visible = segmentVisible(segments[flag.index], viewedFloor);
    L.polyline([res.coords[flag.index], res.coords[flag.index + 1]], visible ? FLAG_STYLE : FADED_FLAG_STYLE)
      .bindTooltip(textEl(flagLabel(flag)), { sticky: true })
      .addTo(routeLayer);
  }
  // No tooltip: a non-interactive layer can't show one; the door dot underneath has the name.
  L.circleMarker(res.coords[res.coords.length - 1], ROUTE_ENTRANCE_STYLE).addTo(routeLayer);
  // Stairs/elevator badges on the selected floor's end of each move; a click jumps to the other end.
  for (const move of verticalMoves(res)) {
    const badge = moveBadge(move, viewedFloor);
    if (badge === null) continue;
    const el = document.createElement("span");
    el.textContent = badge.text;
    L.marker(res.coords[move.index], {
      icon: L.divIcon({ className: "floor-change", html: el, iconSize: null }),
      keyboard: true,
      title: move.label,
    })
      .on("click", () => setViewedFloor(badge.target))
      .addTo(routeLayer);
  }
  if (map.hasLayer(startMarker)) startMarker.bringToFront();
}

function drawRoute(res) {
  currentRoute = res;
  placeStartMarker(); // a picked start's dot goes on the route's first point
  updateEnds(); // the building the route ends in is now known; may change the focus
  // the focused building's part of the route: the start's first indoor floor, the destination's last;
  // an outdoor route keeps the floor
  viewedFloor = routeFloorFor(res, focusEnd()) ?? viewedFloor;
  refreshFloorView();
  const bounds = L.latLngBounds(res.coords);
  if (start?.kind === "point") bounds.extend([start.lat, start.lon]); // the approach line's far end
  map.fitBounds(bounds, { maxZoom: 18, padding: [40, 40] });
  const { title, details } = describeRoute(res, start, destination, (id) => doorsById.get(id) ?? null);
  showRouteInfo(title, [...details, describeFloors(res)], describeFlags(res.flags));
}

async function updateRoute() {
  clearRoute();
  if (start === null || destination === null || campusId === null) return;
  const ctrl = new AbortController();
  routeAbort = ctrl;
  const [from, dest] = [start, destination]; // the values this request was made for
  const reqMode = mode;
  showRouteInfo("Finding route…");
  try {
    const params = routeParams(from, dest, reqMode);
    const res = await getJSON(`/campuses/${encodeURIComponent(campusId)}/route?${params}`, ctrl.signal);
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

// --- search: each end of the route has two boxes (Sara's two-level design). The place box finds buildings
// and outdoor places; once a building with an indoor map is picked, the room box below searches inside
// it (?building=). ---

const SEARCH_DELAY_MS = 200;
const SEARCH_LIMIT = 10;

// One search box: debounced /search as you type, Enter picks the first result (fetching first if this
// text's results aren't in yet), Escape closes the list. Each box cancels its own stale requests.
//   params(q)    -> URLSearchParams for /search, or null to search nothing
//   describe(r)  -> the small grey line under a result
//   onPick(r)    -> a result was chosen (the box already shows its name)
//   onClear()    -> the box was emptied (including its clear "x")
function makeSearchBox({ input, list, params, describe, onPick, onClear }) {
  let timer = null;
  let abort = null; // cancels the in-flight request so an old answer never replaces a newer one
  let shown = { q: null, results: [] }; // what the list currently shows, and for which query

  function cancel() {
    clearTimeout(timer);
    abort?.abort();
  }

  // results: null hides the list, [] shows "No matches".
  function render(q, results) {
    shown = { q, results: results ?? [] };
    list.replaceChildren();
    list.hidden = results === null;
    if (results === null) return;
    if (results.length === 0) {
      const li = document.createElement("li");
      li.className = "no-matches";
      li.textContent = "No matches";
      list.append(li);
      return;
    }
    for (const r of results) {
      const button = document.createElement("button");
      button.type = "button";
      const name = document.createElement("span");
      name.textContent = r.name;
      const kind = document.createElement("small");
      kind.textContent = describe(r);
      button.append(name, kind);
      button.addEventListener("click", () => choose(r));
      const li = document.createElement("li");
      li.append(button);
      list.append(li);
    }
  }

  function close() {
    cancel(); // a pending debounced search would otherwise reopen the list
    render(null, null);
  }

  function choose(result) {
    close();
    input.value = result.name; // setting .value doesn't fire "input", so no new search starts
    onPick(result);
  }

  // pickFirst: Enter was pressed before this query's results were shown.
  async function run(q, pickFirst = false) {
    const p = campusId === null ? null : params(q); // campus not loaded yet, or nothing to search in
    if (p === null) return;
    cancel();
    const ctrl = new AbortController();
    abort = ctrl;
    try {
      const results = await getJSON(`/campuses/${encodeURIComponent(campusId)}/search?${p}`, ctrl.signal);
      if (pickFirst && results.length > 0) choose(results[0]);
      else render(q, results);
    } catch (err) {
      if (err.name === "AbortError") return; // superseded by a newer search
      showStatus(`Search failed: ${err.message}`);
      console.error(err);
    }
  }

  input.addEventListener("input", () => {
    cancel();
    const q = input.value.trim();
    if (!q) {
      render(null, null);
      onClear();
      return;
    }
    timer = setTimeout(() => run(q), SEARCH_DELAY_MS);
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      close();
    } else if (e.key === "Enter") {
      e.preventDefault();
      const q = input.value.trim();
      if (!q) return;
      if (q === shown.q) {
        if (shown.results.length > 0) choose(shown.results[0]);
      } else {
        run(q, true); // results for this text aren't in yet: fetch now and pick the first
      }
    }
  });

  return {
    close,
    setText(text) {
      close();
      input.value = text;
    },
  };
}

// One end of the route ("from" or "to"): its place box and room box. What the boxes show always follows
// the place (show), so a pick from anywhere (search, a popup, a map click, a swap) looks the same.
function makeEndpoint(role) {
  const roomBox = document.getElementById(`${role}-room-box`);
  const roomInput = document.getElementById(`${role}-room-input`);
  let roomBuilding = null; // {id, name}: the building the room box searches in, or null (box hidden)

  const places = makeSearchBox({
    input: document.getElementById(`${role}-input`),
    list: document.getElementById(`${role}-results`),
    params: (q) => searchParams(q, SEARCH_LIMIT),
    describe: describeResult,
    onPick: (r) => setPlace(role, r),
    onClear: () => setPlace(role, null), // an emptied box drops this end, room included
  });

  const rooms = makeSearchBox({
    input: roomInput,
    list: document.getElementById(`${role}-room-results`),
    params: (q) => (roomBuilding === null ? null : searchParams(q, SEARCH_LIMIT, roomBuilding.id)),
    describe: describeRoomResult,
    onPick: (r) => setPlace(role, r),
    onClear: () => {
      // back to the building itself (its best entrance)
      if (roomBuilding !== null) {
        setPlace(role, { kind: "building", id: roomBuilding.id, name: roomBuilding.name, building_id: roomBuilding.id });
      }
    },
  });

  // Show the room box for a building with an indoor map; hide it for anything else (null, no floors).
  function setRoomBuilding(b) {
    roomBuilding = b && b.floors.length > 0 ? { id: b.id, name: b.name } : null;
    rooms.setText("");
    roomBox.hidden = roomBuilding === null;
    if (roomBuilding !== null) {
      roomInput.placeholder = `Search rooms in ${roomBuilding.name}`;
      roomInput.setAttribute("aria-label", `Search rooms in ${roomBuilding.name}`);
    }
  }

  // A POI in a building with an indoor map shows as building + room (room-box results and floor-view
  // rooms); a building opens its room box; anything else (outdoor place, door, point, null) is one line.
  function show(place) {
    const inBuilding = place?.kind === "poi" && place.building_id ? buildingsById.get(place.building_id) : null;
    if (inBuilding && inBuilding.floors.length > 0) {
      places.setText(inBuilding.name);
      setRoomBuilding(inBuilding);
      rooms.setText(place.name);
      return;
    }
    places.setText(place?.name ?? "");
    setRoomBuilding(place?.kind === "building" ? buildingsById.get(place.id) : null);
  }

  return {
    show,
    close() {
      places.close();
      rooms.close();
    },
  };
}

function describeResult(r) {
  if (r.kind === "building") return "Building";
  if (r.building_id === null) return "Place";
  const b = buildingsById.get(r.building_id);
  return `Place in ${b ? b.name : r.building_id}`;
}

const endpoints = { from: makeEndpoint("from"), to: makeEndpoint("to") };

// The swap button: a point (map click, GPS) can't be a destination, so it only works with place starts.
const swapButton = document.getElementById("swap-button");

function updateSwap() {
  const point = start?.kind === "point";
  swapButton.disabled = point || (start === null && destination === null);
  swapButton.title = point ? "A point on the map can't be a destination" : "Swap start and destination";
}

swapButton.addEventListener("click", () => {
  if (!swapButton.disabled) setPlaces({ from: destination, to: start });
});
updateSwap();

// --- campus: picked in the dropdown, kept in the URL as ?campus=<id> ---

const campusSelect = document.getElementById("campus-select");
let campusAbort = null; // cancels the previous campus's /buildings request, so a slow one never draws late

// Everything tied to the current campus: its ids mean nothing on another campus.
function clearCampus() {
  for (const end of Object.values(endpoints)) end.show(null);
  destination = null;
  start = null;
  highlighted = { start: null, end: null };
  clearRoute();
  focusChoiceIds = [];
  setFocus(null);
  layoutCache.clear();
  startMarker.remove();
  updateSwap();
  map.closePopup();
  buildingsLayer?.remove();
  buildingsLayer = null;
  buildingsById.clear();
  doorsById.clear();
  buildingLayers.clear();
  entrancesLayer.clearLayers();
  campusBounds = null;
  showStatus("");
}

async function loadCampus(campus) {
  campusAbort?.abort();
  const ctrl = new AbortController();
  campusAbort = ctrl;
  clearCampus();
  campusId = campus.id;
  if (campus.bounds) {
    campusBounds = L.latLngBounds(campus.bounds);
    map.fitBounds(campus.bounds); // [[south, west], [north, east]] is Leaflet's order already
  } else {
    map.setView([0, 0], 2);
    showStatus(`${campusLabel(campus)} has no mapped points`);
  }

  try {
    drawBuildings(await getJSON(`/campuses/${encodeURIComponent(campus.id)}/buildings`, ctrl.signal));
  } catch (err) {
    if (err.name === "AbortError") return; // another campus was picked meanwhile
    showStatus(`Could not load buildings: ${err.message}`); // the map itself stays usable
    console.error(err);
  }
}

async function init() {
  const campuses = await getJSON("/campuses");
  const requested = new URLSearchParams(location.search).get("campus");
  const campus = chooseCampus(campuses, requested);
  if (campus === null) throw new Error("no campuses");

  for (const c of campuses) {
    const option = document.createElement("option");
    option.value = c.id;
    option.textContent = campusLabel(c);
    campusSelect.append(option);
  }
  campusSelect.value = campus.id;
  campusSelect.hidden = campuses.length < 2; // nothing to pick between
  campusSelect.addEventListener("change", () => {
    const picked = campuses.find((c) => c.id === campusSelect.value);
    history.replaceState(null, "", campusUrl(location.href, picked.id)); // no reload; a link reopens it
    loadCampus(picked);
  });

  await loadCampus(campus);
}

init().catch((err) => {
  map.setView([0, 0], 2);
  showStatus(`Could not load campus data: ${err.message}`);
  console.error(err);
});

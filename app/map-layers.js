// Everything drawn on the map except the floor view: the base map, buildings and door dots (with their
// popup and highlights), the start marker, "Use my location", and the route. Reads state, never writes
// it: changes go out through the handlers given to initMapLayers().
// Coordinates: the API gives (lat, lon) everywhere except building geometry (GeoJSON [lon, lat]).

import { doorDetails } from "./helpers/common.js";
import { classifySegments, moveBadge, routeRuns, segmentVisible, verticalMoves } from "./helpers/indoor.js";
import { flagLabel } from "./helpers/route.js";
import { showStatus } from "./panel.js";
import { state } from "./state.js";

let handlers = null; // {onPick, onFloor}, from initMapLayers()

export const map = L.map("map");
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
}).addTo(map);

// Pane order: buildings and door dots (overlay, 400) < floor layout (405) < route (410) < markers (600).
// The layout must sit above the building polygons, or their fill would take the clicks meant for room dots.
map.createPane("layout").style.zIndex = 405;
map.createPane("route").style.zIndex = 410;

// Leaflet treats string tooltips as HTML; build a text node so names can't inject markup.
export function textEl(text) {
  const span = document.createElement("span");
  span.textContent = text;
  return span;
}

// --- buildings and doors ---

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

const buildingLayers = new Map(); // id -> its Leaflet polygon layer, for highlighting
let buildingsLayer = null; // the L.geoJSON group; resetStyle() restores a building's normal style
const entrancesLayer = L.layerGroup().addTo(map); // every door dot, so a campus switch can clear them together
let highlighted = { start: null, end: null }; // building ids drawn highlighted at each end

export function drawBuildings(buildings) {
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
  const details = doorDetails(entrance, state.mode);
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
    handlers.onPick("to", door);
  });
  const startHere = document.createElement("button");
  startHere.type = "button";
  startHere.textContent = "Start here";
  startHere.addEventListener("click", () => {
    map.closePopup();
    handlers.onPick("from", door); // from_entrance: starts at the door node itself, no snapping
  });
  buttons.append(routeHere, startHere);
  box.append(buttons);
  return box;
}

function layerId(id) {
  return id !== null && buildingLayers.has(id) ? id : null;
}

// Highlights both ends' buildings (ids may be null or unknown); one building at both ends gets the
// destination's style.
export function highlightBuildings(startId, endId) {
  for (const id of new Set([highlighted.start, highlighted.end])) {
    if (id !== null) buildingsLayer.resetStyle(buildingLayers.get(id));
  }
  highlighted = { start: layerId(startId), end: layerId(endId) };
  if (highlighted.start !== null && highlighted.start !== highlighted.end) {
    buildingLayers.get(highlighted.start).setStyle(START_HIGHLIGHT_STYLE);
  }
  if (highlighted.end !== null) buildingLayers.get(highlighted.end).setStyle(HIGHLIGHT_STYLE);
}

// Zoom to one building, if it's drawn (id may be null).
export function fitBuilding(id) {
  const layer = layerId(id) === null ? null : buildingLayers.get(id);
  if (layer) map.fitBounds(layer.getBounds(), { maxZoom: 18, padding: [40, 40] });
}

// Everything tied to the current campus's buildings: its ids mean nothing on another campus.
export function clearBuildings() {
  highlighted = { start: null, end: null };
  map.closePopup();
  buildingsLayer?.remove();
  buildingsLayer = null;
  buildingLayers.clear();
  entrancesLayer.clearLayers();
}

// --- start marker: a map click or "use my location" gives a point, search and popups give a place ---

const START_STYLE = { radius: 8, color: "#fff", weight: 3, fillColor: "#16a34a", fillOpacity: 1 };
const startMarker = L.circleMarker([0, 0], START_STYLE); // moved, never recreated; added on first use

// The green dot: on a point start as soon as it's set. A picked place's position isn't known until the
// route arrives (a building's door, a room), so its dot waits for the route's first point.
export function placeStartMarker() {
  const at = state.start === null ? null : state.start.kind === "point" ? [state.start.lat, state.start.lon] : state.route?.coords[0] ?? null;
  if (at === null) {
    startMarker.remove();
    return;
  }
  startMarker.setLatLng(at);
  if (!map.hasLayer(startMarker)) startMarker.addTo(map);
  startMarker.bringToFront();
}

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
          handlers.onPick("from", { kind: "point", lat, lon, name: "My location" });
          // Pad ~10% so someone just past the outermost path still counts as on campus.
          if (!state.campusBounds || state.campusBounds.pad(0.1).contains([lat, lon])) {
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

// --- route ---

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

export function clearRouteLayers() {
  routeLayer.clearLayers();
}

// Everything on the map for state.route, as seen from state.viewedFloor. Re-run when the floor changes.
export function renderRouteLayers() {
  const res = state.route;
  routeLayer.clearLayers();
  // Faded runs first, so the selected floor's line sits on top where they overlap.
  const runs = routeRuns(res, state.viewedFloor).sort((a, b) => a.visible - b.visible);
  for (const run of runs) L.polyline(run.coords, run.visible ? ROUTE_STYLE : FADED_ROUTE_STYLE).addTo(routeLayer);
  // The approach (your point -> where you join the path) is off the graph, so it isn't in coords.
  if (res.approach_m > MIN_APPROACH_DRAWN_M && state.start?.kind === "point") {
    L.polyline([[state.start.lat, state.start.lon], res.coords[0]], APPROACH_STYLE).addTo(routeLayer);
  }
  // Flag i is the segment coords[i] -> coords[i + 1]; only walking routes have any.
  const segments = classifySegments(res);
  for (const flag of res.flags) {
    const visible = segmentVisible(segments[flag.index], state.viewedFloor);
    L.polyline([res.coords[flag.index], res.coords[flag.index + 1]], visible ? FLAG_STYLE : FADED_FLAG_STYLE)
      .bindTooltip(textEl(flagLabel(flag)), { sticky: true })
      .addTo(routeLayer);
  }
  // No tooltip: a non-interactive layer can't show one; the door dot underneath has the name.
  L.circleMarker(res.coords[res.coords.length - 1], ROUTE_ENTRANCE_STYLE).addTo(routeLayer);
  // Stairs/elevator badges on the selected floor's end of each move; a click jumps to the other end.
  for (const move of verticalMoves(res)) {
    const badge = moveBadge(move, state.viewedFloor);
    if (badge === null) continue;
    const el = document.createElement("span");
    el.textContent = badge.text;
    L.marker(res.coords[move.index], {
      icon: L.divIcon({ className: "floor-change", html: el, iconSize: null }),
      keyboard: true,
      title: move.label,
    })
      .on("click", () => handlers.onFloor(badge.target))
      .addTo(routeLayer);
  }
  if (map.hasLayer(startMarker)) startMarker.bringToFront();
}

// handlers:
//   onPick(role, place)  a door popup's "Route here" / "Start here", or "Use my location"
//   onFloor(floor)       a route's stairs/elevator badge was clicked
export function initMapLayers(h) {
  handlers = h;
  // Geolocation only exists in secure contexts (https, or localhost); otherwise there's no button.
  if ("geolocation" in navigator) new LocateControl().addTo(map);
}

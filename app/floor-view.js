// The floor view: the floor buttons and building switch (bottom right), and the focused building's
// schematic plan on the viewed floor. The only writer of state.viewedFloor, focusId, focusLayout and
// focusChoiceIds. Room popups' "Route here" / "Start here" go out through initFloorView()'s onPick.

import * as api from "./api.js";
import { floorLabel, placeBuildingId } from "./helpers/common.js";
import { focusChoices, initialFloor, layoutPointStyle, routeFloorFor, routeFloors, startFocusId, switcherFloors } from "./helpers/indoor.js";
import { map, renderRouteLayers, textEl } from "./map-layers.js";
import { showStatus } from "./panel.js";
import { state } from "./state.js";

let handlers = null; // {onPick}, from initFloorView()

// --- floors: an indoor route is drawn one floor at a time ---

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
  const switchIds = state.focusChoiceIds.length > 1 ? state.focusChoiceIds : [];
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
    button.setAttribute("aria-pressed", String(Number(button.dataset.floor) === state.viewedFloor));
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
      const name = state.buildings.get(id)?.name ?? id;
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
    button.setAttribute("aria-pressed", String(button.dataset.building === state.focusId));
  }
}

// --- floor view: the focused building's layout on viewedFloor (from /buildings/{id}/indoor) ---

const layoutLayer = L.layerGroup().addTo(map);
const LAYOUT_SEGMENT_STYLE = { pane: "layout", color: "#6b7280", weight: 2, opacity: 0.8, interactive: false };
const LAYOUT_PLACE_STYLE = {
  pane: "layout", radius: 4, color: "#fff", weight: 1, fillColor: "#475569", fillOpacity: 1, bubblingMouseEvents: false,
};

const layoutCache = new Map(); // building id -> /indoor response, for the current campus
let layoutAbort = null;

// New choices (an end moved to another building) reset the focus to the first one: the start's building
// (Sara's call: the route's first indoor floor is there). Same choices keep a building picked in the switch.
export function updateFocusChoices() {
  const hasFloors = (id) => (state.buildings.get(id)?.floors.length ?? 0) > 0;
  const ids = focusChoices(startFocusId(state.start, state.offeredId), state.destination, hasFloors);
  const same = ids.length === state.focusChoiceIds.length && ids.every((id, i) => id === state.focusChoiceIds[i]);
  state.focusChoiceIds = ids;
  if (!same || !ids.includes(state.focusId)) setFocus(ids[0] ?? null);
  else renderFloorControl(floorsInView());
}

// Which end the focused building is: its route floor is the route's first indoor floor ("start") or last.
function focusEnd() {
  return state.focusId !== null && state.focusId === startFocusId(state.start, state.offeredId) ? "start" : "end";
}

// A picked room's floor at the focused end: shown while there's no route (see refreshFloorView).
function preferredFloor() {
  const place = focusEnd() === "start" ? state.start : state.destination;
  return place?.kind === "poi" && placeBuildingId(place) === state.focusId ? place.floor ?? null : null;
}

function floorsInView() {
  return switcherFloors(state.focusLayout?.floors ?? [], state.route ? routeFloors(state.route) : []);
}

// Redraw everything that depends on viewedFloor; pick a floor if the current one isn't in view.
export function refreshFloorView() {
  const floors = floorsInView();
  if (!floors.includes(state.viewedFloor)) {
    const room = preferredFloor();
    const roomFloor = state.route === null && floors.includes(room) ? room : null;
    state.viewedFloor = roomFloor ?? (floors.length > 0 ? initialFloor(state.focusLayout?.floors ?? [], state.route, focusEnd()) : null);
  }
  renderLayout();
  if (state.route !== null) renderRouteLayers();
  renderFloorControl(floors);
}

export function setViewedFloor(floor) {
  if (floor === state.viewedFloor) return;
  state.viewedFloor = floor;
  refreshFloorView();
}

async function setFocus(id) {
  const building = id === null ? null : state.buildings.get(id);
  const next = building && building.floors.length > 0 ? id : null; // no indoor map: no floor view
  if (next === state.focusId) return;
  layoutAbort?.abort();
  state.focusId = next;
  state.focusLayout = next === null ? null : layoutCache.get(next) ?? null;
  state.viewedFloor = null; // a newly focused building opens on its initial floor
  refreshFloorView();
  if (next === null || state.focusLayout !== null) return;
  const ctrl = new AbortController();
  layoutAbort = ctrl;
  try {
    const layout = await api.indoor(next, ctrl.signal);
    layoutCache.set(next, layout);
    if (state.focusId !== next) return;
    state.focusLayout = layout;
    state.viewedFloor = null;
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
  sub.textContent = `${state.buildings.get(state.focusId)?.name ?? state.focusId} · Floor ${floorLabel(floor)}`;
  const buttons = document.createElement("div");
  buttons.className = "entrance-popup-buttons";
  const routeHere = document.createElement("button");
  routeHere.type = "button";
  routeHere.textContent = "Route here";
  const room = { kind: "poi", id: point.poi_id, name: point.name, building_id: state.focusId, floor };
  routeHere.addEventListener("click", () => {
    map.closePopup();
    handlers.onPick("to", room);
  });
  const startHere = document.createElement("button");
  startHere.type = "button";
  startHere.textContent = "Start here";
  startHere.addEventListener("click", () => {
    map.closePopup();
    handlers.onPick("from", room);
  });
  buttons.append(routeHere, startHere);
  box.append(title, sub, buttons);
  return box;
}

function renderLayout() {
  layoutLayer.clearLayers();
  if (state.focusLayout === null || state.viewedFloor === null) return;
  const plan = state.focusLayout.by_floor[String(state.viewedFloor)]; // keys are strings in JSON
  if (!plan) return; // a route floor this building doesn't have
  for (const seg of plan.segments) L.polyline(seg, LAYOUT_SEGMENT_STYLE).addTo(layoutLayer); // (lat, lon)
  const floor = state.viewedFloor;
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

// A route just arrived (state.route is set): show the focused building's part of it, the start's first
// indoor floor or the destination's last. An outdoor route keeps the floor.
export function showRouteFloor(res) {
  state.viewedFloor = routeFloorFor(res, focusEnd()) ?? state.viewedFloor;
  refreshFloorView();
}

// Only one end is set, so no route will come to pick a floor: show that end's room's floor, if it's in view.
export function showRoomFloor() {
  const floor = preferredFloor();
  if (floorsInView().includes(floor)) setViewedFloor(floor);
}

// Everything tied to the current campus's buildings.
export function clearFloorView() {
  state.focusChoiceIds = [];
  setFocus(null);
  layoutCache.clear();
}

// handlers:
//   onPick(role, place)  a room popup's "Route here" / "Start here"
export function initFloorView(h) {
  handlers = h;
}

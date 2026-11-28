// The side panel outside the search boxes: status line, result box, mode radios, swap button, the
// "you're inside" prompt and the campus picker. Reads state, never writes it: changes go out through
// the handlers given to initPanel().

import { indoorBuildingAt } from "./helpers/indoor.js";
import { campusLabel } from "./helpers/common.js";
import { state } from "./state.js";

let handlers = null; // {onMode, onSwap, onPickRoom, onCampus}, from initPanel()

export function showStatus(text) {
  const el = document.getElementById("status");
  el.textContent = text;
  el.hidden = !text;
}

// --- result box ---

const routeInfo = document.getElementById("route-info");

// details: extra lines under the title; null/empty entries are skipped.
export function showRouteInfo(title, details = [], warning = null) {
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

// --- mode: the radio buttons' values are the backend's MODES keys ---

const MODE_STORAGE_KEY = "campus-navigator.mode";
const modeInputs = [...document.querySelectorAll('#mode-toggle input[name="mode"]')];
const knownModes = new Set(modeInputs.map((i) => i.value));

// The mode saved last time. Storage can throw (private browsing, blocked site data); the page then
// just starts in walk.
export function savedMode() {
  try {
    const saved = localStorage.getItem(MODE_STORAGE_KEY);
    if (knownModes.has(saved)) return saved;
  } catch {}
  return "walk";
}

// --- swap: a point (map click, GPS) can't be a destination, so it only works with place starts ---

const swapButton = document.getElementById("swap-button");

export function updateSwap() {
  const point = state.start?.kind === "point";
  swapButton.disabled = point || (state.start === null && state.destination === null);
  swapButton.title = point ? "A point on the map can't be a destination" : "Swap start and destination";
}

// --- "you're inside <building>": a point start (GPS or map click) inside a building with an indoor map ---

const insidePrompt = document.getElementById("inside-prompt");
let insideBuilding = null; // the building the prompt is about, or null (hidden)

export function updateInsidePrompt() {
  insideBuilding = state.start?.kind === "point" ? indoorBuildingAt(state.start.lat, state.start.lon, [...state.buildings.values()]) : null;
  insidePrompt.hidden = insideBuilding === null;
  if (insideBuilding !== null) {
    insidePrompt.querySelector(".inside-text").textContent = `You're inside ${insideBuilding.name}. Start from a room?`;
  }
}

// --- campus picker: the choice is kept in the URL as ?campus=<id> (see main.js) ---

const campusSelect = document.getElementById("campus-select");

export function fillCampusSelect(campuses, selectedId) {
  for (const c of campuses) {
    const option = document.createElement("option");
    option.value = c.id;
    option.textContent = campusLabel(c);
    campusSelect.append(option);
  }
  campusSelect.value = selectedId;
  campusSelect.hidden = campuses.length < 2; // nothing to pick between
}

// handlers:
//   onMode(mode)          a radio was picked (already saved for next time)
//   onSwap()              the swap button was pressed while enabled
//   onPickRoom(building)  [Pick a room] in the "you're inside" prompt
//   onCampus(campusId)    a campus was picked in the dropdown
export function initPanel(h) {
  handlers = h;

  for (const input of modeInputs) {
    input.checked = input.value === state.mode;
    input.addEventListener("change", () => {
      if (!input.checked) return;
      try {
        localStorage.setItem(MODE_STORAGE_KEY, input.value);
      } catch {}
      handlers.onMode(input.value);
    });
  }

  swapButton.addEventListener("click", () => {
    if (!swapButton.disabled) handlers.onSwap();
  });
  updateSwap();

  // GPS has no floor, so a room is the way to say where inside you are. The point stays the start (it
  // snaps to the nearest outdoor path) until a room is picked: a building start would leave by a door,
  // wrong for a destination in the same building.
  document.getElementById("inside-pick").addEventListener("click", () => {
    const b = insideBuilding;
    if (b === null) return;
    insidePrompt.hidden = true;
    handlers.onPickRoom(b);
  });
  document.getElementById("inside-dismiss").addEventListener("click", () => {
    insidePrompt.hidden = true;
  });

  campusSelect.addEventListener("change", () => handlers.onCampus(campusSelect.value));
}

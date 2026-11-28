// The search boxes: each end of the route has two (Sara's two-level design). The place box finds buildings
// and outdoor places; once a building with an indoor map is picked, the room box below searches inside
// it (?building=). Reads state, never writes it: picks go out through onPick(role, place).

import * as api from "./api.js";
import { searchParams } from "./helpers/common.js";
import { describeRoomResult } from "./helpers/indoor.js";
import { showStatus } from "./panel.js";
import { state } from "./state.js";

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
    const p = state.campusId === null ? null : params(q); // campus not loaded yet, or nothing to search in
    if (p === null) return;
    cancel();
    const ctrl = new AbortController();
    abort = ctrl;
    try {
      const results = await api.search(p, ctrl.signal);
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
function makeEndpoint(role, pick) {
  const roomBox = document.getElementById(`${role}-room-box`);
  const roomInput = document.getElementById(`${role}-room-input`);
  let roomBuilding = null; // {id, name}: the building the room box searches in, or null (box hidden)
  let offering = false; // the room box is open for a [Pick a room] offer; the end's place isn't that building

  const places = makeSearchBox({
    input: document.getElementById(`${role}-input`),
    list: document.getElementById(`${role}-results`),
    params: (q) => searchParams(q, SEARCH_LIMIT),
    describe: describeResult,
    onPick: (r) => pick(role, r),
    onClear: () => pick(role, null), // an emptied box drops this end, room included
  });

  const rooms = makeSearchBox({
    input: roomInput,
    list: document.getElementById(`${role}-room-results`),
    params: (q) => (roomBuilding === null ? null : searchParams(q, SEARCH_LIMIT, roomBuilding.id)),
    describe: describeRoomResult,
    onPick: (r) => pick(role, r),
    onClear: () => {
      // back to the building itself (its best entrance); during an offer, the place (a point) stays
      if (roomBuilding !== null && !offering) {
        pick(role, { kind: "building", id: roomBuilding.id, name: roomBuilding.name, building_id: roomBuilding.id });
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
    offering = false;
    const inBuilding = place?.kind === "poi" && place.building_id ? state.buildings.get(place.building_id) : null;
    if (inBuilding && inBuilding.floors.length > 0) {
      places.setText(inBuilding.name);
      setRoomBuilding(inBuilding);
      rooms.setText(place.name);
      return;
    }
    places.setText(place?.name ?? "");
    setRoomBuilding(place?.kind === "building" ? state.buildings.get(place.id) : null);
  }

  // Open the room box for building b while the end keeps its place (a point): picking a room replaces it.
  function offerRooms(b) {
    setRoomBuilding(b);
    offering = true;
    roomInput.focus();
  }

  return {
    show,
    offerRooms,
    close() {
      places.close();
      rooms.close();
    },
  };
}

function describeResult(r) {
  if (r.kind === "building") return "Building";
  if (r.building_id === null) return "Place";
  const b = state.buildings.get(r.building_id);
  return `Place in ${b ? b.name : r.building_id}`;
}

// Both ends' boxes. onPick(role, place) gets every pick, and null when a place box is emptied.
export function createEndpoints({ onPick }) {
  return { from: makeEndpoint("from", onPick), to: makeEndpoint("to", onPick) };
}

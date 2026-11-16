// Entry point. Leaflet is loaded as a global `L` by index.html.
// Coordinates: the API gives (lat, lon) everywhere except building geometry (GeoJSON [lon, lat]).

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

let campusId = null; // set once in init(); every campus-scoped URL uses it

// Leaflet treats string tooltips as HTML; build a text node so names can't inject markup.
function textEl(text) {
  const span = document.createElement("span");
  span.textContent = text;
  return span;
}

const BUILDING_STYLE = { color: "#2563eb", weight: 2, fillOpacity: 0.15 };
const NO_ENTRANCE_STYLE = { color: "#6b7280", weight: 1, dashArray: "4 4", fillOpacity: 0.08 };
const ENTRANCE_STYLE = { radius: 5, color: "#fff", weight: 1.5, fillColor: "#dc2626", fillOpacity: 1 };

const HIGHLIGHT_STYLE = { weight: 4, fillOpacity: 0.3 };

const buildingsById = new Map(); // id -> building from /buildings
const buildingLayers = new Map(); // id -> its Leaflet polygon layer, for highlighting
let buildingsLayer = null; // the L.geoJSON group; resetStyle() restores a building's normal style

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
      L.circleMarker([e.lat, e.lon], ENTRANCE_STYLE)
        .bindTooltip(textEl(e.name ?? "Entrance"))
        .addTo(map);
    }
  }
}

// --- start point: set by clicking the map or by "use my location"; the backend can't tell which ---

let start = null; // {lat, lon} or null
let campusBounds = null; // L.LatLngBounds, set in init() when the campus has bounds
const START_STYLE = { radius: 8, color: "#fff", weight: 3, fillColor: "#16a34a", fillOpacity: 1 };
const startMarker = L.circleMarker([0, 0], START_STYLE); // moved, never recreated; added on first use

// The only way to change the start. Step 4 hooks in here to re-run the route.
function setStart(lat, lon) {
  start = { lat, lon };
  startMarker.setLatLng([lat, lon]);
  if (!map.hasLayer(startMarker)) startMarker.addTo(map);
  startMarker.bringToFront();
  showStatus("");
}

// Clicks on buildings and entrance dots bubble up to the map, so these set the start too.
map.on("click", (e) => setStart(e.latlng.lat, e.latlng.lng));

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
          setStart(lat, lon);
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

// --- destination: picked from search results ---

let destination = null; // {kind: "building" | "poi", id, name} or null
let highlightedId = null; // building id currently highlighted

function highlightBuilding(id) {
  if (highlightedId !== null) buildingsLayer.resetStyle(buildingLayers.get(highlightedId));
  highlightedId = buildingLayers.has(id) ? id : null;
  if (highlightedId !== null) buildingLayers.get(highlightedId).setStyle(HIGHLIGHT_STYLE);
}

// The only way to change the destination. Step 4b hooks in here to run the route.
function setDestination(result) {
  destination = result ? { kind: result.kind, id: result.id, name: result.name } : null;
  // A POI's location isn't known until a route comes back (no endpoint gives POI coordinates).
  highlightBuilding(result?.kind === "building" ? result.id : null);
  if (highlightedId !== null) {
    map.fitBounds(buildingLayers.get(highlightedId).getBounds(), { maxZoom: 18, padding: [40, 40] });
  }
}

// --- search ---

const searchInput = document.getElementById("search-input");
const searchResults = document.getElementById("search-results");
const SEARCH_DELAY_MS = 200;
const SEARCH_LIMIT = 10;

let searchTimer = null;
let searchAbort = null; // cancels the in-flight request so an old answer never replaces a newer one
let shown = { q: null, results: [] }; // what the list currently shows, and for which query

function describeResult(r) {
  if (r.kind === "building") return "Building";
  if (r.building_id === null) return "Place";
  const b = buildingsById.get(r.building_id);
  return `Place in ${b ? b.name : r.building_id}`;
}

// results: null hides the list, [] shows "No matches".
function renderResults(q, results) {
  shown = { q, results: results ?? [] };
  searchResults.replaceChildren();
  searchResults.hidden = results === null;
  if (results === null) return;
  if (results.length === 0) {
    const li = document.createElement("li");
    li.className = "no-matches";
    li.textContent = "No matches";
    searchResults.append(li);
    return;
  }
  for (const r of results) {
    const button = document.createElement("button");
    button.type = "button";
    const name = document.createElement("span");
    name.textContent = r.name;
    const kind = document.createElement("small");
    kind.textContent = describeResult(r);
    button.append(name, kind);
    button.addEventListener("click", () => pick(r));
    const li = document.createElement("li");
    li.append(button);
    searchResults.append(li);
  }
}

function pick(result) {
  cancelSearch(); // a pending debounced search would otherwise reopen the list
  searchInput.value = result.name; // setting .value doesn't fire "input", so no new search starts
  renderResults(null, null);
  setDestination(result);
}

function cancelSearch() {
  clearTimeout(searchTimer);
  searchAbort?.abort();
}

// pickFirst: Enter was pressed before this query's results were shown.
async function runSearch(q, pickFirst = false) {
  if (campusId === null) return; // campus not loaded yet
  cancelSearch();
  const ctrl = new AbortController();
  searchAbort = ctrl;
  const params = new URLSearchParams({ q, limit: SEARCH_LIMIT });
  try {
    const results = await getJSON(`/campuses/${encodeURIComponent(campusId)}/search?${params}`, ctrl.signal);
    if (pickFirst && results.length > 0) pick(results[0]);
    else renderResults(q, results);
  } catch (err) {
    if (err.name === "AbortError") return; // superseded by a newer search
    showStatus(`Search failed: ${err.message}`);
    console.error(err);
  }
}

searchInput.addEventListener("input", () => {
  cancelSearch();
  const q = searchInput.value.trim();
  if (!q) {
    renderResults(null, null);
    setDestination(null); // an emptied box (including its clear "x") drops the destination
    return;
  }
  searchTimer = setTimeout(() => runSearch(q), SEARCH_DELAY_MS);
});

searchInput.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    cancelSearch();
    renderResults(null, null);
  } else if (e.key === "Enter") {
    e.preventDefault();
    const q = searchInput.value.trim();
    if (!q) return;
    if (q === shown.q) {
      if (shown.results.length > 0) pick(shown.results[0]);
    } else {
      runSearch(q, true); // results for this text aren't in yet: fetch now and pick the first
    }
  }
});

async function init() {
  const campuses = await getJSON("/campuses");
  // Only one campus exists today; a picker comes with the second one.
  const campus = campuses[0];
  campusId = campus.id;
  if (campus.bounds) {
    campusBounds = L.latLngBounds(campus.bounds);
    map.fitBounds(campus.bounds); // [[south, west], [north, east]] is Leaflet's order already
  } else {
    map.setView([0, 0], 2);
    showStatus(`Campus ${campus.id} has no mapped points`);
  }

  try {
    drawBuildings(await getJSON(`/campuses/${encodeURIComponent(campusId)}/buildings`));
  } catch (err) {
    showStatus(`Could not load buildings: ${err.message}`); // the map itself stays usable
    console.error(err);
  }
}

init().catch((err) => {
  map.setView([0, 0], 2);
  showStatus(`Could not load campus data: ${err.message}`);
  console.error(err);
});

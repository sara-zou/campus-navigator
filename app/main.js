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

async function getJSON(url) {
  const res = await fetch(url);
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

function drawBuildings(buildings) {
  // geometry is GeoJSON [lon, lat]; L.geoJSON handles the order, Polygon, MultiPolygon and holes.
  const features = buildings.map((b) => ({
    type: "Feature",
    geometry: b.geometry,
    properties: { id: b.id, name: b.name, hasEntrances: b.entrances.length > 0 },
  }));
  L.geoJSON(features, {
    style: (f) => (f.properties.hasEntrances ? BUILDING_STYLE : NO_ENTRANCE_STYLE),
    onEachFeature: (f, layer) => {
      const label = f.properties.hasEntrances ? f.properties.name : `${f.properties.name} (no entrances mapped)`;
      layer.bindTooltip(textEl(label), { sticky: true });
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

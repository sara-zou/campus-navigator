// Pure helpers used by both route.js and indoor.js: formatting, places, search params, campuses, doors.
// No DOM, no Leaflet, so `node --test app/` can test them. Imports nothing.

// --- formatting ---

export function formatDistance(m) {
  const rounded = Math.round(m / 10) * 10;
  if (rounded < 1000) return `${rounded} m`;
  return `${(m / 1000).toFixed(1)} km`;
}

export function formatDuration(s) {
  const minutes = Math.max(1, Math.round(s / 60));
  if (minutes < 60) return `${minutes} min`;
  const h = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest === 0 ? `${h} h` : `${h} h ${rest} min`;
}

// --- floors ---

// 0 is G, -1 is B1, 1 is 1. A floors.csv with real names is decided in step 6c.
export function floorLabel(n) {
  if (n === 0) return "G";
  return n < 0 ? `B${-n}` : String(n);
}

// --- places ---

// A place is one end of a route: {kind: "building" | "poi" | "entrance", id, name, building_id, ...}
// (an entrance's id is its node_id), or, as a start only, {kind: "point", lat, lon, name}: a map click
// or GPS, which the backend snaps. A point can't be a destination: /route can't route to one.

// The building a place belongs to: a building itself, a POI's or door's building_id; null for a point,
// an outdoor place, or no place.
export function placeBuildingId(place) {
  if (place === null || place === undefined) return null;
  if (place.kind === "building") return place.id;
  return place.kind === "point" ? null : place.building_id ?? null;
}

// --- search ---

// /search query params; with buildingId, the room search inside that building.
export function searchParams(q, limit, buildingId = null) {
  const params = new URLSearchParams({ q, limit });
  if (buildingId !== null) params.set("building", buildingId);
  return params;
}

// --- campuses ---

// The campus to open: the one the URL asks for if it exists, else the first (/campuses is sorted by id).
export function chooseCampus(campuses, requestedId) {
  return campuses.find((c) => c.id === requestedId) ?? campuses[0] ?? null;
}

// The picker's label: campus.csv's name; the API falls back to the id, and so does this.
export function campusLabel(campus) {
  return campus.name || campus.id;
}

// The page URL with ?campus=<id> set, other query params and the hash kept. Used with history.replaceState.
export function campusUrl(href, campusId) {
  const url = new URL(href);
  url.searchParams.set("campus", campusId);
  return url.toString();
}

// --- doors ---

// A door from /buildings -> its popup's details: {floor, access, warning}.
//   floor    "Floor 1" for a door off the ground floor (a door up a hill), else null
//   access   the door's own accessibility: accessible is true / false / null (unknown)
//   warning  in wheelchair mode, for a door that isn't known accessible: the door rule blocks it
//            (unknown is treated like false), so "Route here" would give no accessible path
export function doorDetails(entrance, mode) {
  const access = entrance.accessible === true ? "Wheelchair accessible"
    : entrance.accessible === false ? "Not wheelchair accessible" : "Accessibility unknown";
  return {
    floor: entrance.floor === 0 ? null : `Floor ${floorLabel(entrance.floor)}`,
    access,
    warning: mode === "wheelchair" && entrance.accessible !== true ? "Wheelchair routes can't use this door" : null,
  };
}

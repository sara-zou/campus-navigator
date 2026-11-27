// Pure helpers: no DOM, no Leaflet, so `node --test app/` can test them.

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

// A place is one end of a route: {kind: "building" | "poi" | "entrance", id, name, building_id, ...}
// (an entrance's id is its node_id), or, as a start only, {kind: "point", lat, lon, name}: a map click
// or GPS, which the backend snaps. A point can't be a destination: /route can't route to one.
const PLACE_KINDS = new Set(["building", "poi", "entrance"]);

// The /route param for a place at one end: from_building, to_poi, ...
function placeParam(role, place) {
  if (!PLACE_KINDS.has(place.kind)) {  // a frontend bug
    throw new Error(`unknown ${role === "from" ? "start" : "destination"} kind ${JSON.stringify(place.kind)}`);
  }
  return `${role}_${place.kind}`;
}

export function routeParams(start, destination, mode) {
  const params = new URLSearchParams();
  if (start.kind === "point") {
    params.set("lat", start.lat);
    params.set("lon", start.lon);
  } else {
    params.set(placeParam("from", start), start.id);
  }
  params.set(placeParam("to", destination), destination.id);
  params.set("mode", mode);
  return params;
}

// The building a place belongs to: a building itself, a POI's or door's building_id; null for a point,
// an outdoor place, or no place.
export function placeBuildingId(place) {
  if (place === null || place === undefined) return null;
  if (place.kind === "building") return place.id;
  return place.kind === "point" ? null : place.building_id ?? null;
}

// An "ok" /route response -> what the result box shows: {title, details} (details: lines, nulls skipped).
// start, destination: the places the route was asked for. door(nodeId) -> {name, building_id} or null.
//   title     the destination's name
//   Leave by  a building start: the door the route left by (start_id)
//   Enter by  the door into the building the route ends in (entrance_id is the *last* door on the path,
//             so it's only an entry door if it belongs to that building), unless the destination is that
//             door, or the start was already in that building (no door to enter by)
// The distance includes the approach, because duration_s does too; otherwise the two wouldn't match.
export function describeRoute(res, start, destination, door) {
  const doorName = (id) => door(id)?.name ?? "an entrance";
  const leave = start.kind === "building" && res.start_id !== null ? `Leave by ${doorName(res.start_id)}` : null;
  const last = res.entrance_id === null ? null : door(res.entrance_id);
  const enters = last !== null && last.building_id === res.building_id && destination.kind !== "entrance"
    && placeBuildingId(start) !== res.building_id;
  return {
    title: destination.name,
    details: [
      leave,
      enters ? `Enter by ${res.entrance_name ?? last.name}` : null,
      `${formatDistance(res.approach_m + res.distance_m)} · ${formatDuration(res.duration_s)}`,
    ],
  };
}

// A "no_route" /route response -> one message per reason.
// In wheelchair mode the backend only snaps to and routes over accessible edges, so say "accessible path":
// "nearest path" would be wrong when an ordinary path is right next to you.
// startName: a picked start's name; null for a map point or GPS ("your start").
export function describeNoRoute(res, destName, mode = "walk", startName = null) {
  const wheelchair = mode === "wheelchair";
  const from = startName ?? "your start";
  switch (res.reason) {
    case "too_far":
      if (res.distance_m === null) {
        return wheelchair ? "No accessible path on this campus from here." : "No usable path on this campus from here.";
      }
      return wheelchair
        ? `Your start is ${formatDistance(res.distance_m)} from the nearest accessible path.`
        : `Your start is ${formatDistance(res.distance_m)} from the nearest path. Choose a start closer to campus.`;
    case "no_entrances":
      return `${destName} has no mapped entrances yet.`;
    case "start_no_entrances":
      return `${startName ?? "Your start"} has no mapped entrances to leave by.`;
    case "no_path":
      return wheelchair
        ? `No accessible path connects ${from} to ${destName}.`
        : `No path connects ${from} to ${destName}.`;
    default:
      return `No route found (${res.reason}).`; // a reason this frontend doesn't know yet
  }
}

// --- flags: route segments not known to be wheelchair-accessible (only walking routes have them) ---

// edge_type is an open set; "steps" is the standard OSM value, sometimes joined with "+" ("steps+footway").
export function isSteps(flag) {
  return flag.edge_type !== null && flag.edge_type.split("+").includes("steps");
}

// Tooltip text for one flagged segment.
export function flagLabel(flag) {
  if (isSteps(flag)) return "Steps";
  return flag.accessible === false ? "Not wheelchair-accessible" : "Accessibility unknown";
}

// Consecutive segment indexes form one section: [[first, last], ...] in route order.
export function flagSections(flags) {
  const indexes = flags.map((f) => f.index).sort((a, b) => a - b);
  const sections = [];
  for (const i of indexes) {
    const last = sections[sections.length - 1];
    if (last && i === last[1] + 1) last[1] = i;
    else sections.push([i, i]);
  }
  return sections;
}

// The warning line for the result box, or null for a clean route.
export function describeFlags(flags) {
  if (flags.length === 0) return null;
  const n = flagSections(flags).length;
  if (flags.every(isSteps)) return n === 1 ? "Includes steps" : `Includes steps (${n} sections)`;
  return n === 1
    ? "Includes a section not known to be wheelchair-accessible"
    : `Includes ${n} sections not known to be wheelchair-accessible`;
}

// --- floors: a route's floors[i] / indoor[i] are parallel to coords[i] ---

// 0 is G, -1 is B1, 1 is 1. A floors.csv with real names is decided in step 6c.
export function floorLabel(n) {
  if (n === 0) return "G";
  return n < 0 ? `B${-n}` : String(n);
}

// One entry per segment i (coords[i] -> coords[i + 1]):
//   {kind: "outdoor"}                 both ends outdoors (always drawn), even if their floors differ (a hill door's connector)
//   {kind: "indoor", floor}           an indoor end, both ends on `floor` (includes door -> corridor)
//   {kind: "vertical", from, to}      an indoor end and different floors: stairs, elevator, an indoor ramp
export function classifySegments(res) {
  const segments = [];
  for (let i = 0; i + 1 < res.coords.length; i++) {
    const [fa, fb] = [res.floors[i], res.floors[i + 1]];
    if (!res.indoor[i] && !res.indoor[i + 1]) segments.push({ kind: "outdoor" });
    else if (fa === fb) segments.push({ kind: "indoor", floor: fa });
    else segments.push({ kind: "vertical", from: fa, to: fb });
  }
  return segments;
}

// Drawn at full strength with `floor` selected; otherwise faded.
export function segmentVisible(segment, floor) {
  if (segment.kind === "outdoor") return true;
  if (segment.kind === "indoor") return segment.floor === floor;
  return segment.from === floor || segment.to === floor;
}

// The route as polylines: consecutive segments with the same visibility merge into one run.
// [{coords: [[lat, lon], ...], visible}], in route order; a one-point route gives [].
export function routeRuns(res, floor) {
  const runs = [];
  classifySegments(res).forEach((seg, i) => {
    const visible = segmentVisible(seg, floor);
    const last = runs[runs.length - 1];
    if (last && last.visible === visible) last.coords.push(res.coords[i + 1]);
    else runs.push({ coords: [res.coords[i], res.coords[i + 1]], visible });
  });
  return runs;
}

// Floors the route visits indoors, top floor first (the switcher's order); [] for an outdoor route.
export function routeFloors(res) {
  const floors = new Set(res.floors.filter((_, i) => res.indoor[i]));
  return [...floors].sort((a, b) => b - a);
}

// The floor shown when a route arrives: where its indoor part starts (null if it has none).
export function defaultFloor(res) {
  const i = res.indoor.indexOf(true);
  return i < 0 ? null : res.floors[i];
}

// Where its indoor part ends (null if it has none): the destination building's floor in the floor view.
export function lastIndoorFloor(res) {
  const i = res.indoor.lastIndexOf(true);
  return i < 0 ? null : res.floors[i];
}

// The floor the route shows for one end's building: "start" -> its first indoor floor, "end" -> its last.
export function routeFloorFor(res, end) {
  return end === "end" ? lastIndoorFloor(res) : defaultFloor(res);
}

function verticalKind(change) {
  const tokens = change.edge_type === null ? [] : change.edge_type.split("+");
  return tokens.includes("elevator") ? "Elevator" : tokens.includes("steps") ? "Stairs" : null;
}

// Floor changes that are real vertical moves (stairs, elevator), with a label each. An upper-floor
// door's outdoor connector also changes floor but isn't one (see the step 4 notes in CLAUDE.md).
export function verticalMoves(res) {
  return res.floor_changes
    .filter((c) => verticalKind(c) !== null)
    .map((c) => ({
      ...c,
      label: `${verticalKind(c)} ${c.to_floor > c.from_floor ? "up" : "down"} to floor ${floorLabel(c.to_floor)}`,
    }));
}

// The badge for a move seen from `floor` (one of its two ends): where clicking it takes you.
// {text: "↑ 2", target: 2}, or null if the move doesn't touch `floor`.
export function moveBadge(move, floor) {
  if (floor !== move.from_floor && floor !== move.to_floor) return null;
  const target = floor === move.from_floor ? move.to_floor : move.from_floor;
  return { text: `${target > floor ? "↑" : "↓"} ${floorLabel(target)}`, target };
}

// The result box's floor line, or null for a route that never goes indoors.
export function describeFloors(res) {
  if (!res.indoor.includes(true)) return null;
  const parts = verticalMoves(res).map((m) => m.label);
  const last = res.coords.length - 1;
  if (res.indoor[last]) parts.push(`Ends on floor ${floorLabel(res.floors[last])}`);
  return parts.length > 0 ? parts.join(" · ") : null;
}

// --- floor view: the focused building's layout, plus the route's floors ---

// The switcher's floors: the focused building's and the route's, top floor first, no repeats.
export function switcherFloors(buildingFloors, routeFloorList) {
  return [...new Set([...buildingFloors, ...routeFloorList])].sort((a, b) => b - a);
}

// The floor shown when the view opens: the route's floor for this end ("start": its first indoor floor,
// "end": its last) if it has one, else the building's ground floor (its lowest floor at or above 0), else
// its top floor (a building that is all basement).
export function initialFloor(buildingFloors, route, end = "start") {
  const fromRoute = route ? routeFloorFor(route, end) : null;
  if (fromRoute !== null) return fromRoute;
  if (buildingFloors.length === 0) return null;
  const aboveGround = buildingFloors.filter((f) => f >= 0);
  return aboveGround.length > 0 ? Math.min(...aboveGround) : Math.max(...buildingFloors);
}

// How the floor view draws one layout point: "stairs" / "elevator" (a small badge), "place" (a dot you can
// route to: it has a POI), or null (not drawn: corridors, and doors, which already have their red dots).
export function layoutPointStyle(point) {
  if (point.type === "entrance") return null;
  if (point.type === "stairs" || point.type === "elevator") return point.type;
  return point.poi_id !== null ? "place" : null;
}

// The buildings the floor view can show: the start's and the destination's, if they have an indoor map
// (hasFloors(id)), start first, no repeats. Two entries -> the floor control offers a switch.
// The start's building counts only for a POI start (a room): a building or door start leaves from the
// door, so the route never goes inside it.
export function focusChoices(start, destination, hasFloors) {
  const startId = start?.kind === "poi" ? placeBuildingId(start) : null;
  const ids = [startId, placeBuildingId(destination)].filter((id) => id !== null && hasFloors(id));
  return [...new Set(ids)];
}

// --- search ---

// /search query params; with buildingId, the room search inside that building.
export function searchParams(q, limit, buildingId = null) {
  const params = new URLSearchParams({ q, limit });
  if (buildingId !== null) params.set("building", buildingId);
  return params;
}

// The grey line under a room-box result: the POI's own floor (a label; may be missing).
export function describeRoomResult(r) {
  return r.floor === null || r.floor === undefined ? "Place" : `Floor ${floorLabel(r.floor)}`;
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

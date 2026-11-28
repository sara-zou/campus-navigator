// Pure helpers for a route's request and its text: /route params, the result box, flags.
// No DOM, no Leaflet. Floor-related route helpers are in indoor.js.

import { formatDistance, formatDuration, placeBuildingId } from "./common.js";

// --- /route params (places: see common.js) ---

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

// --- the result box ---

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

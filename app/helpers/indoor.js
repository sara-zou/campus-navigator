// Pure helpers for anything about floors: a route's floors, the floor view, the room search, and
// whether a point is inside a building. No DOM, no Leaflet.

import { floorLabel, placeBuildingId } from "./common.js";

// --- floors: a route's floors[i] / indoor[i] are parallel to coords[i] ---

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

// The building whose plan the start end can show: a POI start's (a room). A building or door start leaves
// from the door, so the route never goes inside it; a point has none, unless the "you're inside" prompt's
// [Pick a room] offered its building (offeredId).
export function startFocusId(start, offeredId = null) {
  if (start?.kind === "poi") return placeBuildingId(start);
  return start?.kind === "point" ? offeredId : null;
}

// The buildings the floor view can show: the start end's (startFocusId) and the destination's, if they
// have an indoor map (hasFloors(id)), start first, no repeats. Two entries -> the floor control offers a switch.
export function focusChoices(startId, destination, hasFloors) {
  const ids = [startId, placeBuildingId(destination)].filter((id) => id !== null && hasFloors(id));
  return [...new Set(ids)];
}

// --- inside a building ---

// Ray casting: is (lon, lat) inside this ring of [lon, lat] points (closed or not)?
function inRing(lon, lat, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if (yi > lat !== yj > lat && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

// Is (lat, lon) inside a GeoJSON Polygon or MultiPolygon ([lon, lat] order)? A polygon's first ring is
// its outline and the rest are holes; a point in a hole is outside.
export function pointInGeometry(lat, lon, geometry) {
  const polygons = geometry.type === "Polygon" ? [geometry.coordinates]
    : geometry.type === "MultiPolygon" ? geometry.coordinates : [];
  return polygons.some(([outer, ...holes]) => inRing(lon, lat, outer) && !holes.some((h) => inRing(lon, lat, h)));
}

// The building with an indoor map that (lat, lon) falls inside, or null. Buildings without one get no
// "you're inside" prompt: there are no rooms to start from.
export function indoorBuildingAt(lat, lon, buildings) {
  return buildings.find((b) => b.floors.length > 0 && pointInGeometry(lat, lon, b.geometry)) ?? null;
}

// --- room search ---

// The grey line under a room-box result: the POI's own floor (a label; may be missing).
export function describeRoomResult(r) {
  return r.floor === null || r.floor === undefined ? "Place" : `Floor ${floorLabel(r.floor)}`;
}

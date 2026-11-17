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

// start: {lat, lon}; destination: {kind: "building" | "poi", id}.
export function routeParams(start, destination, mode) {
  const target = destination.kind === "building" ? "to_building" : "to_poi";
  return new URLSearchParams({ lat: start.lat, lon: start.lon, [target]: destination.id, mode });
}

// An "ok" /route response -> what the result box shows.
// The distance includes the approach, because duration_s does too; otherwise the two wouldn't match.
export function describeRoute(res) {
  return {
    title: res.entrance_name ?? "Entrance",
    detail: `${formatDistance(res.approach_m + res.distance_m)} · ${formatDuration(res.duration_s)}`,
  };
}

// A "no_route" /route response -> one message per reason.
// In wheelchair mode the backend only snaps to and routes over accessible edges, so say "accessible path":
// "nearest path" would be wrong when an ordinary path is right next to you.
export function describeNoRoute(res, destName, mode = "walk") {
  const wheelchair = mode === "wheelchair";
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
    case "no_path":
      return wheelchair
        ? `No accessible path connects your start to ${destName}.`
        : `No path connects your start to ${destName}.`;
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

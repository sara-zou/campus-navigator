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

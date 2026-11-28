// The backend's endpoints. Campus-scoped calls use state.campusId. `signal` is an optional AbortSignal:
// aborting rejects with an AbortError, which callers ignore (a newer request replaced this one).

import { state } from "./state.js";

async function getJSON(url, signal) {
  const res = await fetch(url, { signal });
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
  return res.json();
}

function campusUrl(path) {
  return `/campuses/${encodeURIComponent(state.campusId)}${path}`;
}

export function campuses() {
  return getJSON("/campuses");
}

export function buildings(signal) {
  return getJSON(campusUrl("/buildings"), signal);
}

export function indoor(buildingId, signal) {
  return getJSON(campusUrl(`/buildings/${encodeURIComponent(buildingId)}/indoor`), signal);
}

// params: URLSearchParams from searchParams() / routeParams() in helpers/.
export function search(params, signal) {
  return getJSON(campusUrl(`/search?${params}`), signal);
}

export function route(params, signal) {
  return getJSON(campusUrl(`/route?${params}`), signal);
}

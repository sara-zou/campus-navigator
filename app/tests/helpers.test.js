import assert from "node:assert/strict";
import { test } from "node:test";

import { describeNoRoute, describeRoute, formatDistance, formatDuration, routeParams } from "../helpers.js";

test("formatDistance rounds meters to 10", () => {
  assert.equal(formatDistance(0), "0 m");
  assert.equal(formatDistance(4), "0 m");
  assert.equal(formatDistance(354), "350 m");
  assert.equal(formatDistance(355), "360 m");
});

test("formatDistance switches to km once the rounded value reaches 1000", () => {
  assert.equal(formatDistance(994), "990 m");
  assert.equal(formatDistance(995), "1.0 km"); // never "1000 m"
  assert.equal(formatDistance(1249), "1.2 km");
});

test("formatDuration is at least 1 min", () => {
  assert.equal(formatDuration(0), "1 min");
  assert.equal(formatDuration(20), "1 min");
});

test("formatDuration rounds to minutes", () => {
  assert.equal(formatDuration(89), "1 min");
  assert.equal(formatDuration(90), "2 min");
  assert.equal(formatDuration(59 * 60 + 29), "59 min");
});

test("formatDuration shows hours", () => {
  assert.equal(formatDuration(59 * 60 + 30), "1 h");
  assert.equal(formatDuration(65 * 60), "1 h 5 min");
});

test("routeParams sends to_building for a building", () => {
  const p = routeParams({ lat: 42.3, lon: -71.1 }, { kind: "building", id: "snl" }, "walk");
  assert.equal(p.toString(), "lat=42.3&lon=-71.1&to_building=snl&mode=walk");
});

test("routeParams sends to_poi for a POI, and escapes ids", () => {
  const p = routeParams({ lat: 1, lon: 2 }, { kind: "poi", id: "a b&c" }, "wheelchair");
  assert.equal(p.get("to_poi"), "a b&c");
  assert.equal(p.has("to_building"), false);
  assert.equal(p.toString(), "lat=1&lon=2&to_poi=a+b%26c&mode=wheelchair");
});

test("describeRoute adds the approach to the distance", () => {
  const res = { entrance_name: "Main door", distance_m: 400, approach_m: 20, duration_s: 300 };
  assert.deepEqual(describeRoute(res), { title: "Main door", detail: "420 m · 5 min" });
});

test("describeRoute falls back when the entrance has no name", () => {
  const res = { entrance_name: null, distance_m: 0, approach_m: 0, duration_s: 0 };
  assert.equal(describeRoute(res).title, "Entrance");
});

test("describeNoRoute too_far with a distance", () => {
  assert.equal(
    describeNoRoute({ reason: "too_far", distance_m: 352.4 }, "Snell"),
    "Your start is 350 m from the nearest path. Choose a start closer to campus.",
  );
});

test("describeNoRoute too_far with no usable edge", () => {
  assert.equal(describeNoRoute({ reason: "too_far", distance_m: null }, "Snell"),
    "No usable path on this campus from here.");
});

test("describeNoRoute no_entrances and no_path name the destination", () => {
  assert.equal(describeNoRoute({ reason: "no_entrances", distance_m: null }, "Ell Hall"),
    "Ell Hall has no mapped entrances yet.");
  assert.equal(describeNoRoute({ reason: "no_path", distance_m: null }, "Ell Hall"),
    "No path connects your start to Ell Hall.");
});

test("describeNoRoute unknown reason", () => {
  assert.equal(describeNoRoute({ reason: "closed", distance_m: null }, "X"), "No route found (closed).");
});

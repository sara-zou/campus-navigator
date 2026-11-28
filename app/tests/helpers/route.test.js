import assert from "node:assert/strict";
import { test } from "node:test";

import { describeFlags, describeNoRoute, describeRoute, flagLabel, flagSections, isSteps, routeParams } from "../../helpers/route.js";

test("routeParams sends to_building for a building", () => {
  const p = routeParams({ kind: "point", lat: 42.3, lon: -71.1 }, { kind: "building", id: "snl" }, "walk");
  assert.equal(p.toString(), "lat=42.3&lon=-71.1&to_building=snl&mode=walk");
});

test("routeParams sends to_entrance (a node_id) for an entrance", () => {
  const p = routeParams({ kind: "point", lat: 1, lon: 2 }, { kind: "entrance", id: "entrance_7" }, "walk");
  assert.equal(p.toString(), "lat=1&lon=2&to_entrance=entrance_7&mode=walk");
});

test("routeParams throws on an unknown kind", () => {
  assert.throws(() => routeParams({ kind: "point", lat: 1, lon: 2 }, { kind: "room", id: "x" }, "walk"), /unknown destination kind/);
});

test("routeParams sends from_building / from_poi / from_entrance for a picked start, no lat/lon", () => {
  const to = { kind: "building", id: "lib" };
  assert.equal(routeParams({ kind: "building", id: "hall" }, to, "walk").toString(),
    "from_building=hall&to_building=lib&mode=walk");
  assert.equal(routeParams({ kind: "poi", id: "poi-r1" }, to, "walk").toString(), "from_poi=poi-r1&to_building=lib&mode=walk");
  assert.equal(routeParams({ kind: "entrance", id: "e1" }, to, "walk").toString(), "from_entrance=e1&to_building=lib&mode=walk");
});

test("routeParams throws on a point destination and an unknown start kind", () => {
  const point = { kind: "point", lat: 1, lon: 2 };
  assert.throws(() => routeParams(point, point, "walk"), /unknown destination kind "point"/);
  assert.throws(() => routeParams({ kind: "room", id: "x" }, { kind: "poi", id: "y" }, "walk"), /unknown start kind/);
});

test("routeParams sends to_poi for a POI, and escapes ids", () => {
  const p = routeParams({ kind: "point", lat: 1, lon: 2 }, { kind: "poi", id: "a b&c" }, "wheelchair");
  assert.equal(p.get("to_poi"), "a b&c");
  assert.equal(p.has("to_building"), false);
  assert.equal(p.toString(), "lat=1&lon=2&to_poi=a+b%26c&mode=wheelchair");
});

// Doors for describeRoute: hall-s / hall-e (Main Hall), lib-w (Library, unnamed POI).
const DOORS = {
  "hall-s": { name: "Main Hall (South Entrance)", building_id: "hall" },
  "lib-w": { name: "Entrance of Library", building_id: "lib" },
};
const door = (id) => DOORS[id] ?? null;
const POINT = { kind: "point", lat: 1, lon: 2, name: "Point on map" };
const HALL = { kind: "building", id: "hall", name: "Main Hall" };
const ROUTE = {
  start_id: null, entrance_id: "hall-s", entrance_name: "Main Hall (South Entrance)", building_id: "hall",
  distance_m: 400, approach_m: 20, duration_s: 300,
};

test("describeRoute: destination name as title, the entry door, approach in the distance", () => {
  assert.deepEqual(describeRoute(ROUTE, POINT, HALL, door), {
    title: "Main Hall", details: [null, "Enter by Main Hall (South Entrance)", "420 m · 5 min"],
  });
  const room = { kind: "poi", id: "poi-g06", name: "Room G06", building_id: "hall" };
  assert.equal(describeRoute(ROUTE, POINT, room, door).title, "Room G06");
  assert.equal(describeRoute(ROUTE, POINT, room, door).details[1], "Enter by Main Hall (South Entrance)");
});

test("describeRoute: no Enter by for a door destination", () => {
  const d = { kind: "entrance", id: "hall-s", name: "Main Hall (South Entrance)", building_id: "hall" };
  assert.equal(describeRoute(ROUTE, POINT, d, door).details[1], null);
});

test("describeRoute: the last door isn't an entry when the route ends outside its building", () => {
  // room in Main Hall -> bus stop: the last door on the path is the one you leave by
  const res = { ...ROUTE, building_id: null };
  const from = { kind: "poi", id: "poi-g06", name: "Room G06", building_id: "hall" };
  const bus = { kind: "poi", id: "poi-bus", name: "Bus Stop", building_id: null };
  assert.deepEqual(describeRoute(res, from, bus, door).details.slice(0, 2), [null, null]);
});

test("describeRoute: no Enter by when the start is already in the end building", () => {
  const from = { kind: "poi", id: "poi-g06", name: "Room G06", building_id: "hall" };
  const to = { kind: "poi", id: "poi-101", name: "Room 101", building_id: "hall" };
  assert.equal(describeRoute(ROUTE, from, to, door).details[1], null);
});

test("describeRoute: a building start says which door it leaves by", () => {
  const res = { ...ROUTE, start_id: "lib-w" };
  const lib = { kind: "building", id: "lib", name: "Library" };
  assert.deepEqual(describeRoute(res, lib, HALL, door).details.slice(0, 2),
    ["Leave by Entrance of Library", "Enter by Main Hall (South Entrance)"]);
  assert.equal(describeRoute({ ...res, start_id: "gone" }, lib, HALL, door).details[0], "Leave by an entrance");
});

test("describeRoute: an unnamed entry door uses the door lookup's name", () => {
  const res = { ...ROUTE, entrance_id: "lib-w", entrance_name: null, building_id: "lib" };
  assert.equal(describeRoute(res, POINT, { kind: "building", id: "lib", name: "Library" }, door).details[1],
    "Enter by Entrance of Library");
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

test("describeNoRoute names a picked start", () => {
  assert.equal(describeNoRoute({ reason: "no_path", distance_m: null }, "Library", "walk", "Room G06"),
    "No path connects Room G06 to Library.");
  assert.equal(describeNoRoute({ reason: "no_path", distance_m: null }, "Library", "wheelchair", "Room G06"),
    "No accessible path connects Room G06 to Library.");
  assert.equal(describeNoRoute({ reason: "start_no_entrances", distance_m: null }, "Library", "walk", "Shed"),
    "Shed has no mapped entrances to leave by.");
});

test("describeNoRoute unknown reason", () => {
  assert.equal(describeNoRoute({ reason: "closed", distance_m: null }, "X"), "No route found (closed).");
});

test("describeNoRoute defaults to walk messages", () => {
  assert.equal(describeNoRoute({ reason: "no_path", distance_m: null }, "X"),
    describeNoRoute({ reason: "no_path", distance_m: null }, "X", "walk"));
});

test("describeNoRoute wheelchair too_far says accessible path", () => {
  assert.equal(describeNoRoute({ reason: "too_far", distance_m: 352.4 }, "Snell", "wheelchair"),
    "Your start is 350 m from the nearest accessible path.");
  assert.equal(describeNoRoute({ reason: "too_far", distance_m: null }, "Snell", "wheelchair"),
    "No accessible path on this campus from here.");
});

test("describeNoRoute wheelchair no_path says accessible path", () => {
  assert.equal(describeNoRoute({ reason: "no_path", distance_m: null }, "Ell Hall", "wheelchair"),
    "No accessible path connects your start to Ell Hall.");
});

test("describeNoRoute no_entrances is the same in every mode", () => {
  assert.equal(describeNoRoute({ reason: "no_entrances", distance_m: null }, "Ell Hall", "wheelchair"),
    "Ell Hall has no mapped entrances yet.");
});

const steps = (index) => ({ index, accessible: false, edge_type: "steps" });
const slope = (index) => ({ index, accessible: false, edge_type: "footway" });
const unknown = (index) => ({ index, accessible: null, edge_type: null });

test("isSteps reads OSM steps, including joined types", () => {
  assert.equal(isSteps(steps(0)), true);
  assert.equal(isSteps({ index: 0, accessible: false, edge_type: "steps+footway" }), true);
  assert.equal(isSteps({ index: 0, accessible: false, edge_type: "footsteps" }), false); // whole token only
  assert.equal(isSteps(unknown(0)), false);
});

test("flagLabel per kind", () => {
  assert.equal(flagLabel(steps(0)), "Steps");
  assert.equal(flagLabel(slope(0)), "Not wheelchair-accessible");
  assert.equal(flagLabel(unknown(0)), "Accessibility unknown");
});

test("flagSections groups consecutive indexes", () => {
  assert.deepEqual(flagSections([]), []);
  assert.deepEqual(flagSections([steps(3)]), [[3, 3]]);
  assert.deepEqual(flagSections([steps(3), steps(4)]), [[3, 4]]);
  assert.deepEqual(flagSections([steps(1), steps(4), steps(5)]), [[1, 1], [4, 5]]);
});

test("describeFlags is null for a clean route", () => {
  assert.equal(describeFlags([]), null);
});

test("describeFlags counts steps sections", () => {
  assert.equal(describeFlags([steps(2)]), "Includes steps");
  assert.equal(describeFlags([steps(2), steps(3)]), "Includes steps"); // consecutive = one section
  assert.equal(describeFlags([steps(0), steps(4)]), "Includes steps (2 sections)");
});

test("describeFlags uses generic wording unless every flag is steps", () => {
  assert.equal(describeFlags([steps(0), slope(3)]), "Includes 2 sections not known to be wheelchair-accessible");
  assert.equal(describeFlags([unknown(1)]), "Includes a section not known to be wheelchair-accessible");
});

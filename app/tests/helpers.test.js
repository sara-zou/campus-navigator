import assert from "node:assert/strict";
import { test } from "node:test";

import {
  campusLabel, campusUrl, doorDetails, focusChoices, lastIndoorFloor, placeBuildingId, routeFloorFor, chooseCampus, describeRoomResult, searchParams, classifySegments, defaultFloor, describeFloors, floorLabel, initialFloor,
  layoutPointStyle, moveBadge, switcherFloors,
  routeFloors, routeRuns, segmentVisible, verticalMoves, describeFlags, describeNoRoute, describeRoute, flagLabel, flagSections, formatDistance, formatDuration, isSteps,
  routeParams,
} from "../helpers.js";

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

test("placeBuildingId", () => {
  assert.equal(placeBuildingId(HALL), "hall");
  assert.equal(placeBuildingId({ kind: "poi", id: "p", building_id: "lib" }), "lib");
  assert.equal(placeBuildingId({ kind: "poi", id: "p", building_id: null }), null);
  assert.equal(placeBuildingId(POINT), null);
  assert.equal(placeBuildingId(null), null);
});

test("focusChoices: start first, only buildings with floors, no repeats", () => {
  const hasFloors = (id) => id === "hall" || id === "lib";
  const lib = { kind: "building", id: "lib", name: "Library" };
  const cafe = { kind: "building", id: "cafe", name: "Cafe" };
  const libRoom = { kind: "poi", id: "p1", name: "Room 101", building_id: "lib" };
  const cafeRoom = { kind: "poi", id: "p2", name: "Counter", building_id: "cafe" };
  assert.deepEqual(focusChoices(libRoom, HALL, hasFloors), ["lib", "hall"]);
  assert.deepEqual(focusChoices(POINT, HALL, hasFloors), ["hall"]);
  assert.deepEqual(focusChoices(cafeRoom, HALL, hasFloors), ["hall"]);
  assert.deepEqual(focusChoices(libRoom, { kind: "poi", id: "p", building_id: "lib" }, hasFloors), ["lib"]);
  assert.deepEqual(focusChoices(libRoom, null, hasFloors), ["lib"]);
  // a building or door start leaves from outside: its plan isn't offered
  assert.deepEqual(focusChoices(lib, HALL, hasFloors), ["hall"]);
  assert.deepEqual(focusChoices({ kind: "entrance", id: "e", building_id: "lib" }, null, hasFloors), []);
  assert.deepEqual(focusChoices(null, null, hasFloors), []);
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

const CAMPUSES = [
  { id: "demo-university", name: "Demo University", bounds: null },
  { id: "northeastern-boston", name: "Northeastern University", bounds: null },
];

test("chooseCampus picks the requested campus, else the first", () => {
  assert.equal(chooseCampus(CAMPUSES, "northeastern-boston").id, "northeastern-boston");
  assert.equal(chooseCampus(CAMPUSES, null).id, "demo-university");
  assert.equal(chooseCampus(CAMPUSES, "nope").id, "demo-university");
  assert.equal(chooseCampus(CAMPUSES, "Northeastern-Boston").id, "demo-university"); // ids are case-sensitive
  assert.equal(chooseCampus([], "x"), null);
});

test("campusLabel uses the name, falling back to the id", () => {
  assert.equal(campusLabel(CAMPUSES[0]), "Demo University");
  assert.equal(campusLabel({ id: "tiny", name: "" }), "tiny");
  assert.equal(campusLabel({ id: "tiny" }), "tiny");
});

test("campusUrl sets ?campus= and keeps the rest of the URL", () => {
  assert.equal(campusUrl("http://localhost:8000/", "demo-university"), "http://localhost:8000/?campus=demo-university");
  assert.equal(campusUrl("http://localhost:8000/?campus=old&x=1#map", "new"), "http://localhost:8000/?campus=new&x=1#map");
});

// The tiny-indoor route from south of hq to Room 101, as /route returns it (see CLAUDE.md, step 5 example).
const INDOOR_ROUTE = {
  coords: [[0, 0], [1, 0], [2, 0], [3, 0], [3, 0], [4, 0], [5, 0]],
  floors: [0, 0, 0, 0, 1, 1, 1],
  indoor: [false, false, true, true, true, true, true],
  floor_changes: [{ index: 3, from_floor: 0, to_floor: 1, edge_type: "steps" }],
};
const OUTDOOR_ROUTE = { coords: [[0, 0], [1, 0]], floors: [0, 0], indoor: [false, false], floor_changes: [] };

test("floorLabel", () => {
  assert.equal(floorLabel(0), "G");
  assert.equal(floorLabel(-1), "B1");
  assert.equal(floorLabel(-2), "B2");
  assert.equal(floorLabel(3), "3");
});

test("classifySegments: outdoor, door edge counts as indoor, stairs are vertical", () => {
  assert.deepEqual(classifySegments(INDOOR_ROUTE), [
    { kind: "outdoor" },
    { kind: "indoor", floor: 0 },   // door (outdoor) -> corridor (indoor)
    { kind: "indoor", floor: 0 },
    { kind: "vertical", from: 0, to: 1 },
    { kind: "indoor", floor: 1 },
    { kind: "indoor", floor: 1 },
  ]);
});

test("classifySegments: an upper-floor door's outdoor connector is outdoor, not vertical", () => {
  const hill = { coords: [[0, 0], [1, 0]], floors: [0, 1], indoor: [false, false] };
  assert.deepEqual(classifySegments(hill), [{ kind: "outdoor" }]);
});

test("segmentVisible", () => {
  assert.equal(segmentVisible({ kind: "outdoor" }, 5), true);
  assert.equal(segmentVisible({ kind: "indoor", floor: 1 }, 1), true);
  assert.equal(segmentVisible({ kind: "indoor", floor: 1 }, 0), false);
  assert.equal(segmentVisible({ kind: "vertical", from: 0, to: 2 }, 2), true);
  assert.equal(segmentVisible({ kind: "vertical", from: 0, to: 2 }, 1), false);
});

test("routeRuns merges segments by visibility", () => {
  assert.deepEqual(routeRuns(INDOOR_ROUTE, 0), [
    { coords: [[0, 0], [1, 0], [2, 0], [3, 0], [3, 0]], visible: true },   // outdoor + floor 0 + the stairs
    { coords: [[3, 0], [4, 0], [5, 0]], visible: false },
  ]);
  assert.deepEqual(routeRuns(INDOOR_ROUTE, 1), [
    { coords: [[0, 0], [1, 0]], visible: true },
    { coords: [[1, 0], [2, 0], [3, 0]], visible: false },
    { coords: [[3, 0], [3, 0], [4, 0], [5, 0]], visible: true },
  ]);
  assert.deepEqual(routeRuns(OUTDOOR_ROUTE, null), [{ coords: [[0, 0], [1, 0]], visible: true }]);
  assert.deepEqual(routeRuns({ coords: [[0, 0]], floors: [1], indoor: [true] }, 1), []);
});

test("routeFloors and defaultFloor", () => {
  assert.deepEqual(routeFloors(INDOOR_ROUTE), [1, 0]);
  assert.equal(defaultFloor(INDOOR_ROUTE), 0);
  assert.deepEqual(routeFloors(OUTDOOR_ROUTE), []);
  assert.equal(defaultFloor(OUTDOOR_ROUTE), null);
  const fromRoom = { ...INDOOR_ROUTE, floors: [2, 2, 1], indoor: [true, true, true] };
  assert.equal(defaultFloor(fromRoom), 2);
});

test("verticalMoves keeps stairs and elevators, drops connectors", () => {
  const res = {
    floor_changes: [
      { index: 0, from_floor: 0, to_floor: 1, edge_type: "connector" },
      { index: 3, from_floor: 1, to_floor: -1, edge_type: "elevator" },
      { index: 5, from_floor: -1, to_floor: 0, edge_type: "steps+footway" },
      { index: 6, from_floor: 0, to_floor: 1, edge_type: null },
    ],
  };
  assert.deepEqual(verticalMoves(res).map((m) => [m.index, m.label]), [
    [3, "Elevator down to floor B1"],
    [5, "Stairs up to floor G"],
  ]);
});

test("moveBadge points to the other end of the move", () => {
  const move = { from_floor: 0, to_floor: 2 };
  assert.deepEqual(moveBadge(move, 0), { text: "↑ 2", target: 2 });
  assert.deepEqual(moveBadge(move, 2), { text: "↓ G", target: 0 });
  assert.equal(moveBadge(move, 1), null);
});

test("describeFloors", () => {
  assert.equal(describeFloors(INDOOR_ROUTE), "Stairs up to floor 1 · Ends on floor 1");
  assert.equal(describeFloors(OUTDOOR_ROUTE), null);
  const exitRoute = { ...INDOOR_ROUTE, indoor: [true, true, false], floors: [0, 0, 0], coords: [[0, 0], [1, 0], [2, 0]],
                      floor_changes: [] };
  assert.equal(describeFloors(exitRoute), null);   // indoors, but no move and ends outside
});

test("switcherFloors merges the building's and the route's floors, top first", () => {
  assert.deepEqual(switcherFloors([-1, 0, 1], [1, 2]), [2, 1, 0, -1]);
  assert.deepEqual(switcherFloors([], [1, 0]), [1, 0]);
  assert.deepEqual(switcherFloors([0, 1], []), [1, 0]);
  assert.deepEqual(switcherFloors([], []), []);
});

test("lastIndoorFloor and routeFloorFor", () => {
  assert.equal(lastIndoorFloor(INDOOR_ROUTE), 1);
  assert.equal(lastIndoorFloor(OUTDOOR_ROUTE), null);
  const outAgain = { ...INDOOR_ROUTE, indoor: [false, true, true, false, false, false, false] };
  assert.equal(lastIndoorFloor(outAgain), 0);
  assert.equal(routeFloorFor(INDOOR_ROUTE, "start"), 0);
  assert.equal(routeFloorFor(INDOOR_ROUTE, "end"), 1);
});

test("initialFloor for the destination's building uses the route's last indoor floor", () => {
  assert.equal(initialFloor([0, 1], INDOOR_ROUTE, "end"), 1);
  assert.equal(initialFloor([0, 1], OUTDOOR_ROUTE, "end"), 0);
});

test("initialFloor prefers the route's first indoor floor, else the building's ground floor", () => {
  assert.equal(initialFloor([-1, 0, 1, 2], INDOOR_ROUTE), 0);
  assert.equal(initialFloor([-1, 0, 1, 2], null), 0);
  assert.equal(initialFloor([1, 2, 3], null), 1);         // no floor 0: lowest above ground
  assert.equal(initialFloor([-2, -1], null), -1);         // all basement: the top one
  assert.equal(initialFloor([0, 1], OUTDOOR_ROUTE), 0);   // an outdoor route doesn't pick a floor
  assert.equal(initialFloor([], null), null);
});

test("layoutPointStyle", () => {
  const pt = (type, poi_id = null) => ({ type, poi_id });
  assert.equal(layoutPointStyle(pt("room", "poi-r1")), "place");
  assert.equal(layoutPointStyle(pt("room")), null);                // no POI: nothing to route to
  assert.equal(layoutPointStyle(pt("stairs")), "stairs");
  assert.equal(layoutPointStyle(pt("elevator", "poi-lift")), "elevator");
  assert.equal(layoutPointStyle(pt("corridor")), null);
  assert.equal(layoutPointStyle(pt("entrance", "poi-door")), null); // drawn as a red door dot already
  assert.equal(layoutPointStyle(pt("restroom", "poi-wc")), "place"); // type is an open set
});

test("searchParams: outdoor and in-building", () => {
  assert.equal(searchParams("room 1", 10).toString(), "q=room+1&limit=10");
  assert.equal(searchParams("room 1", 10, "hall").toString(), "q=room+1&limit=10&building=hall");
});

test("describeRoomResult shows the POI's floor", () => {
  assert.equal(describeRoomResult({ floor: 1 }), "Floor 1");
  assert.equal(describeRoomResult({ floor: 0 }), "Floor G");
  assert.equal(describeRoomResult({ floor: -1 }), "Floor B1");
  assert.equal(describeRoomResult({ floor: null }), "Place");
});

test("doorDetails: accessibility, floor off the ground, wheelchair warning", () => {
  assert.deepEqual(doorDetails({ accessible: true, floor: 0 }, "walk"),
    { floor: null, access: "Wheelchair accessible", warning: null });
  assert.deepEqual(doorDetails({ accessible: false, floor: 1 }, "walk"),
    { floor: "Floor 1", access: "Not wheelchair accessible", warning: null });
  assert.equal(doorDetails({ accessible: null, floor: -1 }, "walk").floor, "Floor B1");
  assert.equal(doorDetails({ accessible: null, floor: 0 }, "walk").access, "Accessibility unknown");
});

test("doorDetails warns in wheelchair mode for a door not known accessible", () => {
  assert.equal(doorDetails({ accessible: false, floor: 0 }, "wheelchair").warning, "Wheelchair routes can't use this door");
  assert.equal(doorDetails({ accessible: null, floor: 0 }, "wheelchair").warning, "Wheelchair routes can't use this door");
  assert.equal(doorDetails({ accessible: true, floor: 0 }, "wheelchair").warning, null);
});

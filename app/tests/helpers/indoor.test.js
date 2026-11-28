import assert from "node:assert/strict";
import { test } from "node:test";

import { classifySegments, defaultFloor, describeFloors, describeRoomResult, focusChoices, indoorBuildingAt, initialFloor, lastIndoorFloor, layoutPointStyle, moveBadge, pointInGeometry, routeFloorFor, routeFloors, routeRuns, segmentVisible, startFocusId, switcherFloors, verticalMoves } from "../../helpers/indoor.js";

const POINT = { kind: "point", lat: 1, lon: 2, name: "Point on map" };
const HALL = { kind: "building", id: "hall", name: "Main Hall" };

// The tiny-indoor route from south of hq to Room 101, as /route returns it (see CLAUDE.md, step 5 example).
const INDOOR_ROUTE = {
  coords: [[0, 0], [1, 0], [2, 0], [3, 0], [3, 0], [4, 0], [5, 0]],
  floors: [0, 0, 0, 0, 1, 1, 1],
  indoor: [false, false, true, true, true, true, true],
  floor_changes: [{ index: 3, from_floor: 0, to_floor: 1, edge_type: "steps" }],
};
const OUTDOOR_ROUTE = { coords: [[0, 0], [1, 0]], floors: [0, 0], indoor: [false, false], floor_changes: [] };

test("startFocusId: a room's building, an offered building for a point, else null", () => {
  assert.equal(startFocusId({ kind: "poi", id: "p1", building_id: "lib" }), "lib");
  assert.equal(startFocusId({ kind: "building", id: "lib", name: "Library" }), null);  // leaves from the door
  assert.equal(startFocusId({ kind: "entrance", id: "e", building_id: "lib" }, "lib"), null);
  assert.equal(startFocusId(POINT), null);
  assert.equal(startFocusId(POINT, "hall"), "hall");                                     // [Pick a room]
  assert.equal(startFocusId(null, "hall"), null);
});

test("focusChoices: start first, only buildings with floors, no repeats", () => {
  const hasFloors = (id) => id === "hall" || id === "lib";
  assert.deepEqual(focusChoices("lib", HALL, hasFloors), ["lib", "hall"]);
  assert.deepEqual(focusChoices(null, HALL, hasFloors), ["hall"]);
  assert.deepEqual(focusChoices("cafe", HALL, hasFloors), ["hall"]);
  assert.deepEqual(focusChoices("lib", { kind: "poi", id: "p", building_id: "lib" }, hasFloors), ["lib"]);
  assert.deepEqual(focusChoices("lib", null, hasFloors), ["lib"]);
  assert.deepEqual(focusChoices(null, null, hasFloors), []);
});

// A 10 x 10 square (lon 0..10, lat 0..10) with a 2 x 2 hole at 4..6, and a second part at lon 20..22.
const SQUARE = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]];
const HOLE = [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]];
const FAR = [[20, 0], [22, 0], [22, 2], [20, 2], [20, 0]];

test("pointInGeometry: Polygon (lat, lon in; [lon, lat] rings)", () => {
  const poly = { type: "Polygon", coordinates: [SQUARE] };
  assert.equal(pointInGeometry(2, 8, poly), true);
  assert.equal(pointInGeometry(8, 12, poly), false);    // lon 12 is outside
  assert.equal(pointInGeometry(12, 8, poly), false);    // lat 12 is outside
});

test("pointInGeometry: a hole is outside", () => {
  const poly = { type: "Polygon", coordinates: [SQUARE, HOLE] };
  assert.equal(pointInGeometry(5, 5, poly), false);
  assert.equal(pointInGeometry(2, 2, poly), true);
});

test("pointInGeometry: MultiPolygon, any part; other types never contain", () => {
  const multi = { type: "MultiPolygon", coordinates: [[SQUARE], [FAR]] };
  assert.equal(pointInGeometry(1, 21, multi), true);
  assert.equal(pointInGeometry(1, 15, multi), false);
  assert.equal(pointInGeometry(1, 1, { type: "Point", coordinates: [1, 1] }), false);
});

test("indoorBuildingAt: only buildings with an indoor map", () => {
  const plain = { id: "cafe", floors: [], geometry: { type: "Polygon", coordinates: [SQUARE] } };
  const indoor = { id: "hall", floors: [0, 1], geometry: { type: "Polygon", coordinates: [SQUARE] } };
  assert.equal(indoorBuildingAt(2, 2, [plain]), null);
  assert.equal(indoorBuildingAt(2, 2, [plain, indoor]).id, "hall");
  assert.equal(indoorBuildingAt(50, 50, [indoor]), null);
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

test("describeRoomResult shows the POI's floor", () => {
  assert.equal(describeRoomResult({ floor: 1 }), "Floor 1");
  assert.equal(describeRoomResult({ floor: 0 }), "Floor G");
  assert.equal(describeRoomResult({ floor: -1 }), "Floor B1");
  assert.equal(describeRoomResult({ floor: null }), "Place");
});

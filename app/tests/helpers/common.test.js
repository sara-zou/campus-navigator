import assert from "node:assert/strict";
import { test } from "node:test";

import { campusLabel, campusUrl, chooseCampus, doorDetails, floorLabel, formatDistance, formatDuration, placeBuildingId, searchParams } from "../../helpers/common.js";

const POINT = { kind: "point", lat: 1, lon: 2, name: "Point on map" };
const HALL = { kind: "building", id: "hall", name: "Main Hall" };

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

test("placeBuildingId", () => {
  assert.equal(placeBuildingId(HALL), "hall");
  assert.equal(placeBuildingId({ kind: "poi", id: "p", building_id: "lib" }), "lib");
  assert.equal(placeBuildingId({ kind: "poi", id: "p", building_id: null }), null);
  assert.equal(placeBuildingId(POINT), null);
  assert.equal(placeBuildingId(null), null);
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

test("floorLabel", () => {
  assert.equal(floorLabel(0), "G");
  assert.equal(floorLabel(-1), "B1");
  assert.equal(floorLabel(-2), "B2");
  assert.equal(floorLabel(3), "3");
});

test("searchParams: outdoor and in-building", () => {
  assert.equal(searchParams("room 1", 10).toString(), "q=room+1&limit=10");
  assert.equal(searchParams("room 1", 10, "hall").toString(), "q=room+1&limit=10&building=hall");
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

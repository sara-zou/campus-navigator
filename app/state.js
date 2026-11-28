// The app's shared state: what the user picked and what the page is showing. Data only, no functions.
// Any module may read it. Writers: floor-view.js for viewedFloor, focusId, focusLayout, focusChoiceIds;
// controller.js for everything else. map-layers.js, panel.js and search.js never write it.

export const state = {
  // campus
  campusId: null,      // set by loadCampus(); every campus-scoped URL uses it (see api.js)
  campusBounds: null,  // L.LatLngBounds, set by loadCampus() when the campus has bounds
  buildings: new Map(), // id -> building from /buildings
  doors: new Map(),     // entrance node_id -> {name, building_id}, for the result box's door lines

  // the two ends and the mode
  mode: "walk",        // a backend MODES key, from the radios (see loadMode in main.js)
  start: null,         // a place (see helpers/common.js), or null
  destination: null,   // a place (kind "building" | "poi" | "entrance"), or null
  offeredId: null,     // the "you're inside" building once [Pick a room] was pressed, until the start changes

  // route and floors
  route: null,         // the "ok" /route response being shown, or null
  viewedFloor: null,   // the floor drawn at full strength (route and layout); null when no floors are in view
  focusId: null,       // building whose floor view is open (one of focusChoiceIds), or null
  focusLayout: null,   // its /indoor response once loaded
  focusChoiceIds: [],  // focusChoices() for the current ends: the buildings the floor view can show
};

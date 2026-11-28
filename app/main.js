// Entry point: wires the modules together. Leaflet is loaded as a global `L` by index.html.
//   controller.js  both ends, the route, the mode, the campus (writes state)
//   floor-view.js  floor buttons, building switch, floor plans (writes the floor-view state)
//   map-layers.js, panel.js, search.js  read state and report user actions through these callbacks
// Imports only go one way: main -> controller -> floor-view -> map-layers / panel / search -> state / api / helpers.

import {
  closeSearchLists, initController, offerRoomsIn, openFirstCampus, pickCampus, setMode, setPlace, swapEnds,
} from "./controller.js";
import { initFloorView, setViewedFloor } from "./floor-view.js";
import { initMapLayers, map } from "./map-layers.js";
import { initPanel, showStatus } from "./panel.js";

initController(); // first: the panel's mode radios read state.mode
initMapLayers({ onPick: setPlace, onFloor: setViewedFloor });
initFloorView({ onPick: setPlace });
initPanel({ onMode: setMode, onSwap: swapEnds, onPickRoom: offerRoomsIn, onCampus: pickCampus });

// Clicks on buildings bubble up to the map, so they set the start too. Entrance dots don't (they open
// their popup instead). A map click also closes the search lists: the user has moved on from typing.
map.on("click", (e) => {
  closeSearchLists();
  setPlace("from", { kind: "point", lat: e.latlng.lat, lon: e.latlng.lng, name: "Point on map" });
});

openFirstCampus().catch((err) => {
  map.setView([0, 0], 2);
  showStatus(`Could not load campus data: ${err.message}`);
  console.error(err);
});

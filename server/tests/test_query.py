import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import INDOOR_FIXTURE
from loader import POI, Building, load_campus
from query import START, Flag, FloorChange, NoRoute, Route, SearchResult, Snap, TooFar, route, search, snap
from routing import IMPASSABLE, NoPath, shortest_path, walk, wheelchair

WALK = walk({}, 1.0)  # speed 1: path costs in seconds equal meters
WHEELCHAIR = wheelchair({}, 1.0)

REAL_CAMPUS = Path(__file__).parents[2] / "data" / "northeastern-boston"

# tiny-campus nodes (lat, lon):
#   w1 (42.0005, -71.0005)  w2 (42.0005, -71.0015)  w3 (42.0025, -71.0015)
#   eA1 (42.0009, -71.0005) eA2 (42.0021, -71.0005)  island i1 (42.0050, -71.0050) i2 (42.0055, -71.0050)
# edges: eA1-w1 44.5, w1-w2 82.8, w2-w3 222.4 (vertical), w3-eA2 93.7, steps w1-w3 240.0 (diagonal, not accessible)


@pytest.fixture
def campus(tiny_campus):
    return load_campus(tiny_campus)


def fake_campus(buildings=(), pois=()):
    """Just the two mappings search reads, for ranking cases the fixture doesn't have.

    buildings: (id, name) pairs. pois: (id, name, building_id) or (id, name, building_id, category).
    """
    def poi(i, n, b, category=None):
        return POI(i, "n", n, category, b, None, None, None)
    return SimpleNamespace(
        buildings={i: Building(i, n, {}) for i, n in buildings},
        pois={p[0]: poi(*p) for p in pois},
        nodes={"n": SimpleNamespace(indoor=False, building_id=None)},  # every POI sits on outdoor node "n"
    )


def ids(results):
    return [r.id for r in results]


# --- on the tiny-campus fixture ---

def test_building_result_shape(campus):
    assert search(campus, "Building B") == (SearchResult("building", "bB", "Building B", "bB"),)


def test_entrance_poi_folds_into_its_building(campus):
    # the fixture's POIs are category=entrance, so a door name finds the building
    assert search(campus, "north entrance") == (SearchResult("building", "bA", "Building A", "bA"),)


def test_case_insensitive_and_whitespace_normalized(campus):
    assert ids(search(campus, "  bUILDING    a ")) == ids(search(campus, "Building A"))


def test_exact_then_prefix(campus):
    # entrance POIs fold into bA, so each building appears once
    assert ids(search(campus, "building a")) == ["bA"]
    assert ids(search(campus, "building")) == ["bA", "bB"]


@pytest.mark.parametrize("q", ["", "   ", "\t\n"])
def test_blank_query_gives_nothing(campus, q):
    assert search(campus, q) == ()


def test_no_match(campus):
    assert search(campus, "library") == ()


def test_limit(campus):
    assert ids(search(campus, "building", limit=1)) == ["bA"]


def test_id_match_ranks_after_name_matches(campus):
    # "bb" hits no name, so only Building B's id matches
    assert ids(search(campus, "bB")) == ["bB"]
    assert ids(search(campus, "BB")) == ["bB"]  # case-insensitive like names


def test_id_is_exact_only():
    c = fake_campus(buildings=[("wva", "West Village A")])
    assert search(c, "wv") == ()   # partial id: no match
    assert ids(search(c, "wva")) == ["wva"]


# --- ranking details (fake campus) ---

def test_full_tier_order():
    c = fake_campus(
        buildings=[
            ("ry", "Ryder Hall"),        # word prefix (building, so before the POI below)
            ("sub", "Subhall Annex"),    # plain substring
            ("hall", "Snell Library"),   # id equals "hall", name doesn't match → last
            ("h1", "Hall"),              # exact
            ("h2", "Hallway House"),     # prefix
        ],
        pois=[("p1", "Main Hall (Lobby)", None)],  # word prefix
    )
    assert ids(search(c, "hall")) == ["h1", "h2", "ry", "p1", "sub", "hall"]


def test_word_prefix_after_punctuation():
    c = fake_campus(pois=[("p1", "Building A (South Entrance)", None), ("p2", "Southwest Garage", None)])
    # "(South" counts as a word start, so p1 is a word prefix; p2 is a plain prefix and ranks first
    assert ids(search(c, "south")) == ["p2", "p1"]


def test_word_prefix_found_on_later_occurrence():
    # first "hall" is mid-word ("Marshall"), second starts a word
    c = fake_campus(buildings=[("x", "Marshall Hall"), ("y", "Marshallton")])
    assert ids(search(c, "hall")) == ["x", "y"]


def test_building_matched_by_name_and_id_appears_once_at_name_tier():
    c = fake_campus(buildings=[("cafe", "Cafe Annex"), ("zz", "Cafe")])
    assert ids(search(c, "cafe")) == ["zz", "cafe"]  # cafe ranks as prefix, not id-exact, and isn't repeated


def test_duplicate_poi_names_are_separate_results():
    c = fake_campus(pois=[("p2", "Door", "b"), ("p1", "Door", "b")])
    assert ids(search(c, "door")) == ["p1", "p2"]  # same name → ordered by id


def test_non_entrance_poi_is_its_own_result_and_carries_its_building():
    c = fake_campus(buildings=[("b", "Ell Hall")], pois=[("p", "Ell Hall Cafe", "b", "food")])
    assert search(c, "ell hall") == (SearchResult("building", "b", "Ell Hall", "b"),
                                     SearchResult("poi", "p", "Ell Hall Cafe", "b"))


# --- folding entrance POIs into buildings ---

def test_folded_door_name_finds_building_by_alias():
    c = fake_campus(buildings=[("isec", "Interdisciplinary Science & Eng")],
                    pois=[("p1", "ISEC (Accessible Entrance)", "isec", "entrance")])
    assert search(c, "isec") == (SearchResult("building", "isec", "Interdisciplinary Science & Eng", "isec"),)


def test_folded_building_ranks_at_best_tier():
    # the building's name is only a word-prefix match, but a door name is an exact match
    c = fake_campus(buildings=[("a", "Old Library Annex"), ("b", "Library Hall")],
                    pois=[("p1", "Library", "a", "entrance")])
    assert ids(search(c, "library")) == ["a", "b"]  # exact (via door) beats b's prefix


def test_several_doors_give_one_building_result():
    c = fake_campus(buildings=[("b", "Snell Library")],
                    pois=[("p1", "Snell Library (Accessible Entrance)", "b", "entrance"),
                          ("p2", "Snell Library NE (Accessible Entrance)", "b", "entrance")])
    assert ids(search(c, "snell")) == ["b"]


def test_entrance_poi_without_building_stays_a_poi():
    c = fake_campus(pois=[("p1", "Garage Door", None, "entrance")])
    assert search(c, "garage") == (SearchResult("poi", "p1", "Garage Door", None),)


def test_folded_pois_dont_use_up_limit():
    doors = [(f"p{i}", f"Alpha Door {i}", "a", "entrance") for i in range(5)]
    c = fake_campus(buildings=[("a", "Alpha Hall"), ("b", "Alpha Annex")], pois=doors)
    assert ids(search(c, "alpha", limit=2)) == ["b", "a"]


def test_pois_never_match_by_id():
    c = fake_campus(pois=[("lobby", "Main Entrance", None)])
    assert search(c, "lobby") == ()


# --- outdoor vs in-building search (tiny-indoor) ---

def test_outdoor_search_leaves_out_indoor_pois(indoor):
    assert search(indoor, "room 101") == ()
    assert ids(search(indoor, "headquarters")) == ["hq"]   # doors are outdoor nodes: still fold


def test_building_search_finds_rooms_with_poi_floor(indoor):
    assert search(indoor, "room", building="hq") == (SearchResult("poi", "poi_r101", "Room 101", "hq", 1),)


def test_building_search_lists_doors_unfolded(indoor):
    assert ids(search(indoor, "entrance", building="hq")) == ["poi_e2", "poi_e1"]  # by name


def test_building_search_has_no_building_results(indoor):
    assert all(r.kind == "poi" for r in search(indoor, "headquarters", building="hq"))


def test_building_search_unknown_building_raises(indoor):
    with pytest.raises(KeyError):
        search(indoor, "room", building="nope")


def test_building_search_blank_q(indoor):
    assert search(indoor, "  ", building="hq") == ()


def test_poi_without_building_id_uses_its_nodes(broken_campus):
    # poi_r101's building_id emptied: it's still in hq, via node r101
    c = load_campus(broken_campus("pois.csv", lambda rows: [r[:4] + [""] + r[5:] if r[0] == "poi_r101" else r
                                                            for r in rows], fixture=INDOOR_FIXTURE))
    assert search(c, "room", building="hq") == (SearchResult("poi", "poi_r101", "Room 101", "hq", 1),)


def test_poi_floor_shown_as_is_not_nodes(broken_campus):
    # a schematic POI: says floor 3 but points at door e1 (floor 0); search shows the POI's floor
    extra = ["poi_wc", "e1", "Restroom", "restroom", "hq", "3", "", ""]
    c = load_campus(broken_campus("pois.csv", lambda rows: rows + [extra], fixture=INDOOR_FIXTURE))
    (r,) = search(c, "restroom", building="hq")
    assert r.floor == 3


# --- snapping ---

def start_neighbors(s):
    return sorted(n for n, _ in s.adjacency[START])


def test_snap_mid_edge_splits_it(campus):
    s = snap(campus, 42.0015, -71.0017)  # ~16.5 m west of the middle of w2-w3
    assert s.node_id == START
    assert s.lat == pytest.approx(42.0015) and s.lon == pytest.approx(-71.0015)
    assert s.distance_m == pytest.approx(16.5, abs=0.2)
    assert start_neighbors(s) == ["w2", "w3"]
    halves = {n: e.cost for n, e in s.adjacency[START]}
    assert halves["w2"] == pytest.approx(111.2, abs=0.1)
    assert halves["w2"] + halves["w3"] == pytest.approx(222.4)
    assert all(e.edge_type == "footway" and e.accessible is True for _, e in s.adjacency[START])


def test_overlay_links_back_and_leaves_campus_untouched(campus):
    s = snap(campus, 42.0015, -71.0017)
    assert (START in s.adjacency) and (START not in campus.adjacency)
    assert len(s.adjacency) == len(campus.adjacency) + 1
    assert [n for n, _ in s.adjacency["w2"]].count(START) == 1
    assert s.adjacency["w2"][:len(campus.adjacency["w2"])] == campus.adjacency["w2"]
    assert s.adjacency["eA1"] is campus.adjacency["eA1"]  # untouched nodes pass through


def test_route_from_snap(campus):
    s = snap(campus, 42.0015, -71.0017)
    path = shortest_path(s.adjacency, {s.node_id}, campus.entrances_for("bA"), WALK)
    assert path.nodes == (START, "w3", "eA2")
    assert path.cost == pytest.approx(111.2 + 93.7, abs=0.1)


def test_point_on_node_uses_that_node(campus):
    s = snap(campus, 42.0005, -71.0015)  # exactly w2
    assert s == Snap("w2", 42.0005, -71.0015, 0.0, campus.adjacency, 0)


def test_projection_past_the_end_clamps_to_endpoint(campus):
    s = snap(campus, 42.0000, -71.0005)  # south of w1; every nearby edge ends at w1
    assert s.node_id == "w1"
    assert s.adjacency is campus.adjacency
    assert s.distance_m == pytest.approx(55.6, abs=0.1)


def test_walking_snaps_onto_steps_wheelchair_avoids_them(campus):
    on_steps = (42.0015, -71.0010)  # middle of the w1-w3 diagonal
    walk = snap(campus, *on_steps)
    assert walk.distance_m == pytest.approx(0, abs=0.01)
    assert [e.edge_type for _, e in walk.adjacency[START]] == ["steps", "steps"]

    wc = snap(campus, *on_steps, cost_fn=WHEELCHAIR)
    assert start_neighbors(wc) == ["w2", "w3"]
    assert wc.distance_m == pytest.approx(41.4, abs=0.2)


def test_parallel_edges_are_all_split(broken_campus):
    campus = load_campus(broken_campus(
        "edges.csv", lambda rows: rows + [["w1", "w3", "260.0", "meters", "footway", "True"]]))
    s = snap(campus, 42.0015, -71.0010, cost_fn=WHEELCHAIR)  # accessible footway beside the steps
    assert s.distance_m == pytest.approx(0, abs=0.01)
    assert sorted(e.edge_type for _, e in s.adjacency[START]) == ["footway", "footway", "steps", "steps"]

    path = shortest_path(s.adjacency, {s.node_id}, campus.entrances_for("bA"), WHEELCHAIR)
    assert path.nodes == (START, "w1", "eA1")
    assert path.edges[0].edge_type == "footway"
    assert path.cost == pytest.approx(130.0 + 44.5)


def test_too_far(campus):
    r = snap(campus, 42.0100, -71.0005)
    assert isinstance(r, TooFar) and r.distance_m > 200
    assert isinstance(snap(campus, 42.0100, -71.0005, max_m=10_000), Snap)


def test_no_usable_edge_is_too_far_inf(campus):
    assert snap(campus, 42.0015, -71.0017, cost_fn=lambda e, n: IMPASSABLE) == TooFar(math.inf)


def test_island_snap_then_no_path(campus):
    s = snap(campus, 42.00525, -71.0051)
    assert start_neighbors(s) == ["i1", "i2"]
    assert shortest_path(s.adjacency, {s.node_id}, campus.entrances_for("bA"), WALK) == NoPath()


@pytest.mark.parametrize("lat, lon", [(91, 0), (0, -181), (math.nan, 0), (0, math.inf)])
def test_invalid_coordinates_raise(campus, lat, lon):
    with pytest.raises(ValueError):
        snap(campus, lat, lon)


# --- routes ---

MID_W2_W3 = (42.0015, -71.0017)  # ~16.5 m west of the middle of w2-w3
AT_W3 = (42.0025, -71.0015)


def test_route_to_building_picks_nearer_entrance(campus):
    r = route(campus, *MID_W2_W3, to_building="bA")
    assert r.entrance_id == "eA2"
    assert r.entrance_name == "Building A (North Entrance)"
    assert r.building_id == "bA"
    assert r.distance_m == pytest.approx(111.2 + 93.7, abs=0.1)
    assert r.approach_m == pytest.approx(16.5, abs=0.2)
    assert r.duration_s == pytest.approx((r.approach_m + r.distance_m) / 1.4)


def test_polyline_starts_at_snapped_point(campus):
    r = route(campus, *MID_W2_W3, to_building="bA")
    assert r.coords[0] == pytest.approx((42.0015, -71.0015))
    assert r.coords[1:] == ((42.0025, -71.0015), (42.0021, -71.0005))  # w3, eA2
    assert r.nodes == (START, "w3", "eA2")
    assert len(r.edges) == len(r.nodes) - 1
    assert r.edges[0].cost == pytest.approx(111.2, abs=0.1)  # half of w2-w3
    assert [e.edge_type for e in r.edges] == ["footway", "connector"]


def test_route_edges_show_steps_on_walking_route(campus):
    walk = route(campus, *AT_W3, to_poi="poi_eA1")
    assert walk.nodes == ("w3", "w1", "eA1")  # snapped onto w3 itself, so no START
    assert walk.edges[0].edge_type == "steps" and walk.edges[0].accessible is False



def test_walking_route_over_steps_is_flagged(campus):
    walk = route(campus, *AT_W3, to_poi="poi_eA1")  # w3 -steps- w1 - eA1
    assert walk.flags == (Flag(0, False, "steps"),)


def test_wheelchair_route_has_no_flags(campus):
    assert route(campus, *AT_W3, to_poi="poi_eA1", mode="wheelchair").flags == ()


def test_accessible_route_has_no_flags(campus):
    assert route(campus, *MID_W2_W3, to_building="bA").flags == ()


def test_unknown_accessibility_is_flagged(broken_campus):
    def unknown_w3_ea2(rows):
        assert rows[4][:2] == ["w3", "eA2"]
        rows[4][5] = ""
        return rows
    campus = load_campus(broken_campus("edges.csv", unknown_w3_ea2))
    r = route(campus, *MID_W2_W3, to_building="bA")
    assert r.nodes == (START, "w3", "eA2")
    assert r.flags == (Flag(1, None, "connector"),)


def test_start_partway_along_steps_flags_the_half_edge(campus):
    r = route(campus, 42.0015, -71.0010, to_poi="poi_eA1")  # middle of the w1-w3 steps
    assert r.nodes == (START, "w1", "eA1")
    assert r.flags == (Flag(0, False, "steps"),)

def test_route_to_poi_goes_to_that_entrance(campus):
    r = route(campus, *MID_W2_W3, to_poi="poi_eA1")  # the farther entrance
    assert r.entrance_id == "eA1"
    assert r.distance_m == pytest.approx(111.2 + 82.8 + 44.5, abs=0.1)


def test_wheelchair_avoids_steps_and_is_slower(campus):
    walk = route(campus, *AT_W3, to_poi="poi_eA1")
    wc = route(campus, *AT_W3, to_poi="poi_eA1", mode="wheelchair")
    assert walk.distance_m == pytest.approx(240.0 + 44.5)              # w3 -steps- w1 - eA1
    assert wc.distance_m == pytest.approx(222.4 + 82.8 + 44.5)         # w3 - w2 - w1 - eA1
    assert wc.duration_s == pytest.approx(wc.distance_m / 1.1)


def with_lift(broken_campus, secs):
    """tiny-campus plus an accessible seconds edge (an "elevator") parallel to the w1-w3 steps."""
    return load_campus(broken_campus(
        "edges.csv", lambda rows: rows + [["w1", "w3", str(secs), "seconds", "elevator", "True"]]))


@pytest.mark.parametrize("mode, speed", [("walk", 1.4), ("wheelchair", 1.1)])
def test_fast_seconds_edge_is_taken_and_counts_as_time_only(broken_campus, mode, speed):
    # 60 s beats the steps (240 m / 1.4 = 171 s) and the long way round
    r = route(with_lift(broken_campus, 60), *AT_W3, to_poi="poi_eA1", mode=mode)
    assert r.nodes == ("w3", "w1", "eA1")
    assert r.edges[0].edge_type == "elevator"
    assert r.distance_m == pytest.approx(44.5)                  # the 60 s edge adds no meters
    assert r.duration_s == pytest.approx(44.5 / speed + 60)     # but does add its seconds


def test_slow_seconds_edge_loses_to_meters(broken_campus):
    # 1000 s is slower than walking the steps, so walking ignores it
    r = route(with_lift(broken_campus, 1000), *AT_W3, to_poi="poi_eA1")
    assert [e.edge_type for e in r.edges] == ["steps", "connector"]
    assert r.duration_s == pytest.approx((240.0 + 44.5) / 1.4)


def door_blocked(broken_campus, *lines, value="False"):
    """tiny-campus with the doors on the given nodes.csv lines (2 = eA1, 3 = eA2) not accessible."""
    def edit(rows):
        for line in lines:
            rows[line - 1][rows[0].index("accessible")] = value
        return rows
    return load_campus(broken_campus("nodes.csv", edit))


@pytest.mark.parametrize("value", ["False", ""])  # known steps, or unknown
def test_wheelchair_skips_an_inaccessible_door(broken_campus, value):
    campus = door_blocked(broken_campus, 3, value=value)  # eA2, the nearer door from w3
    assert route(campus, *AT_W3, to_building="bA").entrance_id == "eA2"  # walking doesn't care
    wc = route(campus, *AT_W3, to_building="bA", mode="wheelchair")
    assert wc.entrance_id == "eA1" and "eA2" not in wc.nodes


def test_wheelchair_no_path_when_every_door_is_blocked(broken_campus):
    campus = door_blocked(broken_campus, 2, 3)
    assert route(campus, *AT_W3, to_building="bA", mode="wheelchair") == NoRoute("no_path")


def test_wheelchair_to_a_blocked_entrance_is_no_path(broken_campus):
    campus = door_blocked(broken_campus, 3)
    assert route(campus, *AT_W3, to_entrance="eA2").entrance_id == "eA2"
    assert route(campus, *AT_W3, to_entrance="eA2", mode="wheelchair") == NoRoute("no_path")


def test_wheelchair_never_snaps_onto_a_blocked_door(broken_campus):
    campus = door_blocked(broken_campus, 3)
    near_connector = (42.0023, -71.0010)  # middle of the w3-eA2 connector
    assert start_neighbors(snap(campus, *near_connector)) == ["eA2", "w3"]
    wc = snap(campus, *near_connector, cost_fn=wheelchair(campus.nodes, 1.1))
    assert wc.node_id != "eA2"
    assert wc.node_id != START or "eA2" not in start_neighbors(wc)


def test_start_on_entrance_is_zero_length(campus):
    r = route(campus, 42.0009, -71.0005, to_building="bA")  # exactly eA1
    assert r.coords == ((42.0009, -71.0005),)
    assert r.distance_m == 0 and r.duration_s == 0
    assert r.entrance_id == "eA1"


def test_route_no_entrances(campus):
    assert route(campus, *MID_W2_W3, to_building="bB") == NoRoute("no_entrances")


def test_route_too_far(campus):
    r = route(campus, 42.0100, -71.0005, to_building="bA")
    assert r.reason == "too_far" and r.distance_m > 200


def test_no_path_from_island(campus):
    assert route(campus, 42.00525, -71.0051, to_building="bA") == NoRoute("no_path")


def test_route_to_entrance_goes_to_that_door(campus):
    best = route(campus, *MID_W2_W3, to_building="bA")
    assert best.entrance_id == "eA2"
    r = route(campus, *MID_W2_W3, to_entrance="eA1")  # the farther door
    assert r.entrance_id == "eA1"
    assert r.entrance_name == "Building A (South Entrance)"
    assert r.building_id == "bA"
    assert r.distance_m == pytest.approx(111.2 + 82.8 + 44.5, abs=0.1)


def test_route_to_entrance_wheelchair_avoids_steps(campus):
    walk = route(campus, *AT_W3, to_entrance="eA1")
    wc = route(campus, *AT_W3, to_entrance="eA1", mode="wheelchair")
    assert walk.nodes == ("w3", "w1", "eA1") and walk.flags
    assert wc.nodes == ("w3", "w2", "w1", "eA1") and wc.flags == ()


@pytest.mark.parametrize("kwargs, err", [
    ({}, ValueError),
    ({"to_building": "bA", "to_poi": "poi_eA1"}, ValueError),
    ({"to_building": "bA", "to_entrance": "eA1"}, ValueError),
    ({"to_poi": "poi_eA1", "to_entrance": "eA1"}, ValueError),
    ({"to_entrance": "w1"}, KeyError),     # a node, but not an entrance
    ({"to_entrance": "nope"}, KeyError),
    ({"to_entrance": "EA1"}, KeyError),    # case-sensitive
    ({"to_building": "bA", "mode": "bike"}, ValueError),
    ({"to_building": "nope"}, KeyError),
    ({"to_poi": "nope"}, KeyError),
])
def test_caller_bugs_raise(campus, kwargs, err):
    with pytest.raises(err):
        route(campus, *MID_W2_W3, **kwargs)


def test_route_on_real_campus():
    campus = load_campus(REAL_CAMPUS)
    for mode in ("walk", "wheelchair"):
        r = route(campus, 42.3398, -71.0892, to_building="ry", mode=mode)
        assert isinstance(r, Route) and r.building_id == "ry"


def test_real_campus_door_rule_cuts_nothing_off():
    # Every Northeastern door is accessible=True, so wheelchair reachability must be exactly
    # what the edges alone allow. (Two buildings, wve and ha, are reachable only over steps;
    # that's the sidewalk data, not the door rule.)
    campus = load_campus(REAL_CAMPUS)
    start = [campus.entrances_by_building["ry"][0]]
    with_doors, edges_only = wheelchair(campus.nodes, 1.1), wheelchair({}, 1.1)
    for building_id, entrances in campus.entrances_by_building.items():
        assert (shortest_path(campus.adjacency, start, entrances, with_doors)
                == shortest_path(campus.adjacency, start, entrances, edges_only)), building_id


# --- indoor (tiny-indoor fixture) ---
# hq: south door e1 (floor 0, accessible) - c0 - stairs s0-s1 (15 s) / elevator l0-l1 (35 s) - c1 - r101 (floor 1);
# north door e2 (floor 1, accessible=False) - c1. Outdoor sidewalk o1 - o2 - o3 - o4; o1-e1 and o4-e2 connectors.

SOUTH = (42.30000, -71.10010)   # ~5.6 m south of o1; snaps onto o1
NORTH = (42.30040, -71.10010)   # ~5.6 m north of o4; snaps onto o4


@pytest.fixture
def indoor(tiny_indoor):
    return load_campus(tiny_indoor)


def test_gps_inside_building_snaps_outdoors(indoor):
    at_c0 = (42.30015, -71.10010)  # on the floor-0 corridor: nearest outdoor edge is the o1-e1 connector
    s = snap(indoor, *at_c0)
    assert s.node_id == "e1"       # the door end of the connector, never a corridor
    assert not indoor.nodes[s.node_id].indoor


def test_gps_with_only_indoor_edges_nearby_is_too_far(broken_campus):
    # drop every outdoor edge: an indoor-only graph gives GPS nothing to snap onto
    outdoor = {"o1", "o2", "o3", "o4"}
    campus = load_campus(broken_campus(
        "edges.csv", lambda rows: [r for r in rows if not ({r[0], r[1]} & outdoor)], fixture=INDOOR_FIXTURE))
    assert snap(campus, 42.30015, -71.10010) == TooFar(math.inf)


def test_walk_to_room_takes_the_stairs(indoor):
    r = route(indoor, *SOUTH, to_poi="poi_r101")
    assert r.nodes == ("o1", "e1", "c0", "s0", "s1", "c1", "r101")
    assert r.floors == (0, 0, 0, 0, 1, 1, 1)
    assert r.indoor == (False, False, True, True, True, True, True)
    assert r.floor_changes == (FloorChange(3, 0, 1, "steps"),)
    assert r.flags == (Flag(3, False, "steps"),)
    assert r.distance_m == pytest.approx(5.6 + 5.6 + 6.9 + 6.9 + 6.2)  # the stairs add no meters
    assert r.duration_s == pytest.approx((r.approach_m + r.distance_m) / 1.4 + 15)
    assert (r.end_id, r.entrance_id, r.entrance_name, r.building_id) == (
        "r101", "e1", "Headquarters (South Entrance)", "hq")


def test_wheelchair_to_room_takes_the_elevator(indoor):
    r = route(indoor, *SOUTH, to_poi="poi_r101", mode="wheelchair")
    assert r.nodes == ("o1", "e1", "c0", "l0", "l1", "c1", "r101")
    assert r.floor_changes == (FloorChange(3, 0, 1, "elevator"),)
    assert r.flags == ()
    assert r.duration_s == pytest.approx((r.approach_m + r.distance_m) / 1.1 + 35)


def test_walk_from_north_enters_on_floor_1(indoor):
    # e2 is on floor 1 (up the hill), so the door itself is where the floor changes: no stairs
    r = route(indoor, *NORTH, to_poi="poi_r101")
    assert r.nodes == ("o4", "e2", "c1", "r101")
    assert r.floor_changes == (FloorChange(0, 0, 1, "connector"),)
    assert r.entrance_id == "e2" and r.flags == ()


def test_wheelchair_from_north_goes_around_the_stepped_door(indoor):
    r = route(indoor, *NORTH, to_poi="poi_r101", mode="wheelchair")
    assert r.nodes == ("o4", "o3", "o2", "o1", "e1", "c0", "l0", "l1", "c1", "r101")
    assert r.entrance_id == "e1"


def test_start_from_room(indoor):
    r = route(indoor, from_poi="poi_r101", to_entrance="e2")
    assert r.nodes == ("r101", "c1", "e2")
    assert r.coords[0] == (indoor.nodes["r101"].x_or_lat, indoor.nodes["r101"].y_or_lon)
    assert r.approach_m == 0 and r.floors == (1, 1, 1) and r.indoor == (True, True, False)


def test_start_from_room_wheelchair_to_stepped_door_is_no_path(indoor):
    assert route(indoor, from_poi="poi_r101", to_entrance="e2", mode="wheelchair") == NoRoute("no_path")


def test_start_from_room_to_building_uses_the_nearest_door(indoor):
    assert route(indoor, from_poi="poi_r101", to_building="hq").end_id == "e2"
    assert route(indoor, from_poi="poi_r101", to_building="hq", mode="wheelchair").end_id == "e1"


def test_start_from_entrance(indoor):
    r = route(indoor, from_entrance="e1", to_poi="poi_r101")
    assert r.nodes == ("e1", "c0", "s0", "s1", "c1", "r101")
    assert r.approach_m == 0 and r.entrance_id == "e1"


def test_start_from_blocked_entrance_wheelchair_is_no_path(indoor):
    assert route(indoor, from_entrance="e2", to_poi="poi_r101", mode="wheelchair") == NoRoute("no_path")


def test_room_to_same_room_is_zero_length(indoor):
    r = route(indoor, from_poi="poi_r101", to_poi="poi_r101")
    assert r.nodes == ("r101",) and r.distance_m == 0 and r.duration_s == 0
    assert r.entrance_id is None and r.entrance_name is None  # no door on the path
    assert r.floors == (1,) and r.floor_changes == ()


@pytest.mark.parametrize("args, kwargs, err", [
    ((), {"to_building": "hq"}, ValueError),                                       # no start
    ((42.3,), {"to_building": "hq"}, ValueError),                                  # lat without lon
    (SOUTH, {"from_poi": "poi_r101", "to_building": "hq"}, ValueError),            # two starts
    ((), {"from_poi": "poi_r101", "from_entrance": "e1", "to_building": "hq"}, ValueError),
    ((), {"from_poi": "nope", "to_building": "hq"}, KeyError),
    ((), {"from_entrance": "c0", "to_building": "hq"}, KeyError),                  # a node, not an entrance
])
def test_start_caller_bugs_raise(indoor, args, kwargs, err):
    with pytest.raises(err):
        route(indoor, *args, **kwargs)


def test_outdoor_routes_have_flat_floor_info(campus):
    r = route(campus, *AT_W3, to_building="bA")
    assert set(r.floors) == {0} and not any(r.indoor) and r.floor_changes == ()
    assert r.entrance_id == r.end_id == "eA2"

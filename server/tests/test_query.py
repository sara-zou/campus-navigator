import math
from types import SimpleNamespace

import pytest

from loader import POI, Building, load_campus
from query import START, SearchResult, Snap, TooFar, search, snap
from routing import IMPASSABLE, NoPath, distance, shortest_path, wheelchair

# tiny-campus nodes (lat, lon):
#   w1 (42.0005, -71.0005)  w2 (42.0005, -71.0015)  w3 (42.0025, -71.0015)
#   eA1 (42.0009, -71.0005) eA2 (42.0021, -71.0005)  island i1 (42.0050, -71.0050) i2 (42.0055, -71.0050)
# edges: eA1-w1 44.5, w1-w2 82.8, w2-w3 222.4 (vertical), w3-eA2 93.7, steps w1-w3 240.0 (diagonal, not accessible)


@pytest.fixture
def campus(tiny_campus):
    return load_campus(tiny_campus)


def fake_campus(buildings=(), pois=()):
    """Just the two mappings search reads, for ranking cases the fixture doesn't have.

    buildings: (id, name) pairs. pois: (id, name, building_id) triples.
    """
    return SimpleNamespace(
        buildings={i: Building(i, n, {}) for i, n in buildings},
        pois={i: POI(i, "n", n, None, b, None, None, None) for i, n, b in pois},
    )


def ids(results):
    return [r.id for r in results]


# --- on the tiny-campus fixture ---

def test_building_result_shape(campus):
    assert search(campus, "Building B") == (SearchResult("building", "bB", "Building B", "bB"),)


def test_poi_result_carries_its_building(campus):
    (r,) = search(campus, "north entrance")
    assert r == SearchResult("poi", "poi_eA2", "Building A (North Entrance)", "bA")


def test_case_insensitive_and_whitespace_normalized(campus):
    assert ids(search(campus, "  bUILDING    a ")) == ids(search(campus, "Building A"))


def test_exact_then_prefix_buildings_before_pois(campus):
    # "Building A" exact; the other three are prefixes: building B first, then POIs by name
    assert ids(search(campus, "building a")) == ["bA"]  + ["poi_eA2", "poi_eA1"]
    assert ids(search(campus, "building")) == ["bA", "bB", "poi_eA2", "poi_eA1"]


@pytest.mark.parametrize("q", ["", "   ", "\t\n"])
def test_blank_query_gives_nothing(campus, q):
    assert search(campus, q) == ()


def test_no_match(campus):
    assert search(campus, "library") == ()


def test_limit(campus):
    assert ids(search(campus, "building", limit=2)) == ["bA", "bB"]


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


def test_pois_never_match_by_id():
    c = fake_campus(pois=[("lobby", "Main Entrance", None)])
    assert search(c, "lobby") == ()


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
    path = shortest_path(s.adjacency, {s.node_id}, campus.entrances_for("bA"), distance)
    assert path.nodes == (START, "w3", "eA2")
    assert path.cost == pytest.approx(111.2 + 93.7, abs=0.1)


def test_point_on_node_uses_that_node(campus):
    s = snap(campus, 42.0005, -71.0015)  # exactly w2
    assert s == Snap("w2", 42.0005, -71.0015, 0.0, campus.adjacency)


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

    wc = snap(campus, *on_steps, cost_fn=wheelchair)
    assert start_neighbors(wc) == ["w2", "w3"]
    assert wc.distance_m == pytest.approx(41.4, abs=0.2)


def test_parallel_edges_are_all_split(broken_campus):
    campus = load_campus(broken_campus(
        "edges.csv", lambda rows: rows + [["w1", "w3", "260.0", "meters", "footway", "True"]]))
    s = snap(campus, 42.0015, -71.0010, cost_fn=wheelchair)  # accessible footway beside the steps
    assert s.distance_m == pytest.approx(0, abs=0.01)
    assert sorted(e.edge_type for _, e in s.adjacency[START]) == ["footway", "footway", "steps", "steps"]

    path = shortest_path(s.adjacency, {s.node_id}, campus.entrances_for("bA"), wheelchair)
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
    assert shortest_path(s.adjacency, {s.node_id}, campus.entrances_for("bA"), distance) == NoPath()


@pytest.mark.parametrize("lat, lon", [(91, 0), (0, -181), (math.nan, 0), (0, math.inf)])
def test_invalid_coordinates_raise(campus, lat, lon):
    with pytest.raises(ValueError):
        snap(campus, lat, lon)

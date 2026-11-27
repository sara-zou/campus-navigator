"""Query layer: search()."""
from types import SimpleNamespace

import pytest

from conftest import INDOOR_FIXTURE
from loader import load_campus
from models import POI, Building
from query import SearchResult, search


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

from types import SimpleNamespace

import pytest

from loader import POI, Building, load_campus
from query import SearchResult, search


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

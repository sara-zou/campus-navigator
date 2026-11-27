"""Search: a pure lookup over building and POI names; it never touches the graph."""
from dataclasses import dataclass

DEFAULT_SEARCH_LIMIT = 20

# Rank tiers, best first. Lower number = earlier in results.
EXACT, PREFIX, WORD_PREFIX, SUBSTRING, ID_EXACT = range(5)
KIND_ORDER = {"building": 0, "poi": 1}  # tie-break within a tier
# POI categories that search reports as their building: a door's name is just another
# way to find the building, and routing to the building picks its best door anyway.
FOLD_INTO_BUILDING = frozenset({"entrance"})


@dataclass(frozen=True)
class SearchResult:
    kind: str                # "building" | "poi"
    id: str                  # building_id or poi_id
    name: str
    building_id: str | None  # a building's own id; a POI's building, if any
    floor: int | None = None # a POI's own floor (pois.csv), shown as a label; None for buildings


def search(campus, q, limit=DEFAULT_SEARCH_LIMIT, building=None):
    """Matches for q, best first, at most `limit`.

    Without `building` (the outdoor search): buildings and POIs on outdoor nodes. POIs on
    indoor nodes (rooms) are left out, so they never flood campus-wide results.
    With `building`: only POIs in that building (see poi_building), indoor or not, doors
    included and not folded. An unknown building raises KeyError (caller bug).

    Case-insensitive; q is trimmed and its inner whitespace collapsed. Blank q gives ().
    Ranking: exact name, name prefix, word prefix, other substring, and last,
    buildings whose id equals q (only if not already matched by name).
    Ties: buildings before POIs, then name, then id.

    In the outdoor search, POIs in FOLD_INTO_BUILDING (with a building_id) are reported as
    their building, once, at the best tier among the building's name and those POIs' names.
    Folding happens before `limit`, so folded POIs never take up result slots.
    """
    if building is not None and building not in campus.buildings:
        raise KeyError(building)
    needle = _normalize(q)
    if not needle:
        return ()

    ranked = []          # (tier, kind order, name, id, result)
    building_tier = {}   # building_id -> best tier from its name, its id, or its folded POIs

    def add(tier, result):
        ranked.append((tier, KIND_ORDER[result.kind], result.name.casefold(), result.id, result))

    def match_building(building_id, tier):
        building_tier[building_id] = min(tier, building_tier.get(building_id, tier))

    if building is None:
        for b in campus.buildings.values():
            tier = _name_tier(b.name, needle)
            if tier is None and b.id.casefold() == needle:
                tier = ID_EXACT
            if tier is not None:
                match_building(b.id, tier)

    for p in campus.pois.values():
        if building is None:
            if campus.nodes[p.node_id].indoor:
                continue
        elif poi_building(campus, p) != building:
            continue
        tier = _name_tier(p.name, needle)
        if tier is None:
            continue
        if building is None and p.category in FOLD_INTO_BUILDING and p.building_id is not None:
            match_building(p.building_id, tier)
        else:
            add(tier, SearchResult("poi", p.id, p.name, poi_building(campus, p), p.floor))

    for building_id, tier in building_tier.items():
        b = campus.buildings[building_id]
        add(tier, SearchResult("building", b.id, b.name, b.id))

    ranked.sort(key=lambda r: r[:4])
    return tuple(r[4] for r in ranked[:limit])


def poi_building(campus, poi):
    """The building a POI is in: its own building_id, else its node's (the loader rejects a mismatch)."""
    return poi.building_id if poi.building_id is not None else campus.nodes[poi.node_id].building_id


def _normalize(s):
    return " ".join(s.split()).casefold()


def _name_tier(name, needle):
    """Which rank tier `name` falls in for an already-normalized needle, or None if no match."""
    hay = _normalize(name)
    if hay == needle:
        return EXACT
    if hay.startswith(needle):
        return PREFIX
    i = hay.find(needle)
    if i < 0:
        return None
    while i >= 0:  # word prefix: some occurrence starts right after a non-alphanumeric char
        if not hay[i - 1].isalnum():
            return WORD_PREFIX
        i = hay.find(needle, i + 1)
    return SUBSTRING

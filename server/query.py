"""Query layer: turns user-facing requests into routing calls and readable results.

Search is a pure lookup over names; it never touches the graph.
"""
from dataclasses import dataclass

DEFAULT_SEARCH_LIMIT = 20

# Rank tiers, best first. Lower number = earlier in results.
EXACT, PREFIX, WORD_PREFIX, SUBSTRING, ID_EXACT = range(5)
KIND_ORDER = {"building": 0, "poi": 1}  # tie-break within a tier


@dataclass(frozen=True)
class SearchResult:
    kind: str                # "building" | "poi"
    id: str                  # building_id or poi_id
    name: str
    building_id: str | None  # a building's own id; a POI's building, if any


# --- search ---

def search(campus, q, limit=DEFAULT_SEARCH_LIMIT):
    """Buildings and POIs whose name matches q, best first, at most `limit`.

    Case-insensitive; q is trimmed and its inner whitespace collapsed. Blank q gives ().
    Ranking: exact name, name prefix, word prefix, other substring, and last,
    buildings whose id equals q (only if not already matched by name).
    Ties: buildings before POIs, then name, then id.
    """
    needle = _normalize(q)
    if not needle:
        return ()

    ranked = []  # (tier, kind order, name, id, result)

    def add(tier, result):
        ranked.append((tier, KIND_ORDER[result.kind], result.name.casefold(), result.id, result))

    for b in campus.buildings.values():
        tier = _name_tier(b.name, needle)
        if tier is None and b.id.casefold() == needle:
            tier = ID_EXACT
        if tier is not None:
            add(tier, SearchResult("building", b.id, b.name, b.id))

    for p in campus.pois.values():
        tier = _name_tier(p.name, needle)
        if tier is not None:
            add(tier, SearchResult("poi", p.id, p.name, p.building_id))

    ranked.sort(key=lambda r: r[:4])
    return tuple(r[4] for r in ranked[:limit])


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

"""
Fix building_id mismatches between entrance-derived IDs (slugified from a
free-text Name, used when an entrance's Label was null) and the real short
codes used by the buildings layer's Facility_ID field.

Each entry below was found by hand after merge_buildings.py flagged these
building_ids as never getting a polygon match.
"""

import csv
from pathlib import Path

CAMPUS_ID = "northeastern-boston"
DATA_DIR = Path(__file__).parent.parent.parent.parent / "data" / CAMPUS_ID

CORRECTIONS = {
    "hurtig-hall": "ht",
    "dodge": "dg",
    "snell-library-ne": "sl",       # merges into the existing Snell Library building
    "lightview": "lv",
    "stearns-center": "st",         
    "kariotis-hall": "ka",
    "cargill-hall": "cg",
    "docket-hall": "dk",            # source data typo: "Docket Hall" -> really "Dockser Hall"
    "140-the-fenway": "140",
}


def read_csv(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    nodes_path = DATA_DIR / "nodes.csv"
    pois_path = DATA_DIR / "pois.csv"
    buildings_path = DATA_DIR / "buildings.csv"

    nodes = read_csv(nodes_path)
    pois = read_csv(pois_path)
    buildings = read_csv(buildings_path)

    for row in nodes:
        if row["building_id"] in CORRECTIONS:
            row["building_id"] = CORRECTIONS[row["building_id"]]
    for row in pois:
        if row["building_id"] in CORRECTIONS:
            row["building_id"] = CORRECTIONS[row["building_id"]]

    buildings = [b for b in buildings if b["building_id"] not in CORRECTIONS]

    write_csv(nodes_path, ["node_id", "campus_id", "building_id", "floor", "coord_system", "x_or_lat", "y_or_lon", "type"], nodes)
    write_csv(pois_path, ["poi_id", "node_id", "name", "category", "building_id", "floor", "accessible", "notes"], pois)
    write_csv(buildings_path, ["building_id", "name", "polygon_geojson"], buildings)

    print(f"Fixed {len(CORRECTIONS)} building_id mismatches across nodes.csv, pois.csv, buildings.csv")
    print("Re-run merge_buildings.py to confirm zero buildings remain unmatched.")


if __name__ == "__main__":
    main()

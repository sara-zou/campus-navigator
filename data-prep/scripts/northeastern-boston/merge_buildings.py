"""
Merge Northeastern's ArcGIS 'Boston_Buildings_(Internal)_view' GeoJSON into
the existing buildings.csv produced by transform_entrances.py.

Matching strategy: the buildings layer's `Facility_ID` field uses the same
short code as the entrances layer's `Label` field (e.g. "WVA", "SN", "SE").
Since transform_entrances.py already used that code (lowercased) as
building_id, matching here is just: slugify(Facility_ID) == building_id.

This does NOT always line up perfectly - a few known real-world mismatches
this script will flag rather than silently guess through:
  - Some entrances had no Label, so their building_id was slugified from
    the entrance's free-text Name instead (e.g. "Dodge" -> "dodge"), which
    won't match this building's Facility_ID "DG" -> "dg".
  - "SE" is used by the buildings layer for "Stetson East" but was used by
    one entrance (no label, name "Snell Engineering Auditorium") -> a real
    naming collision in the source data, not a bug in this script.

"""

import json
import csv
import re
from pathlib import Path

CAMPUS_ID = "northeastern-boston"
RAW_PATH = Path(__file__).parent.parent / "raw" / "boston_buildings.geojson"
BUILDINGS_CSV = Path(__file__).parent.parent.parent / "data" / CAMPUS_ID / "buildings.csv"


def slugify(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def load_existing_buildings(path: Path) -> dict:
    buildings = {}
    if not path.exists():
        print(f"no existing buildings path found.")
        return buildings
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            buildings[row["building_id"]] = row
    return buildings


def load_building_features(path: Path) -> list[dict]:
    with open(path) as f:
        data = json.load(f)
    return [f for f in data["features"] if f["properties"].get("Site_ID") == "BO"]


def main():
    existing = load_existing_buildings(BUILDINGS_CSV)
    print(f"Loaded {len(existing)} existing buildings (from entrances data)")

    features = load_building_features(RAW_PATH)
    print(f"Loaded {len(features)} Boston campus building polygons")

    matched = 0
    added = 0
    unmatched_new = []

    for feature in features:
        props = feature["properties"]
        facility_id = props.get("Facility_ID")
        if not facility_id:
            continue

        building_id = slugify(facility_id)
        name = props.get("Name_Long") or props.get("Name") or facility_id
        polygon_json = json.dumps(feature["geometry"])

        if building_id in existing:
            existing[building_id]["name"] = name  # prefer the fuller official name
            existing[building_id]["polygon_geojson"] = polygon_json
            matched += 1
        else:
            # A building with no accessible entrance in our current data, still kept
            existing[building_id] = {
                "building_id": building_id,
                "name": name,
                "polygon_geojson": polygon_json,
            }
            unmatched_new.append((building_id, name))
            added += 1

    # Which existing (entrance-derived) buildings never got a polygon match?
    # These are worth checking by hand - likely a Facility_ID/Label mismatch.
    still_empty = [b for b in existing.values() if not b.get("polygon_geojson")]

    with open(BUILDINGS_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["building_id", "name", "polygon_geojson"])
        writer.writeheader()
        for row in existing.values():
            writer.writerow(row)

    print(f"\nMatched {matched} existing buildings to polygons")
    print(f"Added {added} new buildings that had no accessible entrance")
    if still_empty:
        print(f"\n{len(still_empty)} buildings still have NO polygon, check for a Facility_ID/Label mismatch:")
        for b in still_empty:
            print(f"  - {b['building_id']} ({b['name']})")


if __name__ == "__main__":
    main()

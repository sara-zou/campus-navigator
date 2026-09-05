"""
Transform Northeastern's ArcGIS 'Accessible Entrance' GeoJSON export into
the project's standard schema: buildings.csv, nodes.csv, pois.csv.

"""

import json
import csv
import re
from pathlib import Path

CAMPUS_ID = "northeastern-boston"
RAW_PATH = Path(__file__).parent.parent / "raw" / "accessible_entrances.geojson"
OUT_DIR = Path(__file__).parent.parent.parent / "data" / CAMPUS_ID


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def load_features(path: Path) -> list[dict]:
    with open(path) as f:
        data = json.load(f)
    return data["features"]


def main():
    features = load_features(RAW_PATH)
    print(f"Loaded {len(features)} raw features")

    buildings = {}   # {building_id, name}
    nodes = []       
    pois = []         

    for feature in features:
        props = feature["properties"]
        lon, lat = feature["geometry"]["coordinates"]  # lon, lat

        raw_name = (props.get("Name") or "").strip()
        raw_label = (props.get("Label") or "").strip()

        building_id = slugify(raw_label) if raw_label else slugify(raw_name)

        if not building_id:
            # Skip the rare row with neither a name nor a label
            print(f"Skipping feature {feature.get('id')}, no name or label")
            continue

        # Register the building
        if building_id not in buildings:
            buildings[building_id] = {
                "building_id": building_id,
                "name": raw_name,
                "polygon_geojson": "",  # filled in merge_buildings
            }

        node_id = f"entrance_{props['GlobalID']}"

        nodes.append({
            "node_id": node_id,
            "campus_id": CAMPUS_ID,
            "building_id": building_id,
            "floor": 0,
            "coord_system": "latlon",
            "x_or_lat": lat,
            "y_or_lon": lon,
            "type": "entrance",
        })

        # Combine Comments + Notes into one free-text field
        note_parts = [p for p in (props.get("Comments"), props.get("Notes")) if p]
        notes = " | ".join(note_parts)

        pois.append({
            "poi_id": f"poi_{node_id}",
            "node_id": node_id,
            "name": f"{raw_name} (Accessible Entrance)" if raw_name else "Accessible Entrance",
            "category": "entrance",
            "building_id": building_id,
            "floor": 0,
            "accessible": True,
            "notes": notes,
        })

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    write_csv(OUT_DIR / "buildings.csv",
              ["building_id", "name", "polygon_geojson"],
              buildings.values())

    write_csv(OUT_DIR / "nodes.csv",
              ["node_id", "campus_id", "building_id", "floor", "coord_system", "x_or_lat", "y_or_lon", "type"],
              nodes)

    write_csv(OUT_DIR / "pois.csv",
              ["poi_id", "node_id", "name", "category", "building_id", "floor", "accessible", "notes"],
              pois)

    print(f"\nWrote {len(buildings)} buildings, {len(nodes)} nodes, {len(pois)} pois")
    print(f"Output dir: {OUT_DIR}")

    # Flag anything from notes
    flagged = [p for p in pois if p["notes"]]
    if flagged:
        print(f"\n{len(flagged)} entrances have facilities notes worth reviewing:")
        for p in flagged:
            print(f"  - {p['name']}: {p['notes']}")


def write_csv(path: Path, fieldnames: list[str], rows):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


if __name__ == "__main__":
    main()

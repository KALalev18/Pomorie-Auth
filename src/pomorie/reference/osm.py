"""Extract the OpenStreetMap features used to enrich reports.

Reads the Geofabrik extract for Bulgaria (a daily snapshot of OSM) instead of querying the
public Overpass API, which asks automated clients not to use it. The ~180 MB file is
downloaded once into ``data/raw/`` (git-ignored); the small result is committed as
``data/reference/osm_features.geojson`` so builds and CI need no network.

    python -m pomorie.reference.osm             # download if missing, then extract
    python -m pomorie.reference.osm --refresh   # force a fresh download
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import httpx
import osmium
from shapely import prepare
from shapely.geometry import LineString, Point, Polygon, mapping, shape

from pomorie.reference.overpass import ATTRIBUTION, USER_AGENT
from pomorie.reference.paths import BOUNDARY_PATH, FEATURES_PATH, REPO_ROOT

PBF_URL = "https://download.geofabrik.de/europe/bulgaria-latest.osm.pbf"
PBF_PATH = REPO_ROOT / "data" / "raw" / "bulgaria-latest.osm.pbf"

# Areas we measure distance to keep their outline instead of collapsing to a line.
_POLYGON_KINDS = {"school", "beach"}


def classify(tags: dict[str, str], is_node: bool) -> list[str]:
    """Map OSM tags to the feature kinds the pipeline uses (an object can have several)."""
    kinds = []
    name = tags.get("name")
    if is_node and tags.get("place") in {"town", "village", "hamlet"} and name:
        kinds.append("settlement")
    if not is_node and "highway" in tags and name:
        kinds.append("street")
    if tags.get("amenity") in {"school", "kindergarten"}:
        kinds.append("school")
    if tags.get("natural") == "beach":
        kinds.append("beach")
    if name and (
        tags.get("tourism") in {"attraction", "museum", "viewpoint"}
        or "historic" in tags
        or tags.get("amenity") == "place_of_worship"
    ):
        kinds.append("landmark")
    return kinds


def download_pbf(path: Path = PBF_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".part")
    headers = {"User-Agent": USER_AGENT}
    with httpx.stream("GET", PBF_URL, headers=headers, timeout=60, follow_redirects=True) as r:
        r.raise_for_status()
        with partial.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    partial.replace(path)


def _geometry(obj: Any, kinds: list[str]) -> Point | LineString | Polygon | None:
    if obj.is_node():
        return Point(obj.location.lon, obj.location.lat)
    coords = [(n.lon, n.lat) for n in obj.nodes if n.location.valid()]
    if len(coords) < 2:
        return None
    if _POLYGON_KINDS & set(kinds) and len(coords) >= 4 and coords[0] == coords[-1]:
        return Polygon(coords)
    return LineString(coords)


def extract_features(pbf: Path = PBF_PATH) -> dict[str, Any]:
    boundary_fc = json.loads(BOUNDARY_PATH.read_text("utf-8"))
    boundary = shape(boundary_fc["features"][0]["geometry"])
    prepare(boundary)
    min_lon, min_lat, max_lon, max_lat = boundary.bounds

    # Read from memory: libosmium cannot open non-ASCII paths on Windows.
    source = osmium.io.FileBuffer(pbf.read_bytes(), "pbf")
    processor = (
        osmium.FileProcessor(source, osmium.osm.NODE | osmium.osm.WAY)
        .with_locations()  # resolves way node coordinates before filtering
        .with_filter(
            osmium.filter.KeyFilter("place", "highway", "amenity", "natural", "tourism", "historic")
        )
    )

    features: list[dict[str, Any]] = []
    for obj in processor:
        if not isinstance(obj, (osmium.osm.Node, osmium.osm.Way)):
            continue
        tags = dict(obj.tags)
        kinds = classify(tags, obj.is_node())
        if not kinds:
            continue
        geometry = _geometry(obj, kinds)
        if geometry is None:
            continue
        x0, y0, x1, y1 = geometry.bounds
        if x1 < min_lon or x0 > max_lon or y1 < min_lat or y0 > max_lat:
            continue  # cheap bounding-box rejection before the exact test
        if not boundary.intersects(geometry):
            continue
        geojson = json.loads(json.dumps(mapping(geometry)))
        geojson["coordinates"] = _round(geojson["coordinates"])
        for kind in kinds:
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "osm_type": "node" if obj.is_node() else "way",
                        "osm_id": obj.id,
                        "kind": kind,
                        "name": tags.get("name:bg") or tags.get("name"),
                    },
                    "geometry": geojson,
                }
            )

    features.sort(key=lambda f: (f["properties"]["kind"], f["properties"]["osm_id"]))
    return {"type": "FeatureCollection", "attribution": ATTRIBUTION, "features": features}


def _round(coords: Any) -> Any:
    if isinstance(coords[0], (int, float)):
        return [round(coords[0], 6), round(coords[1], 6)]
    return [_round(c) for c in coords]


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract OSM enrichment features.")
    parser.add_argument("--refresh", action="store_true", help="download a fresh extract")
    args = parser.parse_args()

    if args.refresh or not PBF_PATH.exists():
        print(f"downloading {PBF_URL}")
        download_pbf()
    collection = extract_features()
    FEATURES_PATH.write_text(
        json.dumps(collection, ensure_ascii=False, separators=(",", ":")), "utf-8"
    )
    counts: dict[str, int] = {}
    for feature in collection["features"]:
        counts[feature["properties"]["kind"]] = counts.get(feature["properties"]["kind"], 0) + 1
    print(f"{counts} -> {FEATURES_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()

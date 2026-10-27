"""Build the Pomorie municipality boundary from OpenStreetMap.

The boundary is OSM relation 1937060 (admin_level=5). Overpass returns it as a set of
member ways; ``shapely.ops.polygonize`` assembles them into rings, which handles ways in
any order or direction and any islands/holes, unlike stitching endpoints by hand.

Usage:
    python -m pomorie.reference.boundary              # download from Overpass
    python -m pomorie.reference.boundary --input FILE # rebuild from a saved response
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, MultiPolygon, Polygon, mapping
from shapely.ops import polygonize, unary_union

from pomorie.reference import overpass
from pomorie.reference.overpass import ATTRIBUTION
from pomorie.reference.paths import APP_BOUNDARY_PATH, BOUNDARY_PATH, REPO_ROOT

RELATION_ID = 1937060

# ~50 m at Pomorie's latitude; plenty for drawing the boundary in the app.
APP_SIMPLIFY_TOLERANCE_DEG = 0.0005

RAW_PATH = REPO_ROOT / "data" / "raw" / f"overpass_relation_{RELATION_ID}.json"
FULL_PATH = BOUNDARY_PATH
APP_PATH = APP_BOUNDARY_PATH


def fetch_relation(relation_id: int = RELATION_ID) -> dict[str, Any]:
    return overpass.query(f"[out:json][timeout:60];relation({relation_id});out geom;")


def relation_to_polygon(overpass: dict[str, Any], relation_id: int = RELATION_ID) -> MultiPolygon:
    relation = next(
        (e for e in overpass["elements"] if e["type"] == "relation" and e["id"] == relation_id),
        None,
    )
    if relation is None:
        raise ValueError(f"relation {relation_id} not found in Overpass response")

    lines = [
        LineString([(p["lon"], p["lat"]) for p in member["geometry"]])
        for member in relation["members"]
        if member["type"] == "way"
        and member.get("role") in ("outer", "")
        and member.get("geometry")
    ]
    polygons = list(polygonize(unary_union(lines)))
    if not polygons:
        raise ValueError("member ways did not form a closed ring")

    return as_multipolygon(unary_union(polygons))


def as_multipolygon(geometry: Polygon | MultiPolygon) -> MultiPolygon:
    """Always emit one geometry type so consumers (app, PostGIS) don't need to branch."""
    return geometry if isinstance(geometry, MultiPolygon) else MultiPolygon([geometry])


def to_feature_collection(geometry: Polygon | MultiPolygon) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "name": "Община Поморие",
                    "osm_relation_id": RELATION_ID,
                    "attribution": ATTRIBUTION,
                },
                "geometry": mapping(geometry),
            }
        ],
    }


def write_geojson(path: Path, geometry: Polygon | MultiPolygon) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_feature_collection(geometry), ensure_ascii=False), "utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, help="saved Overpass JSON instead of downloading")
    args = parser.parse_args()

    if args.input:
        overpass = json.loads(args.input.read_text("utf-8"))
    else:
        overpass = fetch_relation()
        RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
        RAW_PATH.write_text(json.dumps(overpass), "utf-8")

    boundary = relation_to_polygon(overpass)
    simplified = as_multipolygon(
        boundary.simplify(APP_SIMPLIFY_TOLERANCE_DEG, preserve_topology=True)
    )
    write_geojson(FULL_PATH, boundary)
    write_geojson(APP_PATH, simplified)

    def vertices(g: MultiPolygon) -> int:
        return sum(len(p.exterior.coords) for p in g.geoms)

    print(f"full boundary: {vertices(boundary)} vertices -> {FULL_PATH.relative_to(REPO_ROOT)}")
    print(f"app boundary:  {vertices(simplified)} vertices -> {APP_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()

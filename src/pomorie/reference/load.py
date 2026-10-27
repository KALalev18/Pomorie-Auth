"""Load the committed reference data into the ``ref`` schema (idempotent).

python -m pomorie.reference.load
"""

from __future__ import annotations

import csv
import json

import psycopg

from pomorie.db import connect
from pomorie.reference.paths import BOUNDARY_PATH, FEATURES_PATH, RULES_PATH


def load_reference(conn: psycopg.Connection) -> dict[str, int]:
    """Replace all reference tables in one transaction, so readers never see a partial load."""
    boundary = json.loads(BOUNDARY_PATH.read_text("utf-8"))["features"][0]
    features = json.loads(FEATURES_PATH.read_text("utf-8"))["features"]
    with RULES_PATH.open(encoding="utf-8", newline="") as f:
        rules = list(csv.DictReader(f))

    with conn.transaction():
        conn.execute("TRUNCATE ref.municipality_boundary, ref.osm_features, ref.category_rules")
        conn.execute(
            "INSERT INTO ref.municipality_boundary (name, geom)"
            " VALUES (%s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))",
            [boundary["properties"]["name"], json.dumps(boundary["geometry"])],
        )
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO ref.osm_features (osm_type, osm_id, kind, name, geom)"
                " VALUES (%s, %s, %s, %s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))",
                [
                    (
                        f["properties"]["osm_type"],
                        f["properties"]["osm_id"],
                        f["properties"]["kind"],
                        f["properties"]["name"],
                        json.dumps(f["geometry"]),
                    )
                    for f in features
                ],
            )
            cur.executemany(
                "INSERT INTO ref.category_rules (category, authority, sla_hours, dedup_radius_m,"
                " dedup_window_hours, fine_cents, reward_share_bp, valid_from, valid_to)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    (
                        r["category"],
                        r["authority"],
                        int(r["sla_hours"]),
                        int(r["dedup_radius_m"]),
                        int(r["dedup_window_hours"]),
                        int(r["fine_cents"]) if r["fine_cents"] else None,
                        int(r["reward_share_bp"]),
                        r["valid_from"],
                        r["valid_to"] or None,
                    )
                    for r in rules
                ],
            )
    return {"boundary": 1, "osm_features": len(features), "category_rules": len(rules)}


def main() -> None:
    with connect() as conn:
        print(load_reference(conn))


if __name__ == "__main__":
    main()

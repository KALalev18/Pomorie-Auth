import psycopg
import pytest

from pomorie.reference.load import load_reference
from pomorie.reference.osm import classify


@pytest.mark.parametrize(
    ("tags", "is_node", "expected"),
    [
        ({"place": "village", "name": "Ахелой"}, True, ["settlement"]),
        ({"place": "village", "name": "Ахелой"}, False, []),  # settlements are nodes only
        ({"highway": "residential", "name": "ул. Яница"}, False, ["street"]),
        ({"highway": "residential"}, False, []),  # unnamed roads are useless for enrichment
        ({"amenity": "school"}, False, ["school"]),
        ({"natural": "beach", "name": "Плаж"}, False, ["beach"]),
        ({"historic": "monument", "name": "Паметник"}, True, ["landmark"]),
        (
            {"amenity": "school", "historic": "building", "name": "Старо училище"},
            False,
            ["school", "landmark"],
        ),
    ],
)
def test_classify(tags: dict[str, str], is_node: bool, expected: list[str]) -> None:
    assert classify(tags, is_node) == expected


@pytest.mark.integration
def test_load_reference_is_idempotent(conn: psycopg.Connection) -> None:
    first = load_reference(conn)
    second = load_reference(conn)
    assert first == second
    (count,) = conn.execute("SELECT count(*) FROM ref.osm_features").fetchone() or (0,)
    assert count == first["osm_features"]
    (inside,) = conn.execute(
        "SELECT ST_Covers(geom, ST_SetSRID(ST_MakePoint(27.6167754, 42.5684133), 4326))"
        " FROM ref.municipality_boundary"
    ).fetchone() or (False,)
    assert inside

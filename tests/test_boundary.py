import json
from pathlib import Path
from typing import Any

import pytest
from shapely.geometry import Point, shape

from pomorie.reference.boundary import APP_PATH, FULL_PATH, relation_to_polygon


def _way(*coords: tuple[float, float]) -> dict[str, Any]:
    return {
        "type": "way",
        "role": "outer",
        "geometry": [{"lon": lon, "lat": lat} for lon, lat in coords],
    }


def _overpass(*members: dict[str, Any]) -> dict[str, Any]:
    return {"elements": [{"type": "relation", "id": 1, "members": list(members)}]}


def test_assembles_ring_from_shuffled_and_reversed_ways() -> None:
    # Unit square split into three ways, out of order and with one reversed.
    data = _overpass(
        _way((1, 1), (0, 1), (0, 0)),
        _way((0, 0), (1, 0)),
        _way((1, 1), (1, 0)),  # reversed
    )
    polygon = relation_to_polygon(data, relation_id=1)
    assert polygon.is_valid
    assert polygon.area == pytest.approx(1.0)


def test_rejects_open_ring() -> None:
    data = _overpass(_way((0, 0), (1, 0)), _way((1, 0), (1, 1)))
    with pytest.raises(ValueError, match="closed ring"):
        relation_to_polygon(data, relation_id=1)


def test_rejects_missing_relation() -> None:
    with pytest.raises(ValueError, match="not found"):
        relation_to_polygon({"elements": []}, relation_id=1)


@pytest.mark.parametrize("path", [FULL_PATH, APP_PATH], ids=["full", "app"])
def test_committed_boundary(path: Path) -> None:
    collection = json.loads(path.read_text("utf-8"))
    boundary = shape(collection["features"][0]["geometry"])
    assert boundary.geom_type == "MultiPolygon"
    assert boundary.is_valid
    assert "OpenStreetMap" in collection["features"][0]["properties"]["attribution"]
    # OSM admin_centre node of the relation (Pomorie town).
    assert boundary.contains(Point(27.6167754, 42.5684133))
    # Burgas city centre and open sea are outside.
    assert not boundary.contains(Point(27.4626, 42.5048))
    assert not boundary.contains(Point(27.75, 42.58))

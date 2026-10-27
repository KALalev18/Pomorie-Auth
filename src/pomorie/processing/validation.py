"""Semantic checks: things a JSON Schema cannot express.

The contract says a latitude is a number between -90 and 90; these checks say whether the
report makes sense for Pomorie. Failures go to the dead-letter table with every reason.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from shapely import Geometry, prepare
from shapely.affinity import affine_transform
from shapely.geometry import Point

MAX_CLOCK_SKEW = timedelta(minutes=10)  # phones with a slightly fast clock
MAX_REPORT_AGE = timedelta(days=7)  # older observations are not actionable
MAX_GPS_ACCURACY_M = 250  # worse than this and we cannot tell which street it is


@dataclass(frozen=True)
class Report:
    event_id: str
    reporter_id: str
    category: str
    lat: float
    lon: float
    accuracy_m: float | None
    occurred_at: datetime
    received_at: datetime
    description: str | None
    photo_keys: list[str]
    plate_hash: str | None

    @classmethod
    def from_event(cls, event: dict[str, Any]) -> Report:
        location = event["location"]
        return cls(
            event_id=event["event_id"],
            reporter_id=event["reporter_id"],
            category=event["category"],
            lat=location["lat"],
            lon=location["lon"],
            accuracy_m=location.get("accuracy_m"),
            occurred_at=datetime.fromisoformat(event["occurred_at"]),
            received_at=datetime.fromisoformat(event["received_at"]),
            description=event.get("description"),
            photo_keys=event.get("photo_keys", []),
            plate_hash=event.get("plate_hash"),
        )


class BoundaryCheck:
    """Point-in-municipality test with a tolerance zone.

    The municipality's eastern boundary *is* the coastline, so a resident reporting litter
    at the waterline or on a pier, with normal GPS error, lands a few metres "in the sea".
    The first full run rejected 4.8 % of genuine reports this way. A 100 m zone around the
    boundary accepts them, while bad GPS fixes (kilometres off) are still rejected.

    The buffer is computed in metres on a local equirectangular projection; over a 40 km
    municipality its distortion is far below the 100 m tolerance.
    """

    def __init__(self, boundary: Geometry, tolerance_m: float = 100) -> None:
        lat0 = math.radians(boundary.centroid.y)
        self._kx, self._ky = 111_320 * math.cos(lat0), 110_574.0
        projected = affine_transform(boundary, [self._kx, 0, 0, self._ky, 0, 0])
        self._zone = projected.buffer(tolerance_m)
        prepare(self._zone)

    def covers(self, lat: float, lon: float) -> bool:
        return bool(self._zone.covers(Point(lon * self._kx, lat * self._ky)))


def semantic_errors(report: Report, boundary: BoundaryCheck) -> list[str]:
    errors = []
    if not boundary.covers(report.lat, report.lon):
        errors.append("outside_boundary: location is not inside Pomorie municipality")
    if report.occurred_at > report.received_at + MAX_CLOCK_SKEW:
        errors.append("future_timestamp: occurred_at is after the server received the report")
    if report.received_at - report.occurred_at > MAX_REPORT_AGE:
        errors.append("stale_report: observed more than 7 days before submission")
    if report.accuracy_m is not None and report.accuracy_m > MAX_GPS_ACCURACY_M:
        errors.append(f"low_gps_accuracy: {report.accuracy_m:.0f} m > {MAX_GPS_ACCURACY_M} m")
    return errors

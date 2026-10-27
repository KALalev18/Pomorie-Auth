"""The simulated world: where issues happen, how often, and who reports them.

All numbers are invented but chosen to be plausible for a seaside municipality of about
27 000 residents with a strong summer tourist season. Nothing here describes real people.
"""

from __future__ import annotations

import json
import random
import uuid
from dataclasses import dataclass, field
from functools import cache

from shapely import Geometry, prepare
from shapely.geometry import LineString, Point, shape
from shapely.ops import nearest_points

from pomorie.reference.paths import BOUNDARY_PATH, FEATURES_PATH

# Busier places get more issues. Coordinates are the OSM place nodes.
CENTRES = {
    "Поморие": ((42.5684, 27.6168), 6.0),
    "Ахелой": ((42.6489, 27.6476), 2.5),
    "Каблешково": ((42.6532, 27.5719), 1.5),
}


@dataclass(frozen=True)
class CategoryProfile:
    daily_issues: float  # mean new real issues per day, off-season
    summer_factor: float  # multiplier June-September
    extra_reports: float  # mean additional duplicate reports per issue
    spread_minutes: float  # how long after the first report duplicates keep coming
    hours: tuple[float, ...]  # relative likelihood of each hour of the day (24 values)
    near: str  # "street" or "beach"
    has_plate: bool = False


_DAY = (0, 0, 0, 0, 0, 1, 2, 4, 6, 7, 7, 6, 6, 6, 6, 6, 6, 7, 7, 6, 4, 3, 1, 0.5)
_EVENING = (2, 1, 0.5, 0, 0, 0, 0.5, 1, 2, 3, 4, 4, 4, 4, 4, 5, 6, 7, 8, 8, 7, 6, 4, 3)
_NIGHT = (8, 6, 3, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 3, 5, 8, 9)

PROFILES: dict[str, CategoryProfile] = {
    "illegal_parking": CategoryProfile(9, 2.5, 0.6, 60, _DAY, "street", has_plate=True),
    "littering": CategoryProfile(4, 3.0, 1.2, 600, _EVENING, "beach"),
    "illegal_dumping": CategoryProfile(1, 1.3, 0.8, 2880, _DAY, "street"),
    "broken_infrastructure": CategoryProfile(2, 1.2, 1.5, 7200, _DAY, "street"),
    "street_lighting": CategoryProfile(1, 1.0, 1.0, 2880, _NIGHT, "street"),
    "noise": CategoryProfile(1.5, 3.5, 1.8, 90, _NIGHT, "street"),
    "damaged_greenery": CategoryProfile(0.7, 1.2, 0.4, 4320, _DAY, "street"),
    "abandoned_vehicle": CategoryProfile(0.3, 1.0, 0.5, 10080, _DAY, "street", has_plate=True),
}


@dataclass(frozen=True)
class Reporter:
    reporter_id: uuid.UUID
    activity: float
    abuse: str | None = None  # None, "spammer", "stalker", "teleporter"


@dataclass
class World:
    seed: int
    streets: list[tuple[LineString, float]] = field(default_factory=list)
    beaches: list[LineString] = field(default_factory=list)
    reporters: list[Reporter] = field(default_factory=list)

    def inside(self, lat: float, lon: float) -> bool:
        return bool(_boundary().covers(Point(lon, lat)))

    def point_near(self, rng: random.Random, near: str) -> tuple[float, float]:
        """A random point on a street (weighted by busyness) or on the beach edge."""
        for _ in range(50):
            if near == "beach" and self.beaches:
                line = rng.choice(self.beaches)
            else:
                line = rng.choices([s for s, _ in self.streets], [w for _, w in self.streets])[0]
            p = line.interpolate(rng.random(), normalized=True)
            if self.inside(p.y, p.x):
                return p.y, p.x
        raise RuntimeError("could not sample a point inside the boundary")


@cache
def _boundary() -> Geometry:
    geom = shape(json.loads(BOUNDARY_PATH.read_text("utf-8"))["features"][0]["geometry"])
    prepare(geom)
    return geom


def _busyness(line: LineString) -> float:
    """Street weight: its length, boosted when it is close to a town centre."""
    weight = float(line.length) * 1000
    for (lat, lon), boost in CENTRES.values():
        a, _ = nearest_points(line, Point(lon, lat))
        if abs(a.y - lat) < 0.02 and abs(a.x - lon) < 0.025:  # within ~2 km
            weight *= boost
    return weight


def build_world(seed: int, n_reporters: int = 800, n_abusers: int = 12) -> World:
    rng = random.Random(seed)
    features = json.loads(FEATURES_PATH.read_text("utf-8"))["features"]
    world = World(seed=seed)
    for feature in features:
        geom = shape(feature["geometry"])
        kind = feature["properties"]["kind"]
        if kind == "street" and isinstance(geom, LineString):
            world.streets.append((geom, _busyness(geom)))
        elif kind == "beach" and geom.geom_type == "Polygon":
            world.beaches.append(LineString(geom.exterior.coords))
        elif kind == "beach" and isinstance(geom, LineString):
            world.beaches.append(geom)

    def reporter_id() -> uuid.UUID:
        return uuid.UUID(int=rng.getrandbits(128), version=4)

    # A few residents report a lot, most report rarely (Pareto-like activity).
    world.reporters = [Reporter(reporter_id(), rng.paretovariate(1.3)) for _ in range(n_reporters)]
    kinds = ["spammer", "stalker", "teleporter"]
    world.reporters += [
        Reporter(reporter_id(), 0.0, abuse=kinds[i % len(kinds)]) for i in range(n_abusers)
    ]
    return world

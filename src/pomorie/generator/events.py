"""Generate one day of report events with ground-truth labels.

Deterministic: the same (seed, day) always yields the same events, so a Dagster backfill
of a day reproduces exactly the data it produced the first time.

    python -m pomorie.generator.events --start 2026-06-01 --days 30
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import random
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pomorie.generator.world import PROFILES, Reporter, World, build_world
from pomorie.privacy import plate_hash

# Rates of deliberately broken input, so the dead-letter paths get exercised.
P_BAD_GPS = 0.02
P_STALE = 0.005
P_MALFORMED = 0.005
P_GARBAGE = 0.001

_PLATE_LETTERS = "ABEKMHOPCTYX"
_SEA = (42.62, 27.75)  # Black Sea, east of the coast


@dataclass(frozen=True)
class Generated:
    category: str  # Kafka key
    value: bytes
    event_id: str | None
    true_issue_id: str | None
    scenario: str
    is_abusive: bool


def _poisson(rng: random.Random, mean: float) -> int:
    # Knuth's method; means here are small.
    limit, k, p = math.exp(-mean), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _uuid(rng: random.Random) -> str:
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def _plate(rng: random.Random) -> str:
    letters = "".join(rng.choice(_PLATE_LETTERS) for _ in range(2))
    return f"A {rng.randint(1000, 9999)} {letters}"  # "A" = Burgas province prefix


def _jitter(rng: random.Random, lat: float, lon: float, metres: float) -> tuple[float, float]:
    dlat = rng.gauss(0, metres) / 111_320
    dlon = rng.gauss(0, metres) / (111_320 * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon


def _event(
    rng: random.Random,
    reporter: Reporter,
    category: str,
    lat: float,
    lon: float,
    accuracy: float,
    at: datetime,
    plate: str | None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "schema": "report.submitted/1",
        "event_id": _uuid(rng),
        "occurred_at": (at - timedelta(minutes=rng.uniform(0, 20))).isoformat(),
        "received_at": at.isoformat(),
        "reporter_id": str(reporter.reporter_id),
        "category": category,
        "location": {"lat": round(lat, 7), "lon": round(lon, 7), "accuracy_m": round(accuracy, 1)},
        "client": {"platform": "generator", "app_version": "sim-1"},
    }
    if plate and (hashed := plate_hash(plate)):
        event["plate_hash"] = hashed
    return event


def _hour(rng: random.Random, hours: tuple[float, ...]) -> int:
    return rng.choices(range(24), hours)[0]


def generate_day(world: World, day: date) -> list[Generated]:
    rng = random.Random(f"{world.seed}:{day.isoformat()}")
    midnight = datetime(day.year, day.month, day.day, tzinfo=UTC)
    summer = day.month in (6, 7, 8, 9)
    normal = [r for r in world.reporters if r.abuse is None]
    weights = [r.activity for r in normal]
    out: list[tuple[datetime, Generated]] = []

    def emit(event: dict[str, Any], issue: str | None, scenario: str, abusive: bool) -> None:
        at = datetime.fromisoformat(event["received_at"])
        value = json.dumps(event).encode()
        out.append(
            (at, Generated(event["category"], value, event["event_id"], issue, scenario, abusive))
        )

    # Real issues, each reported by one or more different residents.
    for category, profile in PROFILES.items():
        mean = profile.daily_issues * (profile.summer_factor if summer else 1.0)
        for _ in range(_poisson(rng, mean)):
            issue_id = _uuid(rng)
            lat, lon = world.point_near(rng, profile.near)
            plate = _plate(rng) if profile.has_plate else None
            start = midnight + timedelta(
                hours=_hour(rng, profile.hours), minutes=rng.uniform(0, 60)
            )
            n_reports = 1 + _poisson(rng, profile.extra_reports)
            reporters = (
                rng.sample(normal, k=min(n_reports, len(normal)))
                if n_reports > 1
                else rng.choices(normal, weights)
            )
            for i, reporter in enumerate(reporters):
                at = (
                    start
                    if i == 0
                    else start + timedelta(minutes=rng.uniform(1, profile.spread_minutes))
                )
                accuracy = min(rng.lognormvariate(math.log(9), 0.5), 60)
                r_lat, r_lon = _jitter(rng, lat, lon, accuracy * 0.7)
                emit(
                    _event(rng, reporter, category, r_lat, r_lon, accuracy, at, plate),
                    issue_id,
                    "normal" if i == 0 else "duplicate",
                    False,
                )

    # Abusive reporters.
    for reporter in (r for r in world.reporters if r.abuse):
        if reporter.abuse == "spammer" and rng.random() < 0.12:
            start = midnight + timedelta(hours=rng.uniform(8, 22))
            for i in range(rng.randint(7, 12)):
                lat, lon = world.point_near(rng, "street")
                category = rng.choice(list(PROFILES))
                event = _event(
                    rng, reporter, category, lat, lon, 15, start + timedelta(seconds=40 * i), None
                )
                emit(event, _uuid(rng), "spam", True)
        elif reporter.abuse == "stalker" and rng.random() < 0.4:
            # Always the same plate, always near the same street: a neighbour dispute.
            local = random.Random(f"{world.seed}:{reporter.reporter_id}")
            plate = _plate(local)
            lat, lon = world.point_near(local, "street")
            at = midnight + timedelta(hours=rng.uniform(7, 20))
            event = _event(
                rng, reporter, "illegal_parking", *_jitter(rng, lat, lon, 10), 8, at, plate
            )
            emit(event, _uuid(rng), "repeat_target", True)
        elif reporter.abuse == "teleporter" and rng.random() < 0.15:
            at = midnight + timedelta(hours=rng.uniform(8, 20))
            for i in range(3):
                lat, lon = world.point_near(rng, "street")
                event = _event(
                    rng,
                    reporter,
                    rng.choice(list(PROFILES)),
                    lat,
                    lon,
                    10,
                    at + timedelta(minutes=2 * i),
                    None,
                )
                emit(event, _uuid(rng), "impossible_travel", True)

    # Damage a small share of events the way real clients do.
    damaged: list[tuple[datetime, Generated]] = []
    for at, g in out:
        roll = rng.random()
        event = json.loads(g.value)
        if roll < P_BAD_GPS:
            if rng.random() < 0.5:
                event["location"].update(
                    lat=_SEA[0] + rng.uniform(-0.05, 0.05), lon=_SEA[1], accuracy_m=30
                )
            else:
                event["location"]["accuracy_m"] = rng.uniform(400, 3000)
            damaged.append((at, _replace(g, event, "bad_gps")))
        elif roll < P_BAD_GPS + P_STALE:
            event["occurred_at"] = (at - timedelta(days=rng.uniform(8, 30))).isoformat()
            damaged.append((at, _replace(g, event, "stale")))
        elif roll < P_BAD_GPS + P_STALE + P_MALFORMED:
            broken = copy.deepcopy(event)
            broken.pop(rng.choice(["reporter_id", "location", "category"]))
            damaged.append(
                (
                    at,
                    Generated(
                        g.category, json.dumps(broken).encode(), None, None, "malformed", False
                    ),
                )
            )
        elif roll < P_BAD_GPS + P_STALE + P_MALFORMED + P_GARBAGE:
            damaged.append(
                (at, Generated(g.category, b"\x00\xffnot json", None, None, "garbage", False))
            )
        else:
            damaged.append((at, g))

    damaged.sort(key=lambda pair: pair[0])
    return [g for _, g in damaged]


def _replace(g: Generated, event: dict[str, Any], scenario: str) -> Generated:
    return Generated(
        g.category, json.dumps(event).encode(), g.event_id, g.true_issue_id, scenario, g.is_abusive
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Print a summary of generated days.")
    parser.add_argument("--start", type=date.fromisoformat, default=date(2026, 7, 1))
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    world = build_world(args.seed)
    for offset in range(args.days):
        day = args.start + timedelta(days=offset)
        events = generate_day(world, day)
        scenarios: dict[str, int] = {}
        for g in events:
            scenarios[g.scenario] = scenarios.get(g.scenario, 0) + 1
        print(day, len(events), scenarios)


if __name__ == "__main__":
    main()

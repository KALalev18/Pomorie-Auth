import uuid
from datetime import UTC, datetime, timedelta

from shapely.geometry import box

from pomorie.processing.dedup import Candidate, choose_case
from pomorie.processing.fraud import haversine_km, is_impossible_travel
from pomorie.processing.ledger import reward_cents
from pomorie.processing.validation import BoundaryCheck, Report, semantic_errors

T0 = datetime(2026, 7, 14, 9, 0, tzinfo=UTC)
SQUARE = BoundaryCheck(box(27.5, 42.5, 27.7, 42.7))


def make_report(**overrides: object) -> Report:
    values: dict[str, object] = {
        "event_id": str(uuid.uuid4()),
        "reporter_id": str(uuid.uuid4()),
        "category": "littering",
        "lat": 42.6,
        "lon": 27.6,
        "accuracy_m": 10.0,
        "occurred_at": T0,
        "received_at": T0,
        "description": None,
        "photo_keys": [],
        "plate_hash": None,
    }
    values.update(overrides)
    return Report(**values)  # type: ignore[arg-type]


def test_valid_report_has_no_semantic_errors() -> None:
    assert semantic_errors(make_report(), SQUARE) == []


def test_every_semantic_problem_is_reported() -> None:
    report = make_report(
        lat=0.0,
        lon=0.0,
        accuracy_m=900.0,
        occurred_at=T0 + timedelta(hours=1),
    )
    reasons = [e.split(":")[0] for e in semantic_errors(report, SQUARE)]
    assert reasons == ["outside_boundary", "future_timestamp", "low_gps_accuracy"]


def test_stale_report() -> None:
    report = make_report(occurred_at=T0 - timedelta(days=8))
    assert semantic_errors(report, SQUARE)[0].startswith("stale_report")


def _candidate(distance_m: float, last_h_ago: float, first_h_ago: float = 1) -> Candidate:
    return Candidate(
        case_id=uuid.uuid4(),
        distance_m=distance_m,
        first_reported_at=T0 - timedelta(hours=first_h_ago),
        last_reported_at=T0 - timedelta(hours=last_h_ago),
    )


def test_dedup_picks_nearest_active_case() -> None:
    near, far = _candidate(5, 1), _candidate(40, 1)
    assert choose_case([far, near], T0, radius_m=50, window=timedelta(hours=3)) == near.case_id


def test_dedup_ignores_cases_outside_radius_or_window() -> None:
    window = timedelta(hours=3)
    assert choose_case([_candidate(60, 1)], T0, 50, window) is None
    assert choose_case([_candidate(5, 4)], T0, 50, window) is None


def test_dedup_caps_case_span_so_hotspots_do_not_merge_forever() -> None:
    # Reported every hour for 13 hours: last report is recent, but the case is too old.
    long_running = _candidate(5, last_h_ago=1, first_h_ago=13)
    assert choose_case([long_running], T0, 50, timedelta(hours=3)) is None


def test_haversine_matches_postgis_geodesic_distance() -> None:
    # PostGIS ST_Distance(geography) on the WGS84 ellipsoid gives 15.468 km for these points;
    # a sphere is within 0.5 % of that at this latitude.
    assert abs(haversine_km(42.5567, 27.6373, 42.5048, 27.4626) - 15.468) < 15.468 * 0.005


def test_impossible_travel() -> None:
    pomorie, kableshkovo = (42.568, 27.617), (42.603, 27.539)  # ~7.5 km apart
    prev = (*pomorie, T0)
    assert is_impossible_travel(prev, *kableshkovo, T0 + timedelta(minutes=2))
    assert not is_impossible_travel(prev, *kableshkovo, T0 + timedelta(minutes=30))
    assert not is_impossible_travel(prev, 42.5681, 27.6171, T0 + timedelta(seconds=10))  # jitter


def test_reward_rounds_down_to_whole_cents() -> None:
    assert reward_cents(7500, 1500) == 1125
    assert reward_cents(999, 1500) == 149
    assert reward_cents(5000, 0) == 0

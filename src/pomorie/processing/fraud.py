"""Abuse checks run on every report before it can earn a reward.

A flag never rejects a report: the issue may still be real. It marks the case for manual
review, and no reward is accrued until a reviewer approves it.

- burst:              many reports from one reporter in a short time (spam, scripted abuse)
- impossible_travel:  two reports further apart than anyone could travel in the time between
- repeat_target:      the same reporter reports the same licence plate again and again
                      (a neighbour dispute, or harassment, rather than civic reporting)
- low_reputation:     most of the reporter's earlier cases were rejected by the authority
"""

from __future__ import annotations

import math
from datetime import datetime

import psycopg

from pomorie.processing.validation import Report

BURST_WINDOW_MIN = 10
BURST_MAX_REPORTS = 5  # the 6th report within 10 minutes is flagged
MAX_SPEED_KMH = 130  # faster than driving on the roads around Pomorie
MIN_TRAVEL_KM = 2  # ignore GPS jitter between nearby reports
REPEAT_TARGET_DAYS = 30
REPEAT_TARGET_MAX = 3  # the 4th report on one plate within 30 days is flagged
REPUTATION_MIN_CASES = 4
REPUTATION_MAX_REJECTED = 0.5


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def is_impossible_travel(
    prev: tuple[float, float, datetime], lat: float, lon: float, at: datetime
) -> bool:
    distance_km = haversine_km(prev[0], prev[1], lat, lon)
    if distance_km < MIN_TRAVEL_KM:
        return False
    hours = abs((at - prev[2]).total_seconds()) / 3600
    return hours == 0 or distance_km / hours > MAX_SPEED_KMH


HISTORY_SQL = """
WITH history AS (
    SELECT received_at, plate_hash, geom, case_id
    FROM ops.reports
    WHERE reporter_id = %(reporter)s AND received_at <= %(at)s
)
SELECT
    (SELECT count(*) FROM history
      WHERE received_at > %(at)s - make_interval(mins => %(burst)s)),
    (SELECT count(*) FROM history
      WHERE plate_hash = %(plate)s AND received_at > %(at)s - make_interval(days => %(days)s)),
    prev.lat, prev.lon, prev.received_at,
    reputation.total, reputation.rejected
FROM
    (SELECT 1) AS one
    LEFT JOIN LATERAL (
        SELECT ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon, received_at
        FROM history ORDER BY received_at DESC LIMIT 1
    ) AS prev ON true
    CROSS JOIN LATERAL (
        -- Primary-key lookups for this reporter's cases only, not a scan of all cases.
        SELECT count(*) AS total, count(*) FILTER (WHERE status = 'rejected') AS rejected
        FROM ops.cases WHERE case_id IN (SELECT case_id FROM history)
    ) AS reputation
"""


def fraud_flags(conn: psycopg.Connection, report: Report) -> list[str]:
    """All four checks from one query over the reporter's history (one round trip)."""
    row = conn.execute(
        HISTORY_SQL,
        {
            "reporter": report.reporter_id,
            "at": report.received_at,
            "burst": BURST_WINDOW_MIN,
            "plate": report.plate_hash,
            "days": REPEAT_TARGET_DAYS,
        },
    ).fetchone()
    recent, same_plate, prev_lat, prev_lon, prev_at, total, rejected = row or (0,) * 7

    flags = []
    if recent >= BURST_MAX_REPORTS:
        flags.append("burst")
    if report.plate_hash and same_plate >= REPEAT_TARGET_MAX:
        flags.append("repeat_target")
    if prev_at is not None and is_impossible_travel(
        (prev_lat, prev_lon, prev_at), report.lat, report.lon, report.received_at
    ):
        flags.append("impossible_travel")
    if total >= REPUTATION_MIN_CASES and rejected / total > REPUTATION_MAX_REJECTED:
        flags.append("low_reputation")
    return flags


HOLD_RELATED_SQL = """
WITH related AS (
    SELECT report_id, case_id, %(flag)s::text AS flag
    FROM ops.reports
    WHERE reporter_id = %(reporter)s
      AND received_at <= %(at)s
      AND (
        (%(flag)s = 'burst' AND received_at > %(at)s - make_interval(mins => %(burst)s))
        OR (%(flag)s = 'repeat_target' AND plate_hash = %(plate)s
            AND received_at > %(at)s - make_interval(days => %(days)s))
        OR (%(flag)s = 'impossible_travel' AND received_at = (
            SELECT max(received_at) FROM ops.reports
            WHERE reporter_id = %(reporter)s AND received_at < %(at)s))
      )
),
flag_reports AS (
    UPDATE ops.reports r
    SET fraud_flags = ARRAY(SELECT DISTINCT unnest(r.fraud_flags || ARRAY[related.flag]))
    FROM related WHERE r.report_id = related.report_id
)
UPDATE ops.cases c
SET needs_review = true,
    review_reasons = ARRAY(SELECT DISTINCT unnest(c.review_reasons || ARRAY[%(flag)s::text])),
    updated_at = now()
FROM related
WHERE c.case_id = related.case_id AND c.review_decision IS NULL
"""


def hold_related(conn: psycopg.Connection, report: Report, flags: list[str]) -> None:
    """Once a pattern is visible, hold the earlier reports that formed it as well.

    Detection lags: a burst is only recognisable at its sixth report. Rewards are accrued
    when a fine is paid, typically days later, so flagging the earlier reports now still
    stops their payout. Low reputation is about the reporter, not specific reports.
    """
    for flag in flags:
        if flag == "low_reputation":
            continue
        conn.execute(
            HOLD_RELATED_SQL,
            {
                "flag": flag,
                "reporter": report.reporter_id,
                "at": report.received_at,
                "burst": BURST_WINDOW_MIN,
                "plate": report.plate_hash,
                "days": REPEAT_TARGET_DAYS,
            },
        )

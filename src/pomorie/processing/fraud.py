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


def fraud_flags(conn: psycopg.Connection, report: Report) -> list[str]:
    flags = []
    row = conn.execute(
        """
        SELECT
            count(*) FILTER (WHERE received_at > %(at)s - make_interval(mins => %(burst)s)),
            count(*) FILTER (
                WHERE plate_hash = %(plate)s
                  AND received_at > %(at)s - make_interval(days => %(days)s))
        FROM ops.reports
        WHERE reporter_id = %(reporter)s AND received_at <= %(at)s
        """,
        {
            "reporter": report.reporter_id,
            "at": report.received_at,
            "burst": BURST_WINDOW_MIN,
            "plate": report.plate_hash,
            "days": REPEAT_TARGET_DAYS,
        },
    ).fetchone()
    recent, same_plate = row or (0, 0)
    if recent >= BURST_MAX_REPORTS:
        flags.append("burst")
    if report.plate_hash and same_plate >= REPEAT_TARGET_MAX:
        flags.append("repeat_target")

    prev = conn.execute(
        "SELECT ST_Y(geom::geometry), ST_X(geom::geometry), received_at FROM ops.reports"
        " WHERE reporter_id = %s AND received_at <= %s ORDER BY received_at DESC LIMIT 1",
        [report.reporter_id, report.received_at],
    ).fetchone()
    if prev and is_impossible_travel(prev, report.lat, report.lon, report.received_at):
        flags.append("impossible_travel")

    total, rejected = conn.execute(
        "SELECT count(DISTINCT c.case_id),"
        " count(DISTINCT c.case_id) FILTER (WHERE c.status = 'rejected')"
        " FROM ops.reports r JOIN ops.cases c USING (case_id) WHERE r.reporter_id = %s",
        [report.reporter_id],
    ).fetchone() or (0, 0)
    if total >= REPUTATION_MIN_CASES and rejected / total > REPUTATION_MAX_REJECTED:
        flags.append("low_reputation")
    return flags

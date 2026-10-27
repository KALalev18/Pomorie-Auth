"""Turn one valid report event into operational state: route, deduplicate, enrich, flag."""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import psycopg

from pomorie.processing.dedup import MAX_SPAN_WINDOWS, Candidate, choose_case
from pomorie.processing.fraud import fraud_flags, hold_related
from pomorie.processing.validation import Report

CASE_NAMESPACE = uuid.UUID("3f6e2a1c-8d4b-4c7e-9a2f-6b1d0e5c7a93")
ENRICH_SQL = (Path(__file__).parent / "sql" / "enrich_report.sql").read_text("utf-8")


@dataclass(frozen=True)
class Rule:
    authority: str
    sla_hours: int
    dedup_radius_m: int
    dedup_window_hours: int


@dataclass(frozen=True)
class Result:
    case_id: uuid.UUID
    is_duplicate: bool
    flags: list[str]


class MissingRule(LookupError):
    pass


class RuleBook:
    """All category rule versions, held in memory and refreshed every ``ttl_s`` seconds.

    The table is tiny and changes rarely; reading it once per minute instead of once per
    report saves a database round trip on the hot path.
    """

    def __init__(self, conn: psycopg.Connection, ttl_s: float = 60) -> None:
        self._conn, self._ttl_s = conn, ttl_s
        self._loaded_at = -math.inf
        self._rules: list[tuple[str, datetime, datetime | None, Rule]] = []

    def at(self, category: str, when: datetime) -> Rule:
        """The rule valid at ``when`` (type-2 lookup: valid_from <= when < valid_to)."""
        if time.monotonic() - self._loaded_at > self._ttl_s:
            rows = self._conn.execute(
                "SELECT category, valid_from, valid_to, authority, sla_hours, dedup_radius_m,"
                " dedup_window_hours FROM ref.category_rules"
            ).fetchall()
            self._rules = [(c, f, t, Rule(*rest)) for c, f, t, *rest in rows]
            self._loaded_at = time.monotonic()
        for rule_category, valid_from, valid_to, rule in self._rules:
            if (
                rule_category == category
                and valid_from <= when
                and (valid_to is None or when < valid_to)
            ):
                return rule
        raise MissingRule(f"no rule for {category} at {when.isoformat()}")


def find_candidates(conn: psycopg.Connection, report: Report, rule: Rule) -> list[Candidate]:
    window = timedelta(hours=rule.dedup_window_hours)
    rows = conn.execute(
        """
        SELECT case_id, ST_Distance(centroid, p.g), first_reported_at, last_reported_at
        FROM ops.cases,
             (SELECT ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography AS g) p
        WHERE category = %(category)s
          AND status = 'routed'
          AND last_reported_at >= %(at)s - %(window)s
          AND first_reported_at >= %(at)s - %(span)s
          AND ST_DWithin(centroid, p.g, %(radius)s)
        """,
        {
            "lon": report.lon,
            "lat": report.lat,
            "category": report.category,
            "at": report.received_at,
            "window": window,
            "span": window * MAX_SPAN_WINDOWS,
            "radius": rule.dedup_radius_m,
        },
    ).fetchall()
    return [Candidate(*row) for row in rows]


def process_report(conn: psycopg.Connection, report: Report, rule: Rule) -> Result:
    """Must run inside the caller's transaction, together with the raw insert."""
    flags = fraud_flags(conn, report)
    case_id = choose_case(
        find_candidates(conn, report, rule),
        report.received_at,
        rule.dedup_radius_m,
        timedelta(hours=rule.dedup_window_hours),
    )
    is_duplicate = case_id is not None

    if case_id is None:
        # Derived from the report that opened it, so replaying history yields the same ids.
        case_id = uuid.uuid5(CASE_NAMESPACE, report.event_id)
        conn.execute(
            """
            INSERT INTO ops.cases (case_id, category, authority, status, centroid,
                first_reported_at, last_reported_at, routed_at, sla_due_at,
                needs_review, review_reasons)
            VALUES (%(case_id)s, %(category)s, %(authority)s, 'routed',
                ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography,
                %(at)s, %(at)s, %(at)s, %(at)s + make_interval(hours => %(sla)s),
                %(review)s, %(flags)s)
            """,
            {
                "case_id": case_id,
                "category": report.category,
                "authority": rule.authority,
                "lon": report.lon,
                "lat": report.lat,
                "at": report.received_at,
                "sla": rule.sla_hours,
                "review": bool(flags),
                "flags": flags,
            },
        )
        conn.execute(
            "INSERT INTO ops.case_status_history VALUES (%s, 'routed', %s, 'processor')",
            [case_id, report.received_at],
        )
    else:
        # Running mean of report positions: fine at the tens-of-metres scale of a case.
        conn.execute(
            """
            UPDATE ops.cases SET
                centroid = ST_SetSRID(ST_MakePoint(
                    (ST_X(centroid::geometry) * report_count + %(lon)s) / (report_count + 1),
                    (ST_Y(centroid::geometry) * report_count + %(lat)s) / (report_count + 1)),
                    4326)::geography,
                report_count = report_count + 1,
                last_reported_at = greatest(last_reported_at, %(at)s),
                needs_review = needs_review OR %(review)s,
                review_reasons = ARRAY(SELECT DISTINCT unnest(review_reasons || %(flags)s::text[])),
                updated_at = now()
            WHERE case_id = %(case_id)s
            """,
            {
                "lon": report.lon,
                "lat": report.lat,
                "at": report.received_at,
                "review": bool(flags),
                "flags": flags,
                "case_id": case_id,
            },
        )

    settlement, street, landmark, dist_school, dist_beach = (
        conn.execute(ENRICH_SQL, {"lon": report.lon, "lat": report.lat}).fetchone() or (None,) * 5
    )
    conn.execute(
        """
        INSERT INTO ops.reports (report_id, case_id, reporter_id, category, geom, accuracy_m,
            occurred_at, received_at, description, photo_keys, plate_hash, settlement, street,
            nearest_landmark, dist_school_m, dist_beach_m, is_duplicate, fraud_flags)
        VALUES (%s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        [
            report.event_id,
            case_id,
            report.reporter_id,
            report.category,
            report.lon,
            report.lat,
            report.accuracy_m,
            report.occurred_at,
            report.received_at,
            report.description,
            report.photo_keys,
            report.plate_hash,
            settlement,
            street,
            landmark,
            dist_school,
            dist_beach,
            is_duplicate,
            flags,
        ],
    )
    hold_related(conn, report, flags)
    return Result(case_id, is_duplicate, flags)

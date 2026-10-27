"""Turn one valid report event into operational state: route, deduplicate, enrich, flag."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import psycopg

from pomorie.processing.dedup import MAX_SPAN_WINDOWS, Candidate, choose_case
from pomorie.processing.fraud import fraud_flags
from pomorie.processing.validation import Report

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


def rule_at(conn: psycopg.Connection, report: Report) -> Rule:
    """The category rule valid when the report was received (type-2 lookup)."""
    row = conn.execute(
        "SELECT authority, sla_hours, dedup_radius_m, dedup_window_hours FROM ref.category_rules"
        " WHERE category = %s AND tstzrange(valid_from, valid_to) @> %s::timestamptz",
        [report.category, report.received_at],
    ).fetchone()
    if row is None:
        raise MissingRule(f"no rule for {report.category} at {report.received_at.isoformat()}")
    return Rule(*row)


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


def process_report(conn: psycopg.Connection, report: Report) -> Result:
    """Must run inside the caller's transaction, together with the raw insert."""
    rule = rule_at(conn, report)
    flags = fraud_flags(conn, report)
    case_id = choose_case(
        find_candidates(conn, report, rule),
        report.received_at,
        rule.dedup_radius_m,
        timedelta(hours=rule.dedup_window_hours),
    )
    is_duplicate = case_id is not None

    if case_id is None:
        case_id = uuid.uuid4()
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
    return Result(case_id, is_duplicate, flags)

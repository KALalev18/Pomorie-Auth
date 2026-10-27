"""Erasure requests and retention periods (GDPR Articles 5(1)(e) and 17).

Erasure, per request, in one transaction:

  identity.reporters   name and e-mail removed, erased_at set
  ops.reports          free-text description and photo references removed
  object storage       the photos themselves deleted
  raw.report_events    description and photo keys removed from the stored payload
  raw.dead_letter      rejected events from this reporter deleted (they hold raw payloads)
  warehouse            rebuilt from these tables by dbt, so the change reaches every mart
  Kafka                topics keep events for 7 days only, then they expire

Kept: reports' category, place and time (needed to run the city's cases; without the
identity they no longer point to a person), and the reward ledger, which is a financial
record the municipality must keep (Art. 17(3)(b)); it references a pseudonymous id only.

Retention (scheduled daily):

  photos                    deleted 90 days after the case is closed
  descriptions              removed 365 days after the report
  licence-plate hashes      removed after 180 days (fraud checks look back 30 days)
  dead-letter rows          deleted after 30 days
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

import psycopg

from pomorie import photos

PHOTO_RETENTION_DAYS = 90
DESCRIPTION_RETENTION_DAYS = 365
PLATE_RETENTION_DAYS = 180
DEAD_LETTER_RETENTION_DAYS = 30

DeletePhotos = Callable[[list[str]], int]


def erase_reporter(
    conn: psycopg.Connection, reporter_id: uuid.UUID, delete_photos: DeletePhotos | None = None
) -> dict[str, int]:
    delete = delete_photos or photos.delete_photos
    rows = conn.execute(
        "SELECT report_id, photo_keys FROM ops.reports WHERE reporter_id = %s", [reporter_id]
    ).fetchall()
    keys = [k for _, report_keys in rows for k in report_keys]

    summary = {"reports": len(rows), "photos": delete(keys)}
    summary["descriptions"] = conn.execute(
        "UPDATE ops.reports SET description = NULL, photo_keys = '{}'"
        " WHERE reporter_id = %s AND (description IS NOT NULL OR photo_keys <> '{}')",
        [reporter_id],
    ).rowcount
    summary["raw_events"] = conn.execute(
        "UPDATE raw.report_events SET payload = payload - 'description' - 'photo_keys'"
        " WHERE payload ->> 'reporter_id' = %s"
        " AND (payload ? 'description' OR payload ? 'photo_keys')",
        [str(reporter_id)],
    ).rowcount
    summary["dead_letters"] = conn.execute(
        "DELETE FROM raw.dead_letter WHERE position(%s::bytea IN payload) > 0",
        [str(reporter_id).encode()],
    ).rowcount
    summary["identity"] = conn.execute(
        "UPDATE identity.reporters SET display_name = NULL, email = NULL, erased_at = now()"
        " WHERE reporter_id = %s AND erased_at IS NULL",
        [reporter_id],
    ).rowcount
    return summary


def process_erasure_requests(
    conn: psycopg.Connection, delete_photos: DeletePhotos | None = None
) -> int:
    """Handle every open request; each is committed with its audit summary."""
    pending = conn.execute(
        "SELECT request_id, reporter_id FROM identity.erasure_requests"
        " WHERE completed_at IS NULL ORDER BY requested_at"
    ).fetchall()
    for request_id, reporter_id in pending:
        with conn.transaction():
            summary = erase_reporter(conn, reporter_id, delete_photos)
            conn.execute(
                "UPDATE identity.erasure_requests SET completed_at = now(), summary = %s"
                " WHERE request_id = %s",
                [json.dumps(summary), request_id],
            )
    return len(pending)


def apply_retention(
    conn: psycopg.Connection, now: datetime, delete_photos: DeletePhotos | None = None
) -> dict[str, Any]:
    delete = delete_photos or photos.delete_photos
    with conn.transaction():
        expired = conn.execute(
            "SELECT r.report_id, r.photo_keys FROM ops.reports r JOIN ops.cases c USING (case_id)"
            " WHERE r.photo_keys <> '{}' AND c.closed_at < %s - make_interval(days => %s)",
            [now, PHOTO_RETENTION_DAYS],
        ).fetchall()
        photo_count = delete([k for _, keys in expired for k in keys])
        conn.execute(
            "UPDATE ops.reports SET photo_keys = '{}' WHERE report_id = ANY(%s)",
            [[report_id for report_id, _ in expired]],
        )
        descriptions = conn.execute(
            "UPDATE ops.reports SET description = NULL"
            " WHERE description IS NOT NULL AND received_at < %s - make_interval(days => %s)",
            [now, DESCRIPTION_RETENTION_DAYS],
        ).rowcount
        plates = conn.execute(
            "UPDATE ops.reports SET plate_hash = NULL"
            " WHERE plate_hash IS NOT NULL AND received_at < %s - make_interval(days => %s)",
            [now, PLATE_RETENTION_DAYS],
        ).rowcount
        dead_letters = conn.execute(
            "DELETE FROM raw.dead_letter WHERE created_at < %s - make_interval(days => %s)",
            [now, DEAD_LETTER_RETENTION_DAYS],
        ).rowcount
    return {
        "photos": photo_count,
        "descriptions": descriptions,
        "plate_hashes": plates,
        "dead_letters": dead_letters,
    }

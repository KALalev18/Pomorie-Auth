"""Apply authority decisions (simulated) to cases and fines."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import psycopg

from pomorie.processing.ledger import accrue_reward

# Which outcome may follow which case status. Anything else is a semantic error.
ALLOWED = {
    "rejected": {"routed"},
    "resolved": {"routed"},
    "fine_issued": {"routed"},
    "fine_paid": {"fined"},
}
NEW_STATUS = {
    "rejected": "rejected",
    "resolved": "resolved",
    "fine_issued": "fined",
    "fine_paid": "paid",
}


class InvalidOutcome(ValueError):
    pass


def process_outcome(conn: psycopg.Connection, event: dict[str, Any]) -> None:
    case_id = uuid.UUID(event["case_id"])
    outcome = event["outcome"]
    at = datetime.fromisoformat(event["occurred_at"])

    row = conn.execute(
        "SELECT status, authority FROM ops.cases WHERE case_id = %s FOR UPDATE", [case_id]
    ).fetchone()
    if row is None:
        raise InvalidOutcome(f"unknown_case: {case_id}")
    status, authority = row
    if authority != event["authority"]:
        raise InvalidOutcome(f"wrong_authority: case is routed to {authority}")
    if status not in ALLOWED[outcome]:
        raise InvalidOutcome(f"invalid_transition: {outcome} on a case that is {status}")

    if outcome == "fine_issued":
        conn.execute(
            "INSERT INTO ops.fines (fine_id, case_id, authority, amount_cents, currency, issued_at)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            [event["fine_id"], case_id, authority, event["amount_cents"], event["currency"], at],
        )
    elif outcome == "fine_paid":
        paid = conn.execute(
            "UPDATE ops.fines SET paid_at = %s"
            " WHERE fine_id = %s AND case_id = %s AND amount_cents = %s AND paid_at IS NULL",
            [at, event["fine_id"], case_id, event["amount_cents"]],
        ).rowcount
        if not paid:
            raise InvalidOutcome("fine_mismatch: no unpaid fine with this id and amount")

    closes = outcome in {"rejected", "resolved", "fine_paid"}
    conn.execute(
        "UPDATE ops.cases SET status = %s, closed_at = CASE WHEN %s THEN %s ELSE closed_at END,"
        " updated_at = now() WHERE case_id = %s",
        [NEW_STATUS[outcome], closes, at, case_id],
    )
    conn.execute(
        "INSERT INTO ops.case_status_history VALUES (%s, %s, %s, 'authority')"
        " ON CONFLICT DO NOTHING",
        [case_id, NEW_STATUS[outcome], at],
    )
    if outcome == "fine_paid":
        accrue_reward(conn, uuid.UUID(event["fine_id"]))

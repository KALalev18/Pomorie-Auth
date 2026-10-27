"""Reward postings in the double-entry ledger (simulated; no real money moves).

Reward accrual, when a fine is paid:      reward_expense  +R   /  payable:<reporter>  -R
Payout batch, later:                      payable:<reporter> +B  /  payout_cash  -B

R = floor(fine × reward_share_bp / 10 000), using the category rule that was valid when the
case was first reported, so a later rule change never alters an earlier promise. The reward
goes to the first reporter of the case whose report was not flagged, unless a reviewer
approved the case, in which case the first reporter overall.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import psycopg

ELIGIBLE_FINE_SQL = """
SELECT f.amount_cents, r.reward_share_bp, f.case_id, f.paid_at,
       (SELECT rep.reporter_id FROM ops.reports rep
         WHERE rep.case_id = f.case_id
           AND (cardinality(rep.fraud_flags) = 0 OR c.review_decision = 'approved')
         ORDER BY rep.received_at, rep.report_id LIMIT 1)
FROM ops.fines f
JOIN ops.cases c USING (case_id)
JOIN ref.category_rules r
  ON r.category = c.category AND tstzrange(r.valid_from, r.valid_to) @> c.first_reported_at
WHERE f.fine_id = %s
  AND f.paid_at IS NOT NULL
  AND (NOT c.needs_review OR c.review_decision = 'approved')
"""


def reward_cents(fine_cents: int, share_bp: int) -> int:
    return fine_cents * share_bp // 10_000


def accrue_reward(conn: psycopg.Connection, fine_id: uuid.UUID) -> uuid.UUID | None:
    """Post the reward for a paid fine. Safe to call any number of times."""
    row = conn.execute(ELIGIBLE_FINE_SQL, [fine_id]).fetchone()
    if row is None:
        return None
    fine_cents, share_bp, case_id, paid_at, reporter_id = row
    amount = reward_cents(fine_cents, share_bp)
    if amount == 0 or reporter_id is None:
        return None

    account = f"payable:{reporter_id}"
    conn.execute(
        "INSERT INTO ledger.accounts (account_id, kind, reporter_id) VALUES (%s, 'liability', %s)"
        " ON CONFLICT DO NOTHING",
        [account, reporter_id],
    )
    inserted = conn.execute(
        # Dated by event time (when the fine was paid), like the rest of the pipeline, so
        # replayed history produces the same ledger as live processing would have.
        "INSERT INTO ledger.transactions (txn_id, kind, case_id, fine_id, memo, created_at)"
        " VALUES (%s, 'reward_accrual', %s, %s, %s, %s)"
        " ON CONFLICT (fine_id) WHERE kind = 'reward_accrual' DO NOTHING RETURNING txn_id",
        [
            uuid.uuid4(),
            case_id,
            fine_id,
            f"{share_bp / 100:g}% of {fine_cents / 100:.2f} EUR",
            paid_at,
        ],
    ).fetchone()
    if inserted is None:
        return None  # already accrued
    txn_id: uuid.UUID = inserted[0]
    conn.execute(
        "INSERT INTO ledger.entries (txn_id, account_id, amount_cents)"
        " VALUES (%s, 'reward_expense', %s), (%s, %s, %s)",
        [txn_id, amount, txn_id, account, -amount],
    )
    return txn_id


def accrue_pending_rewards(conn: psycopg.Connection) -> int:
    """Catch up rewards that became eligible later, e.g. after a manual review approval."""
    pending = conn.execute(
        "SELECT f.fine_id FROM ops.fines f WHERE f.paid_at IS NOT NULL AND NOT EXISTS ("
        " SELECT 1 FROM ledger.transactions t WHERE t.fine_id = f.fine_id"
        " AND t.kind = 'reward_accrual')"
    ).fetchall()
    return sum(accrue_reward(conn, fine_id) is not None for (fine_id,) in pending)


def pay_out(conn: psycopg.Connection, as_of: datetime) -> int:
    """Simulated payout batch: settle every reporter's outstanding balance."""
    balances = conn.execute(
        "SELECT a.account_id, sum(e.amount_cents) FROM ledger.accounts a"
        " JOIN ledger.entries e USING (account_id) JOIN ledger.transactions t USING (txn_id)"
        " WHERE a.kind = 'liability' AND t.created_at <= %s"
        " GROUP BY a.account_id HAVING sum(e.amount_cents) < 0",
        [as_of],
    ).fetchall()
    for account, balance in balances:
        txn_id = uuid.uuid4()
        conn.execute(
            "INSERT INTO ledger.transactions (txn_id, kind, memo, created_at)"
            " VALUES (%s, 'reward_payout', 'simulated bank transfer', %s)",
            [txn_id, as_of],
        )
        conn.execute(
            "INSERT INTO ledger.entries (txn_id, account_id, amount_cents)"
            " VALUES (%s, %s, %s), (%s, 'payout_cash', %s)",
            [txn_id, account, -balance, txn_id, balance],
        )
    return len(balances)

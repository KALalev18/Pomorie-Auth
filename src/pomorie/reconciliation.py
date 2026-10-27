"""Daily reconciliation of the reward ledger against fines (fails loudly on mismatch).

For one day it recomputes, independently of the ledger code, what should have been
accrued: floor(fine × share) for every fine paid that day whose case is eligible, using
the rule valid when the case was first reported. It then compares with what the ledger
holds, and checks the double-entry invariants. Every run is recorded in
``ledger.reconciliation_runs``; a mismatch raises, which fails the Dagster run and alerts.

    python -m pomorie.reconciliation 2026-07-15
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from typing import Any

import psycopg

from pomorie.db import connect

EXPECTED_SQL = """
SELECT coalesce(sum(f.amount_cents * r.reward_share_bp / 10000), 0)
FROM ops.fines f
JOIN ops.cases c USING (case_id)
JOIN ref.category_rules r
  ON r.category = c.category AND tstzrange(r.valid_from, r.valid_to) @> c.first_reported_at
WHERE f.paid_at::date = %(day)s
  AND (NOT c.needs_review OR c.review_decision = 'approved')
  AND r.reward_share_bp > 0
  AND EXISTS (SELECT 1 FROM ops.reports rep WHERE rep.case_id = c.case_id
              AND (cardinality(rep.fraud_flags) = 0 OR c.review_decision = 'approved'))
"""

ACCRUED_SQL = """
SELECT coalesce(sum(e.amount_cents), 0)
FROM ledger.entries e JOIN ledger.transactions t USING (txn_id)
WHERE t.kind = 'reward_accrual' AND e.account_id = 'reward_expense'
  AND t.created_at::date = %(day)s
"""

UNBALANCED_SQL = """
SELECT t.txn_id FROM ledger.transactions t JOIN ledger.entries e USING (txn_id)
WHERE t.created_at::date = %(day)s GROUP BY t.txn_id HAVING sum(e.amount_cents) <> 0
"""

ORPHAN_SQL = """
SELECT t.txn_id FROM ledger.transactions t LEFT JOIN ops.fines f USING (fine_id)
WHERE t.kind = 'reward_accrual' AND t.created_at::date = %(day)s
  AND (f.fine_id IS NULL OR f.paid_at IS NULL)
"""

OVERPAID_SQL = """
SELECT e.account_id FROM ledger.entries e JOIN ledger.accounts a USING (account_id)
WHERE a.kind = 'liability' GROUP BY e.account_id HAVING sum(e.amount_cents) > 0
"""


class ReconciliationError(RuntimeError):
    pass


def reconcile_day(conn: psycopg.Connection, day: date) -> dict[str, Any]:
    params = {"day": day}
    (expected,) = conn.execute(EXPECTED_SQL, params).fetchone() or (0,)
    (accrued,) = conn.execute(ACCRUED_SQL, params).fetchone() or (0,)
    problems = []
    if expected != accrued:
        problems.append(f"accrued {accrued} cents but fines imply {expected} cents")
    if unbalanced := conn.execute(UNBALANCED_SQL, params).fetchall():
        problems.append(f"{len(unbalanced)} unbalanced transactions")
    if orphans := conn.execute(ORPHAN_SQL, params).fetchall():
        problems.append(f"{len(orphans)} accruals without a paid fine")
    if overpaid := conn.execute(OVERPAID_SQL).fetchall():
        problems.append(f"{len(overpaid)} reporter accounts paid more than they earned")

    result = {
        "day": day.isoformat(),
        "expected_cents": int(expected),
        "accrued_cents": int(accrued),
        "passed": not problems,
        "problems": problems,
    }
    conn.execute(
        "INSERT INTO ledger.reconciliation_runs (day, expected_cents, accrued_cents, passed,"
        " problems) VALUES (%s, %s, %s, %s, %s)",
        [day, expected, accrued, not problems, problems],
    )
    return result


def reconcile_and_raise(conn: psycopg.Connection, day: date) -> dict[str, Any]:
    """Record the run (committed, so the audit row survives) and raise on any problem."""
    result = reconcile_day(conn, day)
    conn.commit()
    if not result["passed"]:
        raise ReconciliationError(
            f"ledger reconciliation failed for {day}: {'; '.join(result['problems'])}"
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile the reward ledger for one day.")
    parser.add_argument("day", type=date.fromisoformat)
    args = parser.parse_args()
    with connect() as conn:
        print(json.dumps(reconcile_and_raise(conn, args.day)))


if __name__ == "__main__":
    main()

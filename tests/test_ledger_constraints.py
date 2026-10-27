"""The ledger's guarantees are enforced by Postgres itself, not only by application code."""

import uuid

import psycopg
import pytest

pytestmark = pytest.mark.integration


def _payable(conn: psycopg.Connection) -> str:
    reporter_id = uuid.uuid4()
    account = f"payable:{reporter_id}"
    conn.execute(
        "INSERT INTO ledger.accounts (account_id, kind, reporter_id) VALUES (%s, 'liability', %s)",
        [account, reporter_id],
    )
    return account


def _txn(conn: psycopg.Connection) -> uuid.UUID:
    txn_id = uuid.uuid4()
    conn.execute(
        "INSERT INTO ledger.transactions (txn_id, kind, fine_id) VALUES (%s, 'reward_accrual', %s)",
        [txn_id, uuid.uuid4()],
    )
    return txn_id


def test_balanced_transaction_commits(conn: psycopg.Connection) -> None:
    account = _payable(conn)
    txn_id = _txn(conn)
    conn.execute(
        "INSERT INTO ledger.entries (txn_id, account_id, amount_cents)"
        " VALUES (%s, 'reward_expense', 500), (%s, %s, -500)",
        [txn_id, txn_id, account],
    )
    conn.execute("SET CONSTRAINTS ALL IMMEDIATE")  # run the deferred balance check now


def test_unbalanced_transaction_is_rejected(conn: psycopg.Connection) -> None:
    account = _payable(conn)
    txn_id = _txn(conn)
    conn.execute(
        "INSERT INTO ledger.entries (txn_id, account_id, amount_cents)"
        " VALUES (%s, 'reward_expense', 500), (%s, %s, -499)",
        [txn_id, txn_id, account],
    )
    with pytest.raises(psycopg.errors.RaiseException, match="does not balance"):
        conn.execute("SET CONSTRAINTS ALL IMMEDIATE")


def test_entries_cannot_be_updated_or_deleted(conn: psycopg.Connection) -> None:
    account = _payable(conn)
    txn_id = _txn(conn)
    conn.execute(
        "INSERT INTO ledger.entries (txn_id, account_id, amount_cents)"
        " VALUES (%s, 'reward_expense', 500), (%s, %s, -500)",
        [txn_id, txn_id, account],
    )
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        conn.execute("UPDATE ledger.entries SET amount_cents = 1 WHERE txn_id = %s", [txn_id])


def test_one_accrual_per_fine(conn: psycopg.Connection) -> None:
    fine_id = uuid.uuid4()
    sql = (
        "INSERT INTO ledger.transactions (txn_id, kind, fine_id) VALUES (%s, 'reward_accrual', %s)"
    )
    conn.execute(sql, [uuid.uuid4(), fine_id])
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute(sql, [uuid.uuid4(), fine_id])


def test_category_rule_versions_cannot_overlap(conn: psycopg.Connection) -> None:
    sql = (
        "INSERT INTO ref.category_rules (category, authority, sla_hours, dedup_radius_m,"
        " dedup_window_hours, valid_from, valid_to) VALUES ('noise', 'police', 4, 150, 3, %s, %s)"
    )
    conn.execute(sql, ["2026-01-01", "2026-06-01"])
    conn.execute(sql, ["2026-06-01", None])  # adjacent: fine
    with pytest.raises(psycopg.errors.ExclusionViolation):
        conn.execute(sql, ["2026-05-01", None])

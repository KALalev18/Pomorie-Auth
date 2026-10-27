-- Simulated reward ledger. Double-entry: every transaction's entries sum to zero.
-- Signed amounts: positive = debit, negative = credit.
CREATE TABLE ledger.accounts (
    account_id   text PRIMARY KEY,
    kind         text NOT NULL CHECK (kind IN ('expense', 'liability', 'asset')),
    reporter_id  uuid,  -- set for per-reporter payable accounts
    created_at   timestamptz NOT NULL DEFAULT now(),
    CHECK ((kind = 'liability') = (reporter_id IS NOT NULL))
);

INSERT INTO ledger.accounts (account_id, kind) VALUES
    ('reward_expense', 'expense'),   -- cost to the municipality of rewards granted
    ('payout_cash', 'asset');        -- money actually sent to reporters (simulated)

CREATE TABLE ledger.transactions (
    txn_id      uuid PRIMARY KEY,
    kind        text NOT NULL CHECK (kind IN ('reward_accrual', 'reward_payout')),
    case_id     uuid,
    fine_id     uuid,
    created_at  timestamptz NOT NULL DEFAULT now(),
    memo        text,
    CHECK (kind <> 'reward_accrual' OR fine_id IS NOT NULL)
);
-- One reward per paid fine, even if the fine_paid event is delivered twice.
CREATE UNIQUE INDEX transactions_one_accrual_per_fine
    ON ledger.transactions (fine_id) WHERE kind = 'reward_accrual';

CREATE TABLE ledger.entries (
    entry_id      bigserial PRIMARY KEY,
    txn_id        uuid NOT NULL REFERENCES ledger.transactions,
    account_id    text NOT NULL REFERENCES ledger.accounts,
    amount_cents  bigint NOT NULL CHECK (amount_cents <> 0)
);
CREATE INDEX entries_txn_idx ON ledger.entries (txn_id);
CREATE INDEX entries_account_idx ON ledger.entries (account_id);

-- Append-only: corrections are new reversing transactions, never edits.
CREATE FUNCTION ledger.forbid_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'ledger is append-only: % on % is not allowed', TG_OP, TG_TABLE_NAME;
END $$;

CREATE TRIGGER entries_append_only BEFORE UPDATE OR DELETE ON ledger.entries
    FOR EACH ROW EXECUTE FUNCTION ledger.forbid_change();
CREATE TRIGGER transactions_append_only BEFORE UPDATE OR DELETE ON ledger.transactions
    FOR EACH ROW EXECUTE FUNCTION ledger.forbid_change();
CREATE TRIGGER entries_no_truncate BEFORE TRUNCATE ON ledger.entries
    FOR EACH STATEMENT EXECUTE FUNCTION ledger.forbid_change();

-- Checked at COMMIT (deferred), after all entries of the transaction are inserted.
CREATE FUNCTION ledger.check_balanced() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    total bigint;
BEGIN
    SELECT coalesce(sum(amount_cents), 0) INTO total FROM ledger.entries WHERE txn_id = NEW.txn_id;
    IF total <> 0 THEN
        RAISE EXCEPTION 'ledger transaction % does not balance (sum = %)', NEW.txn_id, total;
    END IF;
    RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER entries_balanced AFTER INSERT ON ledger.entries
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION ledger.check_balanced();

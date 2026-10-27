"""Dagster assets, schedules and alerts.

Split of responsibilities:
- the stream processor (always on) turns events into raw/ops rows within milliseconds;
- Dagster runs everything batch: the warehouse (dbt), simulated authorities, reward
  payouts, reconciliation, GDPR erasure and retention.

Tables written by the stream processor are declared as external assets, so the lineage
graph is complete (generator -> Kafka -> raw/ops -> dbt marts -> reconciliation) without
pretending Dagster runs the stream.

    dagster dev -m pomorie.orchestration.definitions
"""

# No "from __future__ import annotations": Dagster inspects annotations at runtime.

import json
import os
from collections import Counter
from datetime import UTC, date, datetime, timedelta

import httpx
from dagster import (
    AssetCheckResult,
    AssetCheckSeverity,
    AssetExecutionContext,
    AssetKey,
    AssetSelection,
    AssetSpec,
    Backoff,
    DailyPartitionsDefinition,
    DefaultScheduleStatus,
    DefaultSensorStatus,
    Definitions,
    MaterializeResult,
    MonthlyPartitionsDefinition,
    RetryPolicy,
    RunFailureSensorContext,
    ScheduleDefinition,
    asset,
    asset_check,
    build_schedule_from_partitioned_job,
    define_asset_job,
    run_failure_sensor,
)
from dagster_dbt import DbtCliResource, DbtProject, dbt_assets, get_asset_key_for_model

from pomorie import gdpr
from pomorie.config import get_settings
from pomorie.db import connect
from pomorie.generator.events import generate_day
from pomorie.generator.run import DEFAULT_SEED, register_reporters, write_labels
from pomorie.generator.world import build_world
from pomorie.kafka import ensure_topics, make_producer
from pomorie.processing.ledger import accrue_pending_rewards, pay_out
from pomorie.reconciliation import reconcile_and_raise
from pomorie.reference.paths import REPO_ROOT
from pomorie.simulation.authorities import simulate

DBT_PROJECT = DbtProject(project_dir=REPO_ROOT / "dbt", profiles_dir=REPO_ROOT / "dbt")
DBT_PROJECT.prepare_if_dev()

HISTORY_START = "2026-06-01"
daily = DailyPartitionsDefinition(start_date=HISTORY_START)
monthly = MonthlyPartitionsDefinition(start_date=HISTORY_START)

# Transient failures (database restart, broker leader election) are retried with backoff.
RETRY = RetryPolicy(max_retries=3, delay=15, backoff=Backoff.EXPONENTIAL)


def _day(context: AssetExecutionContext) -> date:
    return date.fromisoformat(context.partition_key)


# --- ingestion --------------------------------------------------------------------------


@asset(
    partitions_def=daily,
    group_name="ingestion",
    kinds={"python", "kafka"},
    retry_policy=RETRY,
    description="One day of synthetic report events, published to reports.submitted.v1. "
    "Deterministic per day: re-running a partition republishes identical event ids, "
    "which the processor recognises as duplicates, so backfills are idempotent.",
)
def synthetic_reports(context: AssetExecutionContext) -> MaterializeResult[None]:
    world = build_world(DEFAULT_SEED)
    events = generate_day(world, _day(context))
    ensure_topics()
    producer = make_producer()
    with connect() as conn:
        register_reporters(conn, world)
        write_labels(conn, events)
        conn.commit()
    for g in events:
        producer.produce(get_settings().reports_topic, key=g.category, value=g.value)
        producer.poll(0)
    if producer.flush(30):
        raise RuntimeError("not all events were delivered to Kafka")
    scenarios = Counter(g.scenario for g in events)
    return MaterializeResult(metadata={"events": len(events), "scenarios": dict(scenarios)})


# Written continuously by the stream processor (python -m pomorie.processing.consumer).
STREAM_TABLES = [
    AssetSpec(
        AssetKey(["raw", "report_events"]),
        deps=[synthetic_reports],
        group_name="stream",
        kinds={"postgres"},
        description="Accepted report events, landed by the stream processor.",
    ),
    AssetSpec(
        AssetKey(["raw", "dead_letter"]),
        deps=[synthetic_reports],
        group_name="stream",
        kinds={"postgres"},
        description="Rejected events with reasons.",
    ),
    *[
        AssetSpec(
            AssetKey(["ops", table]),
            deps=[AssetKey(["raw", "report_events"])],
            group_name="stream",
            kinds={"postgres"},
        )
        for table in ("reports", "cases", "case_status_history")
    ],
]


@asset(
    deps=[AssetKey(["ops", "cases"])],
    group_name="authorities",
    kinds={"python", "kafka"},
    retry_policy=RETRY,
    description="Simulated police and municipality decisions and fine payments, published "
    "to authority.outcomes.v1. Nothing is sent to real authorities.",
)
def authority_outcomes() -> MaterializeResult[None]:
    ensure_topics()
    with connect() as conn:
        counts = simulate(conn, make_producer(), datetime.now(UTC))
    return MaterializeResult(metadata={"outcomes": counts})


OUTCOME_TABLES = [
    AssetSpec(
        AssetKey(["raw", "outcome_events"]),
        deps=[authority_outcomes],
        group_name="stream",
        kinds={"postgres"},
    ),
    AssetSpec(
        AssetKey(["ops", "fines"]),
        deps=[AssetKey(["raw", "outcome_events"])],
        group_name="stream",
        kinds={"postgres"},
    ),
]


@asset(
    deps=[AssetKey(["ops", "fines"])],
    group_name="ledger",
    kinds={"postgres"},
    retry_policy=RETRY,
    description="Rewards that became eligible after a manual review approval.",
)
def pending_rewards() -> MaterializeResult[None]:
    with connect() as conn:
        accrued = accrue_pending_rewards(conn)
        conn.commit()
    return MaterializeResult(metadata={"accrued": accrued})


LEDGER_TABLES = [
    AssetSpec(
        AssetKey(["ledger", table]),
        deps=[AssetKey(["ops", "fines"]), pending_rewards],
        group_name="ledger",
        kinds={"postgres"},
    )
    for table in ("transactions", "entries", "accounts")
]

# --- warehouse --------------------------------------------------------------------------


@dbt_assets(manifest=DBT_PROJECT.manifest_path, project=DBT_PROJECT)
def warehouse(context: AssetExecutionContext, dbt: DbtCliResource):  # type: ignore[no-untyped-def]
    """dbt build: models, snapshot (SCD2 reputation) and all data tests."""
    yield from dbt.cli(["build"], context=context).stream()


# Resolved from the dbt manifest (keys carry the schema prefix, e.g. analytics/fct_cases).
FCT_REWARD_LEDGER = get_asset_key_for_model([warehouse], "fct_reward_ledger")
FCT_FINES = get_asset_key_for_model([warehouse], "fct_fines")


@asset(
    partitions_def=monthly,
    deps=[FCT_REWARD_LEDGER],
    group_name="ledger",
    kinds={"postgres"},
    retry_policy=RETRY,
    description="Simulated monthly payout: settles every reporter's balance at month end.",
)
def reward_payouts(context: AssetExecutionContext) -> MaterializeResult[None]:
    month_start = date.fromisoformat(context.partition_key)
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    as_of = datetime(next_month.year, next_month.month, 1, tzinfo=UTC) - timedelta(seconds=1)
    with connect() as conn:
        accrue_pending_rewards(conn)
        paid = pay_out(conn, as_of)
        conn.commit()
    return MaterializeResult(metadata={"accounts_paid": paid, "as_of": as_of.isoformat()})


@asset(
    partitions_def=daily,
    deps=[FCT_REWARD_LEDGER, FCT_FINES],
    group_name="ledger",
    kinds={"postgres"},
    description="Reconciles one day of rewards against paid fines. A mismatch fails the run "
    "(and the failure sensor alerts); the result is recorded either way.",
)
def ledger_reconciliation(context: AssetExecutionContext) -> MaterializeResult[None]:
    with connect() as conn:
        result = reconcile_and_raise(conn, _day(context))
    return MaterializeResult(metadata=result)


@asset_check(asset=AssetKey(["raw", "report_events"]), blocking=False)
def report_events_freshness() -> AssetCheckResult:
    """Warn if nothing has been ingested for 24 hours (the app or the processor is down)."""
    with connect() as conn:
        (latest,) = conn.execute("SELECT max(ingested_at) FROM raw.report_events").fetchone() or (
            None,
        )
    age_h = None if latest is None else (datetime.now(UTC) - latest).total_seconds() / 3600
    return AssetCheckResult(
        passed=age_h is not None and age_h < 24,
        severity=AssetCheckSeverity.WARN,
        metadata={"hours_since_last_event": round(age_h, 1) if age_h is not None else -1},
    )


@asset_check(asset=AssetKey(["raw", "dead_letter"]), blocking=False)
def dead_letter_rate() -> AssetCheckResult:
    """Warn when more than 10 % of today's events were rejected (a broken client release)."""
    with connect() as conn:
        rejected, accepted = conn.execute(
            "SELECT"
            " (SELECT count(*) FROM raw.dead_letter WHERE created_at > now() - interval '1 day'),"
            " (SELECT count(*) FROM raw.report_events WHERE ingested_at > now() - interval '1 day')"
        ).fetchone() or (0, 0)
    total = rejected + accepted
    rate = rejected / total if total else 0.0
    return AssetCheckResult(
        passed=rate <= 0.10,
        severity=AssetCheckSeverity.WARN,
        metadata={"rejected": rejected, "accepted": accepted, "rate": round(rate, 4)},
    )


# --- privacy ----------------------------------------------------------------------------


@asset(group_name="privacy", kinds={"postgres", "s3"}, retry_policy=RETRY)
def gdpr_erasure() -> MaterializeResult[None]:
    """Process open erasure requests (GDPR Art. 17); the next dbt build propagates them."""
    with connect() as conn:
        handled = gdpr.process_erasure_requests(conn)
        conn.commit()
    return MaterializeResult(metadata={"requests": handled})


@asset(group_name="privacy", kinds={"postgres", "s3"}, retry_policy=RETRY)
def data_retention() -> MaterializeResult[None]:
    """Delete personal data past its retention period (photos, descriptions, plates)."""
    with connect() as conn:
        result = gdpr.apply_retention(conn, datetime.now(UTC))
    return MaterializeResult(metadata=result)


# --- jobs, schedules, alerts ------------------------------------------------------------

warehouse_job = define_asset_job(
    "warehouse_job",
    selection=AssetSelection.assets(authority_outcomes, pending_rewards, gdpr_erasure)
    | AssetSelection.assets(warehouse),
)
reconciliation_job = define_asset_job(
    "reconciliation_job",
    selection=AssetSelection.assets(ledger_reconciliation),
    partitions_def=daily,
)
payout_job = define_asset_job(
    "payout_job", selection=AssetSelection.assets(reward_payouts), partitions_def=monthly
)
ingestion_job = define_asset_job(
    "ingestion_job", selection=AssetSelection.assets(synthetic_reports), partitions_def=daily
)
retention_job = define_asset_job("retention_job", selection=AssetSelection.assets(data_retention))

schedules = [
    ScheduleDefinition(
        job=warehouse_job,
        cron_schedule="0 * * * *",
        default_status=DefaultScheduleStatus.RUNNING,
    ),
    build_schedule_from_partitioned_job(
        reconciliation_job, hour_of_day=2, default_status=DefaultScheduleStatus.RUNNING
    ),
    build_schedule_from_partitioned_job(
        payout_job, day_of_month=1, hour_of_day=4, default_status=DefaultScheduleStatus.RUNNING
    ),
    ScheduleDefinition(
        job=retention_job, cron_schedule="0 3 * * *", default_status=DefaultScheduleStatus.RUNNING
    ),
]


@run_failure_sensor(default_status=DefaultSensorStatus.RUNNING)
def alert_on_failure(context: RunFailureSensorContext) -> None:
    """Post failures to a Slack-compatible webhook if ALERT_WEBHOOK_URL is set, else log."""
    message = (
        f"Pomorie pipeline: run {context.dagster_run.job_name} failed: "
        f"{context.failure_event.message}"
    )
    url = os.environ.get("ALERT_WEBHOOK_URL")
    if url:
        httpx.post(url, content=json.dumps({"text": message}), timeout=10)
    else:
        context.log.error(message)


defs = Definitions(
    assets=[
        synthetic_reports,
        *STREAM_TABLES,
        authority_outcomes,
        *OUTCOME_TABLES,
        pending_rewards,
        *LEDGER_TABLES,
        warehouse,
        reward_payouts,
        ledger_reconciliation,
        gdpr_erasure,
        data_retention,
    ],
    asset_checks=[report_events_freshness, dead_letter_rate],
    jobs=[warehouse_job, reconciliation_job, payout_job, ingestion_job, retention_job],
    schedules=schedules,
    sensors=[alert_on_failure],
    resources={"dbt": DbtCliResource(project_dir=DBT_PROJECT)},
)

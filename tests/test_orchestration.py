"""The Dagster code location loads and wires the lineage the README describes."""

import os
import subprocess

import pytest
from dagster import AssetKey

from pomorie.reference.paths import REPO_ROOT

MANIFEST = REPO_ROOT / "dbt" / "target" / "manifest.json"


@pytest.fixture(scope="module", autouse=True)
def dbt_manifest() -> None:
    if not MANIFEST.exists():  # dbt parse needs no database connection
        subprocess.run(
            ["dbt", "parse", "--quiet"],
            cwd=REPO_ROOT / "dbt",
            env={**os.environ, "DBT_PROFILES_DIR": "."},
            check=True,
        )


def test_definitions_load_with_full_lineage() -> None:
    from pomorie.orchestration.definitions import defs

    graph = defs.resolve_asset_graph()
    keys = {key.to_user_string() for key in graph.get_all_asset_keys()}
    for expected in [
        "synthetic_reports",
        "raw/report_events",
        "analytics/fct_cases",
        "ledger_reconciliation",
    ]:
        assert expected in keys

    # generator -> stream tables -> dbt staging, and dbt marts -> reconciliation.
    def parents(*key: str) -> set[AssetKey]:
        return set(graph.get(AssetKey(list(key))).parent_keys)

    assert AssetKey(["synthetic_reports"]) in parents("raw", "report_events")
    assert AssetKey(["ops", "reports"]) in parents("analytics_staging", "stg_reports")
    assert AssetKey(["analytics", "fct_reward_ledger"]) in parents("ledger_reconciliation")


def test_schedules_and_alerting_are_registered() -> None:
    from pomorie.orchestration.definitions import defs

    assert {s.name for s in defs.schedules or []} >= {
        "warehouse_job_schedule",
        "reconciliation_job_schedule",
        "payout_job_schedule",
        "retention_job_schedule",
    }
    assert any(s.name == "alert_on_failure" for s in defs.sensors or [])

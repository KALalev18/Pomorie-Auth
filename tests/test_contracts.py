import copy
from typing import Any

import pytest

from pomorie.contracts import (
    AUTHORITY_OUTCOME,
    REPORT_SUBMITTED,
    categories,
    load_schema,
    validate,
)
from pomorie.contracts.compat import breaking_changes


def report(**overrides: Any) -> dict[str, Any]:
    event: dict[str, Any] = {
        "schema": "report.submitted/1",
        "event_id": "0b6f6d1e-6a8e-4b9a-9d2a-0e8e3c1f5a10",
        "occurred_at": "2026-07-14T09:30:00Z",
        "received_at": "2026-07-14T09:30:02Z",
        "reporter_id": "5d1c3f0a-2b7e-4c1d-8f3a-9e6b2a4c7d11",
        "category": "illegal_parking",
        "location": {"lat": 42.5684, "lon": 27.6168, "accuracy_m": 8},
        "plate_hash": "a" * 64,
    }
    event.update(overrides)
    return event


def test_valid_report() -> None:
    assert validate(REPORT_SUBMITTED, report()) == []


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"category": "graffiti"}, "$.category"),
        ({"event_id": "not-a-uuid"}, "$.event_id"),
        ({"occurred_at": "yesterday"}, "$.occurred_at"),
        ({"location": {"lat": 95, "lon": 27.6}}, "$.location.lat"),
        ({"plate_hash": "CA1234AB"}, "$.plate_hash"),
        ({"email": "someone@example.com"}, "$"),  # unknown field: no personal data sneaks in
    ],
)
def test_invalid_report(overrides: dict[str, Any], expected: str) -> None:
    errors = validate(REPORT_SUBMITTED, report(**overrides))
    assert errors
    assert errors[0].startswith(expected)


def test_missing_required_fields_are_all_reported() -> None:
    errors = validate(REPORT_SUBMITTED, {"schema": "report.submitted/1"})
    assert len(errors) == 6


def test_fine_outcome_requires_amount() -> None:
    outcome: dict[str, Any] = {
        "schema": "authority.outcome/1",
        "event_id": "0b6f6d1e-6a8e-4b9a-9d2a-0e8e3c1f5a10",
        "occurred_at": "2026-07-15T10:00:00Z",
        "case_id": "5d1c3f0a-2b7e-4c1d-8f3a-9e6b2a4c7d11",
        "authority": "traffic_police",
        "outcome": "fine_issued",
    }
    assert validate(AUTHORITY_OUTCOME, outcome)
    outcome |= {
        "fine_id": "7a2b3c4d-1e2f-4a5b-8c9d-0e1f2a3b4c5d",
        "amount_cents": 5000,
        "currency": "EUR",
    }
    assert validate(AUTHORITY_OUTCOME, outcome) == []


def test_categories_come_from_contract() -> None:
    assert "illegal_parking" in categories()
    assert len(categories()) == len(set(categories()))


# --- compatibility checker -------------------------------------------------------------


def test_identical_schema_is_compatible() -> None:
    schema = load_schema(REPORT_SUBMITTED)
    assert list(breaking_changes(schema, copy.deepcopy(schema))) == []


def test_adding_optional_field_and_enum_value_is_compatible() -> None:
    old = load_schema(REPORT_SUBMITTED)
    new = copy.deepcopy(old)
    new["properties"]["weather"] = {"type": "string"}
    new["properties"]["category"]["enum"].append("graffiti")
    assert list(breaking_changes(old, new)) == []


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda s: s["properties"].pop("description"), "property removed"),
        (lambda s: s["required"].append("description"), "new required fields"),
        (lambda s: s["properties"]["category"]["enum"].remove("noise"), "enum values removed"),
        (lambda s: s["properties"]["location"]["properties"]["lat"].update(type="string"), "type"),
        (lambda s: s["properties"]["description"].update(maxLength=200), "maxLength tightened"),
        (lambda s: s["properties"]["schema"].update(const="report.submitted/2"), "const changed"),
    ],
)
def test_breaking_changes_are_detected(mutate: Any, expected: str) -> None:
    old = load_schema(REPORT_SUBMITTED)
    new = copy.deepcopy(old)
    mutate(new)
    problems = list(breaking_changes(old, new))
    assert any(expected in p for p in problems), problems

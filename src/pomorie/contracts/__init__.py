"""Event contracts shared by the API (producer) and the pipeline (consumer).

The JSON Schemas in ``contracts/`` are the single source of truth. Both sides validate
against the same file, and CI rejects breaking changes to a published version.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "contracts"

REPORT_SUBMITTED = "report_submitted.v1"
AUTHORITY_OUTCOME = "authority_outcome.v1"


def load_schema(name: str) -> dict[str, Any]:
    schema: dict[str, Any] = json.loads((CONTRACTS_DIR / f"{name}.json").read_text("utf-8"))
    return schema


@cache
def _validator(name: str) -> Draft202012Validator:
    schema = load_schema(name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


def validate(name: str, event: Any) -> list[str]:
    """Return every contract violation as ``"<json path>: <message>"``; empty means valid."""
    errors = sorted(_validator(name).iter_errors(event), key=lambda e: list(e.absolute_path))
    return [f"{e.json_path}: {e.message}" for e in errors]


def categories() -> list[str]:
    values: list[str] = load_schema(REPORT_SUBMITTED)["properties"]["category"]["enum"]
    return values

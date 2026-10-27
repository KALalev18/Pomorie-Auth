"""Detect breaking changes between two versions of a JSON Schema contract.

"Breaking" means an event that the old schema accepted could be rejected by the new one,
or a consumer written for the old schema could receive something it does not expect.
A breaking change needs a new versioned file (e.g. ``report_submitted.v2.json``) and a
migration period, not an edit to v1.

Usage (CI):
    python -m pomorie.contracts.compat --base-ref origin/main
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Iterator
from typing import Any

from pomorie.contracts import CONTRACTS_DIR

# Keywords where a larger value in the new schema is stricter, or a smaller one.
_STRICTER_IF_LARGER = ("minimum", "exclusiveMinimum", "minLength", "minItems")
_STRICTER_IF_SMALLER = ("maximum", "exclusiveMaximum", "maxLength", "maxItems")


def breaking_changes(old: dict[str, Any], new: dict[str, Any], path: str = "$") -> Iterator[str]:
    if old.get("type") != new.get("type"):
        yield f"{path}: type changed {old.get('type')!r} -> {new.get('type')!r}"

    if "const" in old and old.get("const") != new.get("const"):
        yield f"{path}: const changed {old['const']!r} -> {new.get('const')!r}"

    if "enum" in old:
        removed = set(old["enum"]) - set(new.get("enum", old["enum"]))
        if removed:
            yield f"{path}: enum values removed {sorted(removed)}"
    elif "enum" in new:
        yield f"{path}: enum restriction added"

    for key in _STRICTER_IF_LARGER:
        if key in new and (key not in old or new[key] > old[key]):
            yield f"{path}: {key} tightened {old.get(key)!r} -> {new[key]!r}"
    for key in _STRICTER_IF_SMALLER:
        if key in new and (key not in old or new[key] < old[key]):
            yield f"{path}: {key} tightened {old.get(key)!r} -> {new[key]!r}"

    for key in ("pattern", "format"):
        if key in new and new.get(key) != old.get(key):
            yield f"{path}: {key} changed {old.get(key)!r} -> {new[key]!r}"

    if (
        old.get("additionalProperties", True) is not False
        and new.get("additionalProperties") is False
    ):
        yield f"{path}: additionalProperties closed"

    added_required = set(new.get("required", [])) - set(old.get("required", []))
    if added_required:
        yield f"{path}: new required fields {sorted(added_required)}"

    old_props, new_props = old.get("properties", {}), new.get("properties", {})
    for name, old_prop in old_props.items():
        if name not in new_props:
            yield f"{path}.{name}: property removed"
        else:
            yield from breaking_changes(old_prop, new_props[name], f"{path}.{name}")

    if "items" in old and "items" in new:
        yield from breaking_changes(old["items"], new["items"], f"{path}[]")


def _schema_at_ref(ref: str, filename: str) -> dict[str, Any] | None:
    result = subprocess.run(
        ["git", "show", f"{ref}:contracts/{filename}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        return None  # file is new on this branch: nothing to be compatible with
    schema: dict[str, Any] = json.loads(result.stdout)
    return schema


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail if a published contract changed in a breaking way."
    )
    parser.add_argument("--base-ref", default="origin/main")
    args = parser.parse_args()

    failed = False
    for schema_file in sorted(CONTRACTS_DIR.glob("*.json")):
        old = _schema_at_ref(args.base_ref, schema_file.name)
        if old is None:
            print(f"{schema_file.name}: new contract")
            continue
        new = json.loads(schema_file.read_text("utf-8"))
        problems = list(breaking_changes(old, new))
        for problem in problems:
            print(f"{schema_file.name}: BREAKING {problem}")
        if not problems:
            print(f"{schema_file.name}: compatible")
        failed = failed or bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

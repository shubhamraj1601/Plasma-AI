"""Validate messages against the JSON Schemas in schemas/v0."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from plasma_ai.messages import Record

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas" / "v0"
_ATTRIBUTE_KEYS = ("schema_version", "message_type", "run_id", "source")

# Number arrays too large for jsonschema's per-item checks (full OES mode is
# 2 million values per second). Their items are type-checked directly; the
# schema then sees only the first item, so the result matches a full check.
_BULK_NUMBER_ARRAYS = {"oes_block": "intensities"}


class MessageValidationError(ValueError):
    """Raised when a message does not match its schema."""


class MessageValidator:
    """Holds one compiled validator per message type."""

    def __init__(self, schema_dir: Path = SCHEMA_DIR) -> None:
        schemas = {}
        for path in sorted(Path(schema_dir).glob("*.schema.json")):
            with path.open(encoding="utf-8") as f:
                schemas[path.name.removesuffix(".schema.json")] = json.load(f)
        if "envelope" not in schemas:
            raise FileNotFoundError(f"no envelope.schema.json in {schema_dir}")
        registry: Registry = Registry().with_resources(
            (s["$id"], Resource.from_contents(s)) for s in schemas.values()
        )
        self._validators = {
            name: Draft202012Validator(schema, registry=registry)
            for name, schema in schemas.items()
            if name != "envelope"
        }

    @property
    def message_types(self) -> list[str]:
        """Message types that have a schema."""
        return sorted(self._validators)

    def errors(self, data: Any) -> list[str]:
        """All schema errors for a message (the `data` part of a record); empty if valid."""
        message_type = data.get("message_type") if isinstance(data, dict) else None
        validator = self._validators.get(message_type) if isinstance(message_type, str) else None
        if validator is None:
            return [f"unknown or missing message_type: {message_type!r}"]
        errors: list[str] = []
        field = _BULK_NUMBER_ARRAYS.get(message_type)
        if field is not None and isinstance(data.get(field), list) and len(data[field]) > 1:
            values = data[field]
            for i, v in enumerate(values):
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    errors.append(f"{field}/{i}: {v!r} is not of type 'number'")
                    break
            data = {**data, field: values[:1]}
        errors += [
            f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
            for e in validator.iter_errors(data)
        ]
        return errors

    def validate(self, data: Any) -> None:
        """Raise MessageValidationError if the message is invalid."""
        errors = self.errors(data)
        if errors:
            raise MessageValidationError(_describe(data, errors))

    def validate_record(self, record: Record) -> None:
        """Validate the message and check its Pub/Sub attributes are strings matching the data."""
        errors = self.errors(record.data)
        if set(record.attributes) != set(_ATTRIBUTE_KEYS):
            errors.append(f"attributes must have exactly {list(_ATTRIBUTE_KEYS)}, got {sorted(record.attributes)}")
        for key, value in record.attributes.items():
            if not isinstance(value, str):
                errors.append(f"attribute {key!r} must be a string, got {value!r}")
            elif key in _ATTRIBUTE_KEYS and record.data.get(key) != value:
                errors.append(f"attribute {key!r}={value!r} does not match data ({record.data.get(key)!r})")
        if errors:
            raise MessageValidationError(_describe(record.data, errors))


def _describe(data: Any, errors: list[str]) -> str:
    where = ""
    if isinstance(data, dict):
        where = f" ({data.get('message_type')} run_id={data.get('run_id')} seq_no={data.get('seq_no')})"
    return f"invalid message{where}:\n  - " + "\n  - ".join(errors)

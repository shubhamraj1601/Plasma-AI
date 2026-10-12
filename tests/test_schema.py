"""Every generated message validates; malformed messages are rejected."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from conftest import read_lines, run_dirs, run_generator
from plasma_ai.validate import MessageValidationError, MessageValidator

VALIDATOR = MessageValidator()


@pytest.fixture(scope="module")
def messages(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict]:
    """One message of each generated type from a short run."""
    out = run_generator(tmp_path_factory.mktemp("schema"), "--duration-s", "1", "--seed", "3", "--no-validate")
    by_type: dict[str, dict] = {}
    for path in run_dirs(out)[0].glob("*.jsonl"):
        for record in read_lines(path):
            by_type.setdefault(record["data"]["message_type"], record["data"])
    return by_type


# Full mode is 2 million intensities per second of data, so its run is kept to 1 s.
@pytest.mark.parametrize(("mode", "duration_s"), [("lines", "10"), ("full", "1")])
def test_every_generated_message_validates(tmp_path: Path, mode: str, duration_s: str) -> None:
    out = run_generator(tmp_path, "--duration-s", duration_s, "--seed", "7", "--oes-mode", mode, "--no-validate")
    count = 0
    for path in run_dirs(out)[0].glob("*.jsonl"):
        for record in read_lines(path):
            VALIDATOR.validate(record["data"])
            count += 1
    assert count == 2 * int(float(duration_s) * 10) + 3


def test_schemas_cover_every_message_type() -> None:
    assert VALIDATOR.message_types == [
        "dead_letter", "oes_block", "process_sample", "run_end", "run_outcome", "run_start",
    ]


@pytest.mark.parametrize("message_type", ["process_sample", "oes_block", "run_start", "run_end", "run_outcome"])
def test_extra_top_level_field_fails(messages: dict[str, dict], message_type: str) -> None:
    bad = {**messages[message_type], "unexpected_field": 1}
    with pytest.raises(MessageValidationError, match="unexpected_field"):
        VALIDATOR.validate(bad)


@pytest.mark.parametrize(("message_type", "nested"), [("process_sample", "plasma_state"), ("run_start", "setpoints")])
def test_extra_nested_field_fails(messages: dict[str, dict], message_type: str, nested: str) -> None:
    bad = copy.deepcopy(messages[message_type])
    bad[nested]["typo_field"] = 1.0
    with pytest.raises(MessageValidationError, match="typo_field"):
        VALIDATOR.validate(bad)


@pytest.mark.parametrize(
    ("message_type", "field", "value"),
    [
        ("process_sample", "power_kw", "1.85"),
        ("process_sample", "seq_no", 1.5),
        ("process_sample", "event_ts", "2026-10-12T05:00:00Z"),
        ("oes_block", "saturated", "no"),
        ("oes_block", "mode", "partial"),
        ("run_end", "end_reason", "crashed"),
        ("run_outcome", "h2_purity_percent", None),
        ("run_start", "schema_version", "1.0"),
    ],
)
def test_wrong_type_or_value_fails(messages: dict[str, dict], message_type: str, field: str, value: object) -> None:
    bad = {**messages[message_type], field: value}
    with pytest.raises(MessageValidationError):
        VALIDATOR.validate(bad)


@pytest.mark.parametrize("bad_item", ["12.0", True, None])
def test_bad_intensity_item_fails(messages: dict[str, dict], bad_item: object) -> None:
    intensities = list(messages["oes_block"]["intensities"])
    intensities[-1] = bad_item
    with pytest.raises(MessageValidationError, match="intensities"):
        VALIDATOR.validate({**messages["oes_block"], "intensities": intensities})


@pytest.mark.parametrize(
    ("message_type", "field"),
    [("process_sample", "pressure_kpa"), ("process_sample", "plasma_state"), ("oes_block", "intensities"),
     ("run_start", "generator_seed"), ("run_outcome", "raman_id_ig"), ("run_end", "message_id")],
)
def test_missing_required_field_fails(messages: dict[str, dict], message_type: str, field: str) -> None:
    bad = {k: v for k, v in messages[message_type].items() if k != field}
    with pytest.raises(MessageValidationError, match=field):
        VALIDATOR.validate(bad)


def test_null_readings_are_allowed(messages: dict[str, dict]) -> None:
    VALIDATOR.validate({**messages["process_sample"], "power_kw": None, "plasma_state": None})


def test_dead_letter_schema(messages: dict[str, dict]) -> None:
    envelope = {k: messages["run_end"][k] for k in (
        "schema_version", "message_id", "source", "reactor_id", "run_id", "seq_no", "event_ts", "publish_ts",
    )}
    dead = {
        **envelope,
        "message_type": "dead_letter",
        "original_message": "eyJiYWQiOiB0cnVlfQ==",
        "original_attributes": {"message_type": "process_sample"},
        "error_stage": "schema",
        "error_code": "SCHEMA_INVALID",
        "error_detail": "power_kw: '1.85' is not of type 'number'",
        "failed_ts": "2026-10-12T05:00:01.000000Z",
    }
    VALIDATOR.validate(dead)
    with pytest.raises(MessageValidationError):
        VALIDATOR.validate({**dead, "error_stage": "network"})
    with pytest.raises(MessageValidationError):
        VALIDATOR.validate({**dead, "original_attributes": {"seq_no": 3}})

"""Message counts, seq_no, ordering and JSON hygiene of a 10 s run."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

import pytest

from conftest import read_lines, run_dirs, run_generator
from plasma_ai.messages import parse_ts


@pytest.fixture(scope="module")
def run_files(tmp_path_factory: pytest.TempPathFactory) -> dict[str, list[dict]]:
    out = run_generator(tmp_path_factory.mktemp("counts"), "--duration-s", "10", "--seed", "11")
    (run_dir,) = run_dirs(out)
    return {p.name: read_lines(p) for p in sorted(run_dir.glob("*.jsonl"))}


def test_files_per_topic(run_files: dict[str, list[dict]]) -> None:
    assert sorted(run_files) == ["oes-spectra.jsonl", "process-ts.jsonl"]
    assert {r["data"]["message_type"] for r in run_files["oes-spectra.jsonl"]} == {"oes_block"}


def test_counts(run_files: dict[str, list[dict]]) -> None:
    counts = Counter(r["data"]["message_type"] for records in run_files.values() for r in records)
    assert counts == {"process_sample": 100, "oes_block": 100, "run_start": 1, "run_end": 1, "run_outcome": 1}


def test_seq_no_contiguous_per_type(run_files: dict[str, list[dict]]) -> None:
    seqs: defaultdict[tuple[str, str], list[int]] = defaultdict(list)
    for records in run_files.values():
        for r in records:
            seqs[(r["data"]["run_id"], r["data"]["message_type"])].append(r["data"]["seq_no"])
    for key, values in seqs.items():
        assert values == list(range(len(values))), key


def test_event_ts_non_decreasing_per_file(run_files: dict[str, list[dict]]) -> None:
    for name, records in run_files.items():
        times = [parse_ts(r["data"]["event_ts"]) for r in records]
        assert times == sorted(times), name


def test_run_event_timing(run_files: dict[str, list[dict]]) -> None:
    process = [r["data"] for r in run_files["process-ts.jsonl"]]
    assert process[0]["message_type"] == "run_start"
    assert [r["message_type"] for r in process[-2:]] == ["run_end", "run_outcome"]
    start, end, outcome = (parse_ts(process[i]["event_ts"]) for i in (0, -2, -1))
    assert end - start == timedelta(seconds=10)
    assert outcome - end == timedelta(seconds=1)
    assert all(r["publish_ts"] == r["event_ts"] for r in process)


def test_attributes_are_strings_matching_data(run_files: dict[str, list[dict]]) -> None:
    for records in run_files.values():
        for r in records:
            assert set(r["attributes"]) == {"schema_version", "message_type", "run_id", "source"}
            for key, value in r["attributes"].items():
                assert isinstance(value, str)
                assert value == r["data"][key]


def test_no_nan_or_infinity_text(run_files: dict[str, list[dict]], tmp_path: Path) -> None:
    # read_lines already rejects NaN/Infinity tokens while parsing; this checks the raw text too.
    out = run_generator(tmp_path, "--duration-s", "1", "--seed", "11")
    for path in run_dirs(out)[0].glob("*.jsonl"):
        text = path.read_text(encoding="utf-8")
        assert "NaN" not in text and "Infinity" not in text


def test_consecutive_runs_follow_each_other(tmp_path: Path) -> None:
    out = run_generator(tmp_path, "--runs", "2", "--duration-s", "2", "--seed", "5")
    first, second = (read_lines(d / "process-ts.jsonl") for d in run_dirs(out))
    # run_id = prefix + UTC start date and time + run number; run 2 starts 2 s + 5 s gap later.
    assert first[0]["data"]["run_id"] == "SYN-20261012-050000-001"
    assert second[0]["data"]["run_id"] == "SYN-20261012-050007-002"
    first_end = parse_ts(first[-2]["data"]["event_ts"])
    second_start = parse_ts(second[0]["data"]["event_ts"])
    assert second_start - first_end == timedelta(seconds=5)
    assert first[0]["data"]["setpoints"] != second[0]["data"]["setpoints"]

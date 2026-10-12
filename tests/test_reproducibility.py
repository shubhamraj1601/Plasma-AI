"""Same seed + same start gives byte-identical files; a different seed gives different values."""

from __future__ import annotations

from pathlib import Path

from conftest import read_lines, run_dirs, run_generator


def _files(out: Path) -> dict[str, bytes]:
    return {str(p.relative_to(out)): p.read_bytes() for p in sorted(out.rglob("*.jsonl"))}


def test_same_seed_is_byte_identical(tmp_path: Path) -> None:
    a = _files(run_generator(tmp_path / "a", "--runs", "2", "--duration-s", "2", "--seed", "42"))
    b = _files(run_generator(tmp_path / "b", "--runs", "2", "--duration-s", "2", "--seed", "42"))
    assert len(a) == 4
    assert a == b


def test_different_seed_differs(tmp_path: Path) -> None:
    a = run_generator(tmp_path / "a", "--duration-s", "2", "--seed", "42")
    b = run_generator(tmp_path / "b", "--duration-s", "2", "--seed", "43")
    rec_a = read_lines(run_dirs(a)[0] / "process-ts.jsonl")
    rec_b = read_lines(run_dirs(b)[0] / "process-ts.jsonl")
    assert rec_a[0]["data"]["setpoints"] != rec_b[0]["data"]["setpoints"]
    assert rec_a[1]["data"]["power_kw"] != rec_b[1]["data"]["power_kw"]
    assert rec_a[1]["data"]["message_id"] != rec_b[1]["data"]["message_id"]
    oes_a = (run_dirs(a)[0] / "oes-spectra.jsonl").read_bytes()
    oes_b = (run_dirs(b)[0] / "oes-spectra.jsonl").read_bytes()
    assert oes_a != oes_b


def test_seed_recorded_in_run_start(tmp_path: Path) -> None:
    out = run_generator(tmp_path, "--duration-s", "1", "--seed", "42")
    assert read_lines(run_dirs(out)[0] / "process-ts.jsonl")[0]["data"]["generator_seed"] == 42

"""Shared helpers: run the generator CLI into a temp folder and read the output back."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from plasma_ai.generator.__main__ import main

REPO = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO / "config" / "generator.yaml"
START_TS = "2026-10-12T05:00:00Z"


def run_generator(out: Path, *args: str) -> Path:
    """Run the CLI with the repo config, a fixed start time and `args`; returns the out folder."""
    code = main(["--config", str(CONFIG_PATH), "--start-ts", START_TS, "--out", str(out), *args])
    assert code == 0
    return out


def _reject_constant(name: str) -> Any:
    raise AssertionError(f"non-JSON constant {name} in output")


def read_lines(path: Path) -> list[dict]:
    """Parse a JSONL file, failing on NaN or Infinity."""
    with path.open(encoding="utf-8") as f:
        return [json.loads(line, parse_constant=_reject_constant) for line in f]


def run_dirs(out: Path) -> list[Path]:
    """Run folders in an output folder, sorted by run_id."""
    return sorted(p for p in out.iterdir() if p.is_dir())


@pytest.fixture(scope="session")
def raw_config() -> dict:
    """The repo config as a plain dict, for tests that tweak a value."""
    with CONFIG_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f)

"""--reference-run --no-noise reproduces slide 3 (RUN-042) within 1 %."""

from __future__ import annotations

import pytest

from conftest import read_lines, run_dirs, run_generator

SIGNALS = {
    "power_kw": 1.85,
    "ch4_slpm": 12.0,
    "h2_slpm": 2.0,
    "pressure_kpa": 85.0,
    "reflected_power_w": 110.0,
    "re_z_ohm": 34.0,
    "im_z_ohm": 11.0,
    "gas_temperature_k": 2220.0,
}
PLASMA_STATE = {"ne_cm3": 3.1e14, "te_ev": 2.9, "stability_index": 0.96, "carbon_growth_index": 0.81}
OUTCOMES = {
    "graphite_yield_percent": 68.0,
    "raman_id_ig": 0.22,
    "xrd_002_fwhm_deg": 0.38,
    "h2_purity_percent": 99.2,
}


@pytest.fixture(scope="module")
def process_records(tmp_path_factory: pytest.TempPathFactory) -> list[dict]:
    out = run_generator(tmp_path_factory.mktemp("ref"), "--reference-run", "--no-noise", "--duration-s", "2", "--seed", "1")
    return [r["data"] for r in read_lines(run_dirs(out)[0] / "process-ts.jsonl")]


def _close(actual: float, expected: float) -> bool:
    return actual == pytest.approx(expected, rel=0.01)


def test_setpoints_in_run_start(process_records: list[dict]) -> None:
    (start,) = [r for r in process_records if r["message_type"] == "run_start"]
    assert start["setpoints"] == {"power_kw": 1.85, "ch4_slpm": 12.0, "h2_slpm": 2.0, "pressure_kpa": 85.0}


@pytest.mark.parametrize("field", SIGNALS)
def test_signals(process_records: list[dict], field: str) -> None:
    samples = [r for r in process_records if r["message_type"] == "process_sample"]
    assert samples
    assert all(_close(s[field], SIGNALS[field]) for s in samples), field


@pytest.mark.parametrize("field", PLASMA_STATE)
def test_plasma_state(process_records: list[dict], field: str) -> None:
    samples = [r for r in process_records if r["message_type"] == "process_sample"]
    assert all(_close(s["plasma_state"][field], PLASMA_STATE[field]) for s in samples), field


@pytest.mark.parametrize("field", OUTCOMES)
def test_outcomes(process_records: list[dict], field: str) -> None:
    (outcome,) = [r for r in process_records if r["message_type"] == "run_outcome"]
    assert _close(outcome[field], OUTCOMES[field])


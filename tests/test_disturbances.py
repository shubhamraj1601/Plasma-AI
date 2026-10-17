"""Day 8 disturbances: dropouts, drift, publish delay and missing messages (seq_no gaps)."""

from __future__ import annotations

import copy
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
import yaml

from conftest import CONFIG_PATH, START_TS, read_lines, run_dirs
from plasma_ai.config import PROCESS_SIGNALS, ConfigError, GeneratorConfig, config_from_dict
from plasma_ai.generator.__main__ import main
from plasma_ai.generator.run import RunSpec, generate_run
from plasma_ai.impairments import Impairments
from plasma_ai.messages import parse_ts
from plasma_ai.validate import MessageValidator


def _config(raw_config: dict, **switches: bool) -> GeneratorConfig:
    """Repo config with the named disturbances switched on or off."""
    raw = copy.deepcopy(raw_config)
    for name, enabled in switches.items():
        raw["disturbances"][name]["enabled"] = enabled
    return config_from_dict(raw)


def _all_on(raw_config: dict) -> GeneratorConfig:
    return _config(raw_config, publish_delay=True, drift=True, dropout=True, missing_messages=True)


def _run(cfg: GeneratorConfig, seed: int, duration_s: float = 20.0) -> tuple[list[dict], Impairments]:
    rng = np.random.default_rng(seed)
    impairments = Impairments(cfg.disturbances, rng)
    spec = RunSpec(
        run_id="SYN-20261012-050000-001",
        start=datetime(2026, 10, 12, 5, tzinfo=timezone.utc),
        duration_s=duration_s,
        setpoints=cfg.reference_run,
        oes_mode="lines",
        noise=True,
        seed=seed,
    )
    return [r.data for r in generate_run(cfg, spec, rng, impairments)], impairments


def test_repo_config_has_every_disturbance_off(raw_config: dict) -> None:
    cfg = config_from_dict(raw_config)
    d = cfg.disturbances
    assert not (d.publish_delay.enabled or d.drift.enabled or d.dropout.enabled or d.missing_messages.enabled)


def test_disabled_disturbances_draw_nothing(raw_config: dict) -> None:
    rng = np.random.default_rng(1)
    impairments = Impairments(config_from_dict(raw_config).disturbances, rng)
    state = rng.bit_generator.state
    assert impairments.publish_delay_us("process_sample") == 0
    assert impairments.drift("pressure_kpa", 85.0, 3600.0) == 85.0
    assert not impairments.dropout("power_kw")
    assert not impairments.drop("process_sample")
    assert rng.bit_generator.state == state


def test_dropout_rate_within_tolerance(raw_config: dict) -> None:
    raw = copy.deepcopy(raw_config)
    raw["disturbances"]["dropout"] = {"enabled": True, "null_prob": {"power_kw": 0.1, "pressure_kpa": 0.02}}
    impairments = Impairments(config_from_dict(raw).disturbances, np.random.default_rng(5))
    n = 20_000
    for signal, prob in (("power_kw", 0.1), ("pressure_kpa", 0.02)):
        rate = sum(impairments.dropout(signal) for _ in range(n)) / n
        sigma = (prob * (1 - prob) / n) ** 0.5
        assert abs(rate - prob) < 4 * sigma, (signal, rate)
    assert not any(impairments.dropout("h2_slpm") for _ in range(1000))  # not listed: never null


def test_dropouts_appear_as_null_readings_in_a_run(raw_config: dict) -> None:
    cfg = _config(raw_config, dropout=True)
    messages, impairments = _run(cfg, seed=2, duration_s=60.0)
    samples = [m for m in messages if m["message_type"] == "process_sample"]
    for signal in PROCESS_SIGNALS:
        nulls = sum(s[signal] is None for s in samples)
        prob = cfg.disturbances.dropout.null_prob.get(signal, 0.0)
        assert nulls == impairments.stats[f"null.{signal}"]
        if prob == 0:
            assert nulls == 0, signal
        else:
            assert abs(nulls / len(samples) - prob) < 4 * (prob * (1 - prob) / len(samples)) ** 0.5, signal
    assert all(s["plasma_state"] is not None for s in samples)


def test_drift_direction(raw_config: dict) -> None:
    cfg = _config(raw_config, drift=True)
    impairments = Impairments(cfg.disturbances, np.random.default_rng(0))
    rates = cfg.disturbances.drift.rel_per_hour
    assert rates["pressure_kpa"] > 0 > rates["gas_temperature_k"]
    assert impairments.drift("pressure_kpa", 85.0, 0.0) == 85.0
    assert impairments.drift("pressure_kpa", 85.0, 600.0) > impairments.drift("pressure_kpa", 85.0, 60.0) > 85.0
    assert impairments.drift("gas_temperature_k", 2220.0, 600.0) < 2220.0
    assert impairments.drift("pressure_kpa", 85.0, 3600.0) == pytest.approx(85.0 * (1 + rates["pressure_kpa"]))
    assert impairments.drift("power_kw", 1.85, 3600.0) == 1.85  # not listed: no drift


def test_drift_moves_the_run_mean(raw_config: dict) -> None:
    # Over a 10 min run with noise on, the last minute's mean pressure is above the first minute's,
    # and gas temperature below, by about the configured rate.
    cfg = _config(raw_config, drift=True)
    messages, _ = _run(cfg, seed=4, duration_s=600.0)
    samples = [m for m in messages if m["message_type"] == "process_sample"]
    first, last = samples[:600], samples[-600:]
    for signal in ("pressure_kpa", "gas_temperature_k"):
        start = np.mean([s[signal] for s in first])
        end = np.mean([s[signal] for s in last])
        expected = cfg.disturbances.drift.rel_per_hour[signal] * 9 / 60  # 9 min between the window centres
        assert (end / start - 1) == pytest.approx(expected, abs=0.002), signal


def test_publish_delay(raw_config: dict) -> None:
    cfg = _config(raw_config, publish_delay=True)
    delay = cfg.disturbances.publish_delay
    messages, _ = _run(cfg, seed=3)
    delays_ms = [(parse_ts(m["publish_ts"]) - parse_ts(m["event_ts"])).total_seconds() * 1000 for m in messages]
    assert min(delays_ms) >= delay.min_ms
    assert np.mean(delays_ms) == pytest.approx(delay.min_ms + delay.mean_extra_ms, rel=0.15)
    assert len(set(delays_ms)) > len(delays_ms) / 2  # jittered, not constant


def test_missing_messages_leave_seq_no_gaps(raw_config: dict) -> None:
    raw = copy.deepcopy(raw_config)
    raw["disturbances"]["missing_messages"] = {"enabled": True, "prob": {"process_sample": 0.05, "oes_block": 0.05}}
    messages, impairments = _run(config_from_dict(raw), seed=6, duration_s=60.0)
    seqs: defaultdict[str, list[int]] = defaultdict(list)
    for m in messages:
        seqs[m["message_type"]].append(m["seq_no"])
    for message_type in ("process_sample", "oes_block"):
        values = seqs[message_type]
        assert values == sorted(set(values)), message_type  # strictly increasing
        missing = 600 - len(values)
        assert missing == impairments.stats[f"missing.{message_type}"]
        assert missing == len(set(range(600)) - set(values))
        assert 0.02 * 600 < missing < 0.08 * 600, message_type
    for message_type in ("run_start", "run_end", "run_outcome"):
        assert seqs[message_type] == [0]


def test_every_message_validates_with_all_disturbances_on(raw_config: dict) -> None:
    messages, impairments = _run(_all_on(raw_config), seed=8)
    validator = MessageValidator()
    for m in messages:
        validator.validate(m)
    assert impairments.stats  # something was actually disturbed


def _write_config(tmp_path: Path, raw: dict) -> Path:
    path = tmp_path / "generator.yaml"
    with path.open("w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(raw, f)
    return path


def test_reference_run_no_noise_is_exact_with_all_disturbances_on(raw_config: dict, tmp_path: Path) -> None:
    raw = copy.deepcopy(raw_config)
    for name in raw["disturbances"]:
        raw["disturbances"][name]["enabled"] = True
    args = ["--start-ts", START_TS, "--reference-run", "--no-noise", "--duration-s", "5", "--seed", "1"]
    assert main(["--config", str(_write_config(tmp_path, raw)), "--out", str(tmp_path / "on"), *args]) == 0
    assert main(["--config", str(CONFIG_PATH), "--out", str(tmp_path / "off"), *args]) == 0
    (on,), (off,) = run_dirs(tmp_path / "on"), run_dirs(tmp_path / "off")
    for name in ("process-ts.jsonl", "oes-spectra.jsonl"):
        assert (on / name).read_bytes() == (off / name).read_bytes()
    records = [r["data"] for r in read_lines(on / "process-ts.jsonl")]
    sample = next(r for r in records if r["message_type"] == "process_sample")
    outcome = next(r for r in records if r["message_type"] == "run_outcome")
    assert (sample["pressure_kpa"], sample["gas_temperature_k"], sample["reflected_power_w"]) == (85.0, 2220.0, 110.0)
    assert round(outcome["h2_purity_percent"], 2) == 99.20
    assert round(outcome["graphite_yield_percent"], 2) == 68.00
    assert all(r["publish_ts"] == r["event_ts"] for r in records)


@pytest.mark.parametrize(
    ("section", "value", "message"),
    [
        ("drift", {"enabled": True, "rel_per_hour": {"presure_kpa": 0.1}}, "unknown signal"),
        ("dropout", {"enabled": True, "null_prob": {"power_kw": 1.5}}, r"\[0, 1\]"),
        ("missing_messages", {"enabled": True, "prob": {"run_start": 0.1}}, "unknown type"),
        ("publish_delay", {"enabled": True, "min_ms": -1, "mean_extra_ms": 0}, "min_ms"),
        ("publish_delay", {"enabled": "yes", "min_ms": 0, "mean_extra_ms": 0}, "true or false"),
    ],
)
def test_invalid_disturbance_config_fails(raw_config: dict, section: str, value: dict, message: str) -> None:
    raw = copy.deepcopy(raw_config)
    raw["disturbances"][section] = value
    with pytest.raises(ConfigError, match=message):
        config_from_dict(raw)

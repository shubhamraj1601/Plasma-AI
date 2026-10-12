"""Generate one reactor run end to end as a time-ordered stream of records."""

from __future__ import annotations

import heapq
import math
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from plasma_ai.config import PROCESS_SIGNALS, GeneratorConfig, Setpoints, SweepConfig
from plasma_ai.impairments import Impairments
from plasma_ai.messages import MessageFactory, Record
from plasma_ai.oes import OesModel
from plasma_ai.physics_placeholder import Outcomes, plasma_state, run_outcomes

_PERCENT_OUTCOMES = ("graphite_yield_percent", "h2_purity_percent")


@dataclass(frozen=True)
class RunSpec:
    """Everything that defines one run."""

    run_id: str
    start: datetime
    duration_s: float
    setpoints: Setpoints
    oes_mode: str
    noise: bool
    seed: int | None


def make_run_id(prefix: str, start: datetime, number: int) -> str:
    """`{prefix}{YYYYMMDD}-{nnn}` with the run's UTC start date."""
    return f"{prefix}{start:%Y%m%d}-{number:03d}"


def sample_setpoints(sweep: SweepConfig, rng: np.random.Generator) -> Setpoints:
    """Draw each setpoint uniformly from its sweep range."""
    return Setpoints(
        power_kw=float(rng.uniform(sweep.power_kw.low, sweep.power_kw.high)),
        ch4_slpm=float(rng.uniform(sweep.ch4_slpm.low, sweep.ch4_slpm.high)),
        h2_slpm=float(rng.uniform(sweep.h2_slpm.low, sweep.h2_slpm.high)),
        pressure_kpa=float(rng.uniform(sweep.pressure_kpa.low, sweep.pressure_kpa.high)),
    )


def _whole(x: float) -> int:
    """Floor that tolerates float error (e.g. 10 s * 10 Hz = 99.99999...)."""
    return int(math.floor(x + 1e-9))


def _offset(seconds: float) -> timedelta:
    return timedelta(microseconds=round(seconds * 1_000_000))


def generate_run(
    cfg: GeneratorConfig,
    spec: RunSpec,
    rng: np.random.Generator,
    impairments: Impairments,
) -> Iterator[Record]:
    """Yield run_start, then process samples and OES blocks merged by event_ts, then run_end and run_outcome."""
    factory = MessageFactory(cfg, spec.run_id, rng, impairments)
    sp = spec.setpoints
    # Setpoints are constant within a run in v1, so the true state is too.
    state = plasma_state(sp, cfg.physics)
    oes_model = OesModel(cfg.oes, cfg.physics, spec.oes_mode)

    def emit(message_type: str, event_ts: datetime, payload: dict) -> Iterator[Record]:
        record = factory.build(message_type, event_ts, payload)
        if not impairments.drop(message_type):
            yield record

    def process_samples() -> Iterator[Record]:
        true_values = {
            "power_kw": sp.power_kw,
            "reflected_power_w": state.reflected_power_w,
            "ch4_slpm": sp.ch4_slpm,
            "h2_slpm": sp.h2_slpm,
            "pressure_kpa": sp.pressure_kpa,
            "re_z_ohm": state.re_z_ohm,
            "im_z_ohm": state.im_z_ohm,
            "gas_temperature_k": state.gas_temperature_k,
        }
        true = np.array([true_values[name] for name in PROCESS_SIGNALS])
        sigma = np.array([cfg.process.noise_rel_sigma[name] for name in PROCESS_SIGNALS])
        for i in range(_whole(spec.duration_s * cfg.process.sampling_hz)):
            elapsed_s = i / cfg.process.sampling_hz
            measured = true * (1 + sigma * rng.standard_normal(sigma.size)) if spec.noise else true
            payload: dict = {
                name: impairments.drift(name, float(value), elapsed_s)
                for name, value in zip(PROCESS_SIGNALS, measured)
            }
            payload["plasma_state"] = state.labels()
            yield from emit("process_sample", spec.start + _offset(elapsed_s), payload)

    def oes_blocks() -> Iterator[Record]:
        oes = cfg.oes
        block_s = oes.frames_per_message / oes.sampling_hz
        true_frame = oes_model.true_frame(state, sp)
        for k in range(_whole(spec.duration_s / block_s)):
            block = oes_model.measure(true_frame, rng, spec.noise)
            payload = {
                "spectrometer_id": oes.spectrometer_id,
                "oes_config_id": oes_model.config_id,
                "mode": spec.oes_mode,
                "frame_count": oes.frames_per_message,
                "frame_interval_us": oes.frame_interval_us,
                "integration_time_ms": oes.integration_time_ms,
                "intensities": block.frames.ravel().tolist(),
                "saturated": block.saturated,
            }
            yield from emit("oes_block", spec.start + _offset(k * block_s), payload)

    end_ts = spec.start + _offset(spec.duration_s)
    yield from emit(
        "run_start",
        spec.start,
        {
            "setpoints": sp.as_dict(),
            "oes_config_id": oes_model.config_id,
            "generator_seed": spec.seed,
            "duration_s": spec.duration_s,
        },
    )
    yield from heapq.merge(process_samples(), oes_blocks(), key=lambda r: r.data["event_ts"])
    yield from emit("run_end", end_ts, {"end_reason": "completed"})
    outcomes = _measured_outcomes(run_outcomes(state, sp, cfg.physics), cfg.outcomes.noise_rel_sigma, rng, spec.noise)
    yield from emit("run_outcome", end_ts + _offset(cfg.run.outcome_delay_s), outcomes)


def _measured_outcomes(true: Outcomes, rel_sigma: float, rng: np.random.Generator, noise: bool) -> dict[str, float]:
    """Apply one relative Gaussian draw per outcome; percentages stay within [0, 100]."""
    values = true.as_dict()
    if not noise:
        return values
    measured = {}
    for name, value in values.items():
        v = value * (1 + rel_sigma * float(rng.standard_normal()))
        measured[name] = min(max(v, 0.0), 100.0) if name in _PERCENT_OUTCOMES else v
    return measured

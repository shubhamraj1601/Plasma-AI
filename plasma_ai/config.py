"""Load config/generator.yaml into typed dataclasses and validate it.

Unknown or missing keys are rejected so typos fail at load time, not mid-run.
"""

from __future__ import annotations

import dataclasses
import math
import types
import typing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

MESSAGE_TYPES = ("run_start", "process_sample", "run_end", "run_outcome", "oes_block", "dead_letter")
PROCESS_SIGNALS = (
    "power_kw",
    "reflected_power_w",
    "ch4_slpm",
    "h2_slpm",
    "pressure_kpa",
    "re_z_ohm",
    "im_z_ohm",
    "gas_temperature_k",
)
OES_MODES = ("lines", "full")
OES_DRIVERS = ("h_beta", "c2", "continuum")


class ConfigError(ValueError):
    """Raised when the generator config is missing keys or holds invalid values."""


@dataclass(frozen=True)
class Range:
    """Closed interval [low, high] used for sweep ranges."""

    low: float
    high: float


@dataclass(frozen=True)
class Setpoints:
    """Reactor setpoints for one run (constant within a run in v1)."""

    power_kw: float
    ch4_slpm: float
    h2_slpm: float
    pressure_kpa: float

    def as_dict(self) -> dict[str, float]:
        """Return the setpoints as a plain dict for message payloads."""
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class RunConfig:
    id_prefix: str
    gap_s: float
    outcome_delay_s: float


@dataclass(frozen=True)
class ProcessConfig:
    sampling_hz: float
    noise_rel_sigma: dict[str, float]


@dataclass(frozen=True)
class OutcomesConfig:
    noise_rel_sigma: float


@dataclass(frozen=True)
class SweepConfig:
    power_kw: Range
    ch4_slpm: Range
    h2_slpm: Range
    pressure_kpa: Range


@dataclass(frozen=True)
class PowerPressureLaw:
    """base * (P/P0)^power_exp * (p/p0)^pressure_exp."""

    base: float
    power_exp: float
    pressure_exp: float


@dataclass(frozen=True)
class ReflectedPowerCoef:
    base: float
    pressure_dev_coef: float


@dataclass(frozen=True)
class ReZCoef:
    base: float
    ne_exp: float


@dataclass(frozen=True)
class ImZCoef:
    base: float
    pressure_exp: float


@dataclass(frozen=True)
class StabilityCoef:
    reflected_coef: float
    pressure_dev_coef: float


@dataclass(frozen=True)
class CarbonGrowthCoef:
    base: float
    x_exp: float
    te_exp: float
    stability_ref: float


@dataclass(frozen=True)
class CgiOutcomeCoef:
    base: float
    cgi_exp: float


@dataclass(frozen=True)
class XrdCoef:
    base: float
    tgas_exp: float


@dataclass(frozen=True)
class H2PurityCoef:
    impurity_base: float
    ne_exp: float
    x_exp: float


@dataclass(frozen=True)
class PhysicsConfig:
    """Placeholder physics coefficients (CLAUDE.md section 8)."""

    ref: Setpoints
    ne_cm3: PowerPressureLaw
    te_ev: PowerPressureLaw
    gas_temperature_k: PowerPressureLaw
    reflected_power_w: ReflectedPowerCoef
    re_z_ohm: ReZCoef
    im_z_ohm: ImZCoef
    stability_index: StabilityCoef
    carbon_growth_index: CarbonGrowthCoef
    graphite_yield_percent: CgiOutcomeCoef
    raman_id_ig: CgiOutcomeCoef
    xrd_002_fwhm_deg: XrdCoef
    h2_purity_percent: H2PurityCoef


@dataclass(frozen=True)
class OesConfigIds:
    lines: str
    full: str


@dataclass(frozen=True)
class OesFullConfig:
    n_bins: int
    wavelength_range_nm: Range
    line_fwhm_nm: float
    continuum_counts: float


@dataclass(frozen=True)
class OesConfig:
    mode: str
    spectrometer_id: str
    sampling_hz: float
    frames_per_message: int
    integration_time_ms: float
    saturation_counts: float
    dark_noise_counts: float
    shot_noise_rel: float
    lines_nm: list[float]
    line_amplitude_counts: list[float]
    line_driver: list[str]
    continuum_temp_exp: float
    config_id: OesConfigIds
    full: OesFullConfig

    @property
    def frame_interval_us(self) -> int:
        """Microseconds between frames (1 000 000 / sampling_hz)."""
        return round(1_000_000 / self.sampling_hz)


@dataclass(frozen=True)
class ReactorConfig:
    volume_m3: float | None


@dataclass(frozen=True)
class WindowConfig:
    samples: int


@dataclass(frozen=True)
class GeneratorConfig:
    """Whole generator config, mirroring config/generator.yaml."""

    schema_version: str
    reactor_id: str
    source: str
    run: RunConfig
    topics: dict[str, str]
    process: ProcessConfig
    outcomes: OutcomesConfig
    sweep: SweepConfig
    reference_run: Setpoints
    physics: PhysicsConfig
    oes: OesConfig
    reactor: ReactorConfig
    window: WindowConfig


def load_config(path: Path | str) -> GeneratorConfig:
    """Read and validate a generator YAML file."""
    path = Path(path)
    try:
        with path.open(encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except OSError as exc:
        raise ConfigError(f"cannot read config file {path}: {exc}") from exc
    return config_from_dict(raw)


def config_from_dict(raw: Any) -> GeneratorConfig:
    """Build and validate a GeneratorConfig from an already-parsed mapping."""
    cfg = _build(GeneratorConfig, raw, "config")
    _check(cfg)
    return cfg


def _build(tp: Any, value: Any, where: str) -> Any:
    """Convert a parsed YAML value into the annotated type `tp`, failing with the key path."""
    origin = typing.get_origin(tp)
    if origin in (typing.Union, types.UnionType):
        options = typing.get_args(tp)
        if value is None and type(None) in options:
            return None
        (inner,) = [o for o in options if o is not type(None)]
        return _build(inner, value, where)
    if tp is Range:
        if not isinstance(value, list) or len(value) != 2:
            raise ConfigError(f"{where}: expected [low, high], got {value!r}")
        return Range(_build(float, value[0], f"{where}[0]"), _build(float, value[1], f"{where}[1]"))
    if dataclasses.is_dataclass(tp):
        if not isinstance(value, dict):
            raise ConfigError(f"{where}: expected a mapping, got {value!r}")
        hints = typing.get_type_hints(tp)
        names = [f.name for f in dataclasses.fields(tp)]
        missing = [n for n in names if n not in value]
        unknown = [k for k in value if k not in names]
        if missing:
            raise ConfigError(f"{where}: missing key(s) {missing}")
        if unknown:
            raise ConfigError(f"{where}: unknown key(s) {unknown}")
        return tp(**{n: _build(hints[n], value[n], f"{where}.{n}") for n in names})
    if origin is list:
        (item,) = typing.get_args(tp)
        if not isinstance(value, list):
            raise ConfigError(f"{where}: expected a list, got {value!r}")
        return [_build(item, v, f"{where}[{i}]") for i, v in enumerate(value)]
    if origin is dict:
        _, item = typing.get_args(tp)
        if not isinstance(value, dict):
            raise ConfigError(f"{where}: expected a mapping, got {value!r}")
        return {str(k): _build(item, v, f"{where}.{k}") for k, v in value.items()}
    if tp is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ConfigError(f"{where}: expected a finite number, got {value!r}")
        return float(value)
    if tp is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"{where}: expected an integer, got {value!r}")
        return value
    if tp is str:
        if not isinstance(value, str) or not value:
            raise ConfigError(f"{where}: expected a non-empty string, got {value!r}")
        return value
    raise TypeError(f"unsupported config type {tp!r} at {where}")


def _check(cfg: GeneratorConfig) -> None:
    """Semantic checks that a type conversion alone cannot catch."""
    errors: list[str] = []

    def need(ok: bool, msg: str) -> None:
        if not ok:
            errors.append(msg)

    need(cfg.schema_version == "0.1", f"schema_version must be '0.1', got {cfg.schema_version!r}")
    need(cfg.run.gap_s >= 0, "run.gap_s must be >= 0")
    need(cfg.run.outcome_delay_s >= 0, "run.outcome_delay_s must be >= 0")
    need(set(cfg.topics) == set(MESSAGE_TYPES), f"topics must map exactly these message types: {list(MESSAGE_TYPES)}")

    need(cfg.process.sampling_hz > 0, "process.sampling_hz must be > 0")
    need(
        set(cfg.process.noise_rel_sigma) == set(PROCESS_SIGNALS),
        f"process.noise_rel_sigma must list exactly: {list(PROCESS_SIGNALS)}",
    )
    need(all(s >= 0 for s in cfg.process.noise_rel_sigma.values()), "process.noise_rel_sigma values must be >= 0")
    need(cfg.outcomes.noise_rel_sigma >= 0, "outcomes.noise_rel_sigma must be >= 0")

    for name in ("power_kw", "ch4_slpm", "h2_slpm", "pressure_kpa"):
        rng: Range = getattr(cfg.sweep, name)
        need(0 < rng.low < rng.high, f"sweep.{name} must satisfy 0 < low < high, got [{rng.low}, {rng.high}]")
        need(getattr(cfg.reference_run, name) > 0, f"reference_run.{name} must be > 0")
        need(getattr(cfg.physics.ref, name) > 0, f"physics.ref.{name} must be > 0")

    oes = cfg.oes
    need(oes.mode in OES_MODES, f"oes.mode must be one of {list(OES_MODES)}, got {oes.mode!r}")
    need(oes.sampling_hz > 0, "oes.sampling_hz must be > 0")
    if oes.sampling_hz > 0:
        interval = 1_000_000 / oes.sampling_hz
        need(abs(interval - round(interval)) < 1e-9, "oes.sampling_hz must give a whole number of microseconds per frame")
    need(oes.frames_per_message >= 1, "oes.frames_per_message must be >= 1")
    need(oes.integration_time_ms > 0, "oes.integration_time_ms must be > 0")
    need(oes.saturation_counts > 0, "oes.saturation_counts must be > 0")
    need(oes.dark_noise_counts >= 0, "oes.dark_noise_counts must be >= 0")
    need(oes.shot_noise_rel >= 0, "oes.shot_noise_rel must be >= 0")
    need(len(oes.lines_nm) > 0, "oes.lines_nm must not be empty")
    need(
        len(oes.lines_nm) == len(oes.line_amplitude_counts) == len(oes.line_driver),
        "oes.lines_nm, oes.line_amplitude_counts and oes.line_driver must have the same length",
    )
    bad_drivers = sorted(set(oes.line_driver) - set(OES_DRIVERS))
    need(not bad_drivers, f"oes.line_driver has unknown driver(s) {bad_drivers}; allowed {list(OES_DRIVERS)}")
    need(all(a >= 0 for a in oes.line_amplitude_counts), "oes.line_amplitude_counts must be >= 0")
    need(2048 <= oes.full.n_bins <= 4096, f"oes.full.n_bins must be in 2048-4096, got {oes.full.n_bins}")
    wl = oes.full.wavelength_range_nm
    need(0 < wl.low < wl.high, "oes.full.wavelength_range_nm must satisfy 0 < low < high")
    need(oes.full.line_fwhm_nm > 0, "oes.full.line_fwhm_nm must be > 0")
    need(oes.full.continuum_counts >= 0, "oes.full.continuum_counts must be >= 0")

    need(cfg.reactor.volume_m3 is None or cfg.reactor.volume_m3 > 0, "reactor.volume_m3 must be null or > 0")
    need(cfg.window.samples >= 1, "window.samples must be >= 1")

    if errors:
        raise ConfigError("invalid generator config:\n  - " + "\n  - ".join(errors))

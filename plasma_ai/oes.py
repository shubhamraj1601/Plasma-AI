"""Placeholder OES model: frames of line intensities (lines mode) or spectra (full mode).

Line intensities are driven by the true plasma state (CLAUDE.md section 9,
"OES model"). Specair, LIFBASE and PGOPHER are out of scope (Q12).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from plasma_ai.config import OES_MODES, OesConfig, PhysicsConfig, Setpoints
from plasma_ai.physics_placeholder import PlasmaState, methane_fraction


@dataclass(frozen=True)
class OesBlock:
    """One block of measured frames, shape (frame_count, channels), plus the saturation flag."""

    frames: np.ndarray
    saturated: bool


class OesModel:
    """Turns a plasma state into true and measured OES frames for one mode."""

    def __init__(self, oes: OesConfig, physics: PhysicsConfig, mode: str) -> None:
        if mode not in OES_MODES:
            raise ValueError(f"OES mode must be one of {list(OES_MODES)}, got {mode!r}")
        self.oes = oes
        self.physics = physics
        self.mode = mode
        self._amplitudes = np.asarray(oes.line_amplitude_counts, dtype=float)
        if mode == "full":
            wl = oes.full.wavelength_range_nm
            self.wavelengths_nm = np.linspace(wl.low, wl.high, oes.full.n_bins)
            sigma = oes.full.line_fwhm_nm / (2 * math.sqrt(2 * math.log(2)))
            centres = np.asarray(oes.lines_nm, dtype=float)[:, None]
            # Unit-height Gaussian profile of each line over all bins, shape (lines, bins).
            self._profiles = np.exp(-0.5 * ((self.wavelengths_nm[None, :] - centres) / sigma) ** 2)

    @property
    def channels(self) -> int:
        """Values per frame: number of lines, or number of bins in full mode."""
        return len(self.oes.lines_nm) if self.mode == "lines" else self.oes.full.n_bins

    @property
    def config_id(self) -> str:
        """oes_config_id for this mode, from config."""
        return self.oes.config_id.lines if self.mode == "lines" else self.oes.config_id.full

    def _continuum_driver(self, state: PlasmaState) -> float:
        return (state.gas_temperature_k / self.physics.gas_temperature_k.base) ** self.oes.continuum_temp_exp

    def line_drivers(self, state: PlasmaState, setpoints: Setpoints) -> np.ndarray:
        """Relative driver of each configured line (1.0 at the reference run)."""
        x = methane_fraction(setpoints)
        x0 = methane_fraction(self.physics.ref)
        values = {
            "h_beta": (1 - x) / (1 - x0) * (state.ne_cm3 / self.physics.ne_cm3.base),
            "c2": (x / x0) * (state.te_ev / self.physics.te_ev.base),
            "continuum": self._continuum_driver(state),
        }
        return np.array([values[d] for d in self.oes.line_driver], dtype=float)

    def true_frame(self, state: PlasmaState, setpoints: Setpoints) -> np.ndarray:
        """Noise-free intensities (counts) of one frame, shape (channels,)."""
        lines = self._amplitudes * self.line_drivers(state, setpoints)
        if self.mode == "lines":
            return lines
        continuum = self.oes.full.continuum_counts * self._continuum_driver(state)
        return continuum + lines @ self._profiles

    def measure(self, true_frame: np.ndarray, rng: np.random.Generator, noise: bool) -> OesBlock:
        """Add dark and shot noise per frame, clip to [0, saturation] and round to 0.1 count.

        Dark noise N(0, dark) and shot noise N(0, shot_rel * true) are independent,
        so they are drawn as one Gaussian with the combined sigma.
        """
        shape = (self.oes.frames_per_message, true_frame.size)
        raw = np.broadcast_to(true_frame, shape)
        if noise:
            sigma = np.sqrt(self.oes.dark_noise_counts**2 + (self.oes.shot_noise_rel * true_frame) ** 2)
            raw = raw + rng.standard_normal(shape) * sigma
        saturation = self.oes.saturation_counts
        saturated = bool(np.any(raw >= saturation))
        frames = np.round(np.clip(raw, 0.0, saturation), 1)
        return OesBlock(frames=frames, saturated=saturated)

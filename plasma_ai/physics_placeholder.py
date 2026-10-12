"""Placeholder physics: setpoints -> plasma state -> product outcomes.

Assumption Q8. Every coefficient comes from `physics:` in the config and is a
placeholder chosen so the reference run (slide 3, RUN-042) is reproduced.
This module is the single swap point for the D2.3 model: callers use only
`plasma_state` and `run_outcomes`.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from plasma_ai.config import PhysicsConfig, PowerPressureLaw, Setpoints

# Standard conditions behind "SLPM" (0 degC, 1 atm), used only for residence time.
_STD_TEMPERATURE_K = 273.15
_STD_PRESSURE_KPA = 101.325


@dataclass(frozen=True)
class PlasmaState:
    """True (noise-free) plasma state plus the sensor signals derived from it."""

    ne_cm3: float
    te_ev: float
    stability_index: float
    carbon_growth_index: float
    gas_temperature_k: float
    reflected_power_w: float
    re_z_ohm: float
    im_z_ohm: float

    def labels(self) -> dict[str, float]:
        """Ground-truth labels carried in process_sample.plasma_state."""
        return {
            "ne_cm3": self.ne_cm3,
            "te_ev": self.te_ev,
            "stability_index": self.stability_index,
            "carbon_growth_index": self.carbon_growth_index,
        }


@dataclass(frozen=True)
class Outcomes:
    """Per-run product outcomes (run_outcome payload)."""

    graphite_yield_percent: float
    raman_id_ig: float
    xrd_002_fwhm_deg: float
    h2_purity_percent: float

    def as_dict(self) -> dict[str, float]:
        """Return the outcomes as a plain dict for the message payload."""
        return dataclasses.asdict(self)


def methane_fraction(setpoints: Setpoints) -> float:
    """x = Q_CH4 / (Q_CH4 + Q_H2)."""
    return setpoints.ch4_slpm / (setpoints.ch4_slpm + setpoints.h2_slpm)


def _clip(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def plasma_state(setpoints: Setpoints, params: PhysicsConfig) -> PlasmaState:
    """Map setpoints to the true plasma state and derived signals."""
    ref = params.ref
    p_rel = setpoints.power_kw / ref.power_kw
    pr_rel = setpoints.pressure_kpa / ref.pressure_kpa
    x_rel = methane_fraction(setpoints) / methane_fraction(ref)

    def law(c: PowerPressureLaw) -> float:
        return c.base * p_rel**c.power_exp * pr_rel**c.pressure_exp

    ne = law(params.ne_cm3)
    te = law(params.te_ev)
    t_gas = law(params.gas_temperature_k)
    reflected = params.reflected_power_w.base * p_rel * (
        1 + params.reflected_power_w.pressure_dev_coef * abs(pr_rel - 1)
    )
    re_z = params.re_z_ohm.base * (ne / params.ne_cm3.base) ** params.re_z_ohm.ne_exp
    im_z = params.im_z_ohm.base * pr_rel**params.im_z_ohm.pressure_exp
    stab = params.stability_index
    stability = _clip(
        1 - stab.reflected_coef * reflected / (setpoints.power_kw * 1000) - stab.pressure_dev_coef * abs(pr_rel - 1),
        0.0,
        1.0,
    )
    cgi = params.carbon_growth_index
    carbon_growth = (
        cgi.base * x_rel**cgi.x_exp * (te / params.te_ev.base) ** cgi.te_exp * (stability / cgi.stability_ref)
    )
    return PlasmaState(
        ne_cm3=ne,
        te_ev=te,
        stability_index=stability,
        carbon_growth_index=carbon_growth,
        gas_temperature_k=t_gas,
        reflected_power_w=reflected,
        re_z_ohm=re_z,
        im_z_ohm=im_z,
    )


def run_outcomes(mean_state: PlasmaState, setpoints: Setpoints, params: PhysicsConfig) -> Outcomes:
    """Map the run-average plasma state to noise-free product outcomes."""
    x_rel = methane_fraction(setpoints) / methane_fraction(params.ref)
    cgi_base = params.carbon_growth_index.base
    cgi = mean_state.carbon_growth_index
    y = params.graphite_yield_percent
    r = params.raman_id_ig
    xrd = params.xrd_002_fwhm_deg
    h2 = params.h2_purity_percent
    return Outcomes(
        graphite_yield_percent=_clip(y.base * (cgi / cgi_base) ** y.cgi_exp, 0.0, 100.0),
        raman_id_ig=r.base * (cgi_base / cgi) ** r.cgi_exp,
        xrd_002_fwhm_deg=xrd.base * (params.gas_temperature_k.base / mean_state.gas_temperature_k) ** xrd.tgas_exp,
        h2_purity_percent=_clip(
            100 - h2.impurity_base * (params.ne_cm3.base / mean_state.ne_cm3) ** h2.ne_exp * x_rel**h2.x_exp,
            0.0,
            100.0,
        ),
    )


def power_density_kw_m3(setpoints: Setpoints, volume_m3: float | None) -> float | None:
    """P_d = P / V; None while the reactor volume is unknown (Q9)."""
    if volume_m3 is None:
        return None
    return setpoints.power_kw / volume_m3


def residence_time_ms(setpoints: Setpoints, gas_temperature_k: float, volume_m3: float | None) -> float | None:
    """tau = V / actual volumetric flow; None while the reactor volume is unknown (Q9).

    SLPM is converted to actual flow with the ideal-gas law, assuming SLPM is
    referenced to 0 degC and 1 atm.
    """
    if volume_m3 is None:
        return None
    std_flow_m3_s = (setpoints.ch4_slpm + setpoints.h2_slpm) / 1000 / 60
    actual_flow_m3_s = (
        std_flow_m3_s * (gas_temperature_k / _STD_TEMPERATURE_K) * (_STD_PRESSURE_KPA / setpoints.pressure_kpa)
    )
    return volume_m3 / actual_flow_m3_s * 1000

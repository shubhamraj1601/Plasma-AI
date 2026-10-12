"""Config loading fails clearly on bad input; reactor-volume helpers stay None until Q9."""

from __future__ import annotations

import copy

import pytest

from plasma_ai.config import ConfigError, config_from_dict
from plasma_ai.physics_placeholder import power_density_kw_m3, residence_time_ms


def test_repo_config_loads(raw_config: dict) -> None:
    cfg = config_from_dict(raw_config)
    assert cfg.physics.ne_cm3.base == 3.1e14
    assert cfg.oes.frame_interval_us == 1000
    assert cfg.reactor.volume_m3 is None


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("sweep", "power_kw"), [2.2, 1.5], "sweep.power_kw"),
        (("process", "sampling_hz"), 0, "process.sampling_hz"),
        (("oes", "mode"), "partial", "oes.mode"),
        (("oes", "full", "n_bins"), 1024, "n_bins"),
        (("oes", "line_driver"), ["c2"], "same length"),
        (("physics", "ne_cm3", "base"), "3.1e14", "expected a finite number"),
    ],
)
def test_invalid_values_fail_clearly(raw_config: dict, path: tuple[str, ...], value: object, message: str) -> None:
    raw = copy.deepcopy(raw_config)
    node = raw
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    with pytest.raises(ConfigError, match=message):
        config_from_dict(raw)


def test_unknown_and_missing_keys_fail(raw_config: dict) -> None:
    raw = copy.deepcopy(raw_config)
    raw["oes"]["sampling_hzz"] = 1000
    with pytest.raises(ConfigError, match="unknown key"):
        config_from_dict(raw)
    raw = copy.deepcopy(raw_config)
    del raw["run"]["gap_s"]
    with pytest.raises(ConfigError, match="missing key"):
        config_from_dict(raw)


def test_volume_helpers_none_until_volume_known(raw_config: dict) -> None:
    cfg = config_from_dict(raw_config)
    assert power_density_kw_m3(cfg.reference_run, cfg.reactor.volume_m3) is None
    assert residence_time_ms(cfg.reference_run, 2220.0, cfg.reactor.volume_m3) is None
    assert power_density_kw_m3(cfg.reference_run, 0.001) == pytest.approx(1850.0)

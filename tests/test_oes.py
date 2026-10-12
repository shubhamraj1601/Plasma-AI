"""OES frames: shape, value range, saturation flag and response to gas mix."""

from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pytest

from conftest import read_lines, run_dirs, run_generator
from plasma_ai.config import Setpoints, config_from_dict
from plasma_ai.oes import OesModel
from plasma_ai.physics_placeholder import plasma_state


@pytest.mark.parametrize(("mode", "channels"), [("lines", 8), ("full", 2048)])
def test_intensities_length_and_range(tmp_path: Path, mode: str, channels: int) -> None:
    out = run_generator(tmp_path, "--duration-s", "0.5", "--seed", "9", "--oes-mode", mode)
    blocks = [r["data"] for r in read_lines(run_dirs(out)[0] / "oes-spectra.jsonl")]
    assert len(blocks) == 5
    for b in blocks:
        assert b["mode"] == mode
        assert b["frame_count"] == 100
        assert b["frame_interval_us"] == 1000
        assert len(b["intensities"]) == b["frame_count"] * channels
        values = np.asarray(b["intensities"])
        assert values.min() >= 0
        assert values.max() <= 65535
        assert np.array_equal(values, np.round(values, 1))
        assert b["saturated"] is False


def test_frames_are_frame_major(raw_config: dict) -> None:
    cfg = config_from_dict(raw_config)
    model = OesModel(cfg.oes, cfg.physics, "lines")
    state = plasma_state(cfg.reference_run, cfg.physics)
    block = model.measure(model.true_frame(state, cfg.reference_run), np.random.default_rng(0), noise=False)
    flat = block.frames.ravel().tolist()
    # Without noise every frame is the same 8 values, in lines_nm order.
    assert flat[:8] == flat[8:16]
    assert flat[:8] == pytest.approx([3000, 3000, 20000, 3000, 3000, 12000, 30000, 12000], rel=1e-9)


def test_saturated_when_clipped(raw_config: dict) -> None:
    raw = copy.deepcopy(raw_config)
    raw["oes"]["saturation_counts"] = 25000
    cfg = config_from_dict(raw)
    model = OesModel(cfg.oes, cfg.physics, "lines")
    state = plasma_state(cfg.reference_run, cfg.physics)
    block = model.measure(model.true_frame(state, cfg.reference_run), np.random.default_rng(0), noise=True)
    assert block.saturated is True
    assert block.frames.max() == 25000
    assert np.all(block.frames[:, cfg.oes.lines_nm.index(516)] == 25000)


@pytest.mark.parametrize("mode", ["lines", "full"])
def test_c2_line_rises_with_methane_share(raw_config: dict, mode: str) -> None:
    cfg = config_from_dict(raw_config)
    model = OesModel(cfg.oes, cfg.physics, mode)
    lean = Setpoints(power_kw=1.85, ch4_slpm=8.0, h2_slpm=4.0, pressure_kpa=85.0)
    rich = Setpoints(power_kw=1.85, ch4_slpm=16.0, h2_slpm=1.0, pressure_kpa=85.0)
    if mode == "lines":
        idx = cfg.oes.lines_nm.index(516)
    else:
        idx = int(np.argmin(np.abs(model.wavelengths_nm - 516)))
    lean_516 = model.true_frame(plasma_state(lean, cfg.physics), lean)[idx]
    rich_516 = model.true_frame(plasma_state(rich, cfg.physics), rich)[idx]
    assert rich_516 > lean_516
    # Measured (noisy) blocks show the same ordering on average.
    rng = np.random.default_rng(1)
    lean_meas = model.measure(model.true_frame(plasma_state(lean, cfg.physics), lean), rng, noise=True)
    rich_meas = model.measure(model.true_frame(plasma_state(rich, cfg.physics), rich), rng, noise=True)
    assert rich_meas.frames[:, idx].mean() > lean_meas.frames[:, idx].mean()


def test_full_mode_spectrum_shape(raw_config: dict) -> None:
    cfg = config_from_dict(raw_config)
    model = OesModel(cfg.oes, cfg.physics, "full")
    frame = model.true_frame(plasma_state(cfg.reference_run, cfg.physics), cfg.reference_run)
    assert frame.shape == (2048,)
    # Continuum far from any line is about 1500 counts at the reference run.
    assert frame[model.wavelengths_nm > 650] == pytest.approx(1500, rel=1e-6)
    # The 516 nm peak (C2, 30 000) stands well above the continuum.
    assert frame[np.argmin(np.abs(model.wavelengths_nm - 516))] > 20000

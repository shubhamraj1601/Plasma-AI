# Plasma-AI

An AI and data-engineering research project for **microwave plasma methane pyrolysis**: a process that splits methane (CH₄) into solid carbon (graphite and graphene-like material) and hydrogen (H₂) without producing CO₂.

The aim is to learn how a plasma reactor's operating conditions shape its products, and to use that knowledge to steer the reactor towards better carbon quality and higher hydrogen yield. This repository holds the code: a streaming data pipeline first, and machine-learning models on top of it later.

## Why

Plasma pyrolysis is a promising route to low-carbon hydrogen, but the plasma is hard to observe and control. Small changes in power, gas mix or pressure change the plasma's state, and with it the quality of the carbon and the purity of the hydrogen. The useful signals (fast optical spectra and electrical measurements) arrive at high rates, while the product quality is only known after a run. Linking the two needs a reliable data pipeline and models that can read time series.

## What we are building

**Phase 1: data framework (current)**

```
data source ──► Pub/Sub ──► Dataflow (Apache Beam) ──► BigQuery (tabular) + Cloud Storage (spectra)
```

- **Message contract**: versioned JSON Schemas (`schemas/v0/`) for every message: process samples, optical emission spectroscopy (OES) blocks, run start and end events, run outcomes and dead letters.
- **Synthetic data generator**: produces realistic-looking reactor runs so the pipeline can be built and tested before real data is available. A real simulator or reactor can replace it later without changes downstream, because everything depends only on the message schema.
- **Streaming pipeline**: validation, dead-letter routing, windowing, normalisation and spectral feature extraction (for example emission line peaks and line ratios), then storage on Google Cloud Platform.

**Phase 2: modelling (later)**

- A **CNN-LSTM** model (PyTorch) that reads OES spectra and process time series to estimate the plasma state.
- Per-run aggregation that maps plasma behaviour to product outcomes.
- A **genetic-algorithm optimiser** that searches for operating conditions that improve the outcomes.

## Data at a glance

| Stream | Content | Rate (configurable) |
|---|---|---|
| Process time series | forward and reflected power, gas flows, pressure, impedance, gas temperature | ~10 Hz |
| OES spectra | selected emission lines (e.g. Hβ, C₂ Swan band) or full spectra | ~1 kHz frames, batched |
| Run outcomes | carbon yield and quality indicators (Raman, XRD), hydrogen purity | once per run |

Synthetic runs also carry ground-truth plasma-state labels (electron density, electron temperature, stability and carbon-growth indices) for model training. The physics behind the synthetic data is a simple **placeholder model** with illustrative coefficients. It is not a validated physical model, and it is built to be replaced.

## Repository layout

```
config/          generator settings (rates, noise, sweep ranges, placeholder coefficients)
schemas/v0/      JSON Schema message contract
plasma_ai/       Python package: config, messages, physics placeholder, OES model, sinks, validation
plasma_ai/generator/   synthetic generator CLI
tests/           pytest suite
PROGRESS.md      development log
```

## Quick start

Windows, Python 3.11, PowerShell:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

python -m plasma_ai.generator --runs 1 --duration-s 60 --seed 42 --out out   # one 60 s run
python -m plasma_ai.generator --help                                         # all options
python -m pytest -q                                                          # tests
```

Output goes to `out/<run_id>/process-ts.jsonl` and `out/<run_id>/oes-spectra.jsonl`. Each line is one Pub/Sub-shaped message, and the same seed gives identical output.

OES mode `lines` (8 channels) is the default and the only mode used for streaming to Pub/Sub. `--oes-mode full` (2048 bins, about 14 MB/s as JSON) is for short local or batch tests only, pending the decision on spectrum size and storage (Q3, P-03).

## Status

- [x] Message schemas v0 and synthetic generator v1 (local, no cloud)
- [ ] Cloud project and publishing to Pub/Sub
- [ ] Streaming pipeline (validation, features) and storage
- [ ] Modelling (CNN-LSTM) and optimisation

See `PROGRESS.md` for details.

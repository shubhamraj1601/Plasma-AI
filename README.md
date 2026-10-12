# Plasma-AI

Data pipeline for a microwave plasma reactor that cracks methane into carbon and hydrogen (M.Tech research project, Milestone 1). The synthetic generator produces reactor runs as schema v0 messages: process data at 10 Hz, OES spectra, ground-truth labels and run outcomes. Later stages send them through Pub/Sub and Dataflow into BigQuery.

**Setup** (Windows, Python 3.11, PowerShell)
```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

**Run** — writes `out/<run_id>/process-ts.jsonl` and `out/<run_id>/oes-spectra.jsonl`
```powershell
python -m plasma_ai.generator --runs 1 --duration-s 60 --seed 42 --out out
python -m plasma_ai.generator --reference-run --no-noise   # slide 3 calibration run
python -m plasma_ai.generator --help                       # all options
```

**Test**: `python -m pytest -q`

Settings are in `config/generator.yaml`, message schemas in `schemas/v0/`. Progress log: `PROGRESS.md`.

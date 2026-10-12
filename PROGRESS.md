# PROGRESS: Plasma-AI

## Status (updated 2026-10-12)

| Story | Plan day(s) | State | Notes |
|---|---|---|---|
| ST3 GCP foundation | 2 | Not started | Repo skeleton exists (built with ST4). GCP project, APIs, service accounts and budget alerts not started; no GCP calls made. |
| ST4 Synthetic generator | 6–8 | In progress | Generator v1 (Day 7) done, pulled forward to 12 Oct. Day 6 (real parameter ranges) and Day 8 (impairments, Pub/Sub publishing) not started. |
| ST5 Stream preprocessing | 9–10, 17 | Not started | `dead_letter` JSON Schema is ready. |
| ST6 Storage and aggregation | 11–13 | Not started | |

---

## 2026-10-12: Day 7 / ST4: Generator v1 (pulled forward)

**State:** Done (all six Definition-of-Done items met, except that the code is pushed to `feature_ai` instead of `main`; see Deviations)
**Commit(s):** 5b56bb7 ST4: add repo skeleton, generator config and v0 schemas · ac10e94 ST4: add synthetic generator v1 · f8645f8 ST4: add generator tests · (this entry) ST4: add README and PROGRESS log

### Built
- `config/generator.yaml`: every number from CLAUDE.md section 9, plus the physics coefficients (`physics:`), OES line amplitudes and drivers, and a message-type → topic map.
- `schemas/v0/*.schema.json`: JSON Schema 2020-12 for the envelope and all six message types. Each message schema uses `allOf` + `$ref` with `unevaluatedProperties: false`; nested objects use `additionalProperties: false`.
- `plasma_ai/config.py`: loads YAML into frozen dataclasses. Rejects unknown or missing keys and invalid values with the key path in the message.
- `plasma_ai/physics_placeholder.py`: `plasma_state(setpoints, params)` and `run_outcomes(mean_state, setpoints, params)` (section 8 relations), plus `power_density_kw_m3` and `residence_time_ms`, which return `None` while `reactor.volume_m3` is null.
- `plasma_ai/oes.py`: OES model, lines mode (8 channels) and full mode (2048-bin continuum plus Gaussian lines). Adds dark and shot noise, clips to saturation, rounds to 0.1 count and sets the `saturated` flag.
- `plasma_ai/messages.py`: envelope builder (seeded UUID v4, `seq_no` per message type, UTC timestamps) and the Pub/Sub-shaped `{"attributes", "data"}` record. Serialisation refuses NaN and Infinity.
- `plasma_ai/impairments.py`: Day 8 hooks (`publish_delay_us`, `drift`, `drop`). They are no-ops now but are already called by the generator.
- `plasma_ai/sinks.py`: `FileSink` (`out/<run_id>/<topic>.jsonl`) and `StdoutSink`.
- `plasma_ai/validate.py`: validates each message against `schemas/v0` and checks that its attributes are strings matching the data.
- `plasma_ai/generator/`: CLI (`python -m plasma_ai.generator`) with every flag in section 6. `run.py` orchestrates one run as a time-ordered record stream.
- `tests/`: 73 tests covering section 11, plus `test_config.py`.
- `README.md`, `pytest.ini`, `requirements.txt` (numpy, pyyaml, jsonschema, pytest; minor versions pinned), `.gitignore`.

### How to run
```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m plasma_ai.generator --runs 1 --duration-s 60 --seed 42 --out out
python -m pytest -q
```
Expect one summary line: `SYN-<date>-001 | oes_block=600 process_sample=600 run_end=1 run_outcome=1 run_start=1 | <two file paths> | yield=59.08% ...` and two files in `out\SYN-<date>-001\`: `process-ts.jsonl` (≈0.5 MB) and `oes-spectra.jsonl` (≈4 MB).

### Tests
- `python -m pytest -q`: 73 passed, 0 failed, in 6.6 s (Windows 11, Python 3.11.9, PowerShell).
- DoD 1: the 60 s run above took 2.9 s with validation on (limit 30 s).
- DoD 4: `--reference-run --no-noise` gives exactly the slide 3 values. Power 1.85, reflected 110.0 W, Z = 34.0 + 11.0j Ω, T_gas 2220.0 K, nₑ 3.1e14, Tₑ 2.9, stability 0.9600, CGI 0.8100, yield 68.00 %, ID/IG 0.220, FWHM 0.380°, H₂ purity 99.20 %.
- Reproducibility was also checked across two separate CLI processes: same `--seed` and `--start-ts` give byte-identical output folders.
- A 10-run sweep (`--seed 1`) gave yields from 54.7 to 72.6 %, inside the 46–77 % range the brief expects.
- Full OES mode: 1 s of data took 2.5 s with validation and wrote 14 MB.

### Sample output
```json
{"schema_version": "0.1", "message_type": "process_sample", "message_id": "233ea18b-ca97-4371-ba51-51731e512c3a", "source": "synthetic_generator", "reactor_id": "MW-PR-01", "run_id": "SYN-20261012-001", "seq_no": 0, "event_ts": "2026-10-12T05:20:41.400863Z", "publish_ts": "2026-10-12T05:20:41.400863Z", "power_kw": 2.0430743369994127, "reflected_power_w": 124.836304828771, "ch4_slpm": 11.510060525084588, "h2_slpm": 3.560542213969164, "pressure_kpa": 91.16090820942611, "re_z_ohm": 33.73117724350509, "im_z_ohm": 11.15651240942301, "gas_temperature_k": 2315.095446654103, "plasma_state": {"ne_cm3": 335291835973660.06, "te_ev": 2.8791665895117267, "stability_index": 0.9446766311398822, "carbon_growth_index": 0.6670003476839034}}
{"schema_version": "0.1", "message_type": "run_outcome", "message_id": "19f9943a-f2ee-4833-b1aa-b89aa194a1cb", "source": "synthetic_generator", "reactor_id": "MW-PR-01", "run_id": "SYN-20261012-001", "seq_no": 0, "event_ts": "2026-10-12T05:21:42.400863Z", "publish_ts": "2026-10-12T05:21:42.400863Z", "graphite_yield_percent": 59.0761142364526, "raman_id_ig": 0.24143338859928357, "xrd_002_fwhm_deg": 0.37987293879752937, "h2_purity_percent": 99.5231776632908}
```
(Each line in the file wraps this in `{"attributes": {...}, "data": ...}`, written compactly with no spaces.)

### Assumptions made in this session
- Raj's laptop had only Python 3.14. Python 3.11.9 was installed with winget (Raj approved), and `.venv` uses it.
- Config keys added beyond section 9 (config only, no schema change):
  - `topics` maps each message type to its topic, so P-04 stays a config change.
  - `physics.ref` and one block per relation hold the section 8 coefficients.
  - `oes.line_amplitude_counts`, `oes.line_driver` (`h_beta`, `c2`, `continuum`) and `oes.continuum_temp_exp` hold the OES table.
  - `oes.full.continuum_counts` is 1500.
- In YAML, nₑ base is written `3.1e+14`, because PyYAML reads `3.1e14` as a string.
- Process noise is multiplicative: measured = true × (1 + N(0, σ_rel)). Outcome noise works the same way, once per run. Percent outcomes are clipped to [0, 100] after noise.
- `--no-noise` turns off all noise: process, OES and outcome. The reference-run check needs this.
- OES dark noise and shot noise are drawn as one Gaussian with their combined sigma (the same distribution as two separate draws). `saturated` is true if any value before clipping is ≥ `saturation_counts`.
- Full mode grid is `linspace(400, 700, 2048)` (both ends included). Each line is a Gaussian with FWHM 0.5 nm scaled to its amplitude; overlapping lines (485 and 486 nm) add.
- The `nnn` in `run_id` is the run number within one CLI call (001, 002, …), and the date is that run's UTC start date.
- Message counts per run: process samples = floor(duration × 10 Hz) and OES blocks = floor(duration × 1000 / 100).
- Stream order: `run_start`, then process samples and OES blocks merged by `event_ts` (process first on ties), then `run_end` and `run_outcome`.
- JSON is written compactly. Floats keep full precision, except intensities, which are rounded to 1 decimal.
- When `--stdout` is set, the summary goes to stderr so stdout stays pure JSONL. Validation is turned off with `--no-validate`. Exit codes: 0 ok, 1 invalid message, 2 bad config.
- Schema constraints beyond the field table:
  - `message_id` must be a UUID v4, timestamps must match `YYYY-MM-DDTHH:MM:SS.ffffffZ`, and `run_id` must match `^[A-Za-z0-9_-]*[0-9]{8}-[0-9]{3,}$`.
  - `frame_count` and `frame_interval_us` must be ≥ 1, and `duration_s` must be > 0.
  - `original_message` must look like base64.
  - JSON Schema cannot express "intensities length = frame_count × channels", so the schema doesn't check it. The tests check it, and Beam should check it on Day 9.
- The validator type-checks `intensities` items directly, then runs jsonschema on a copy that keeps only the first item. The result is the same as a full check. A 1 s full-mode run went from 17.4 s to 2.5 s.
- `residence_time_ms` (used only once the volume is known) converts SLPM to actual flow with the ideal-gas law at 0 °C and 1 atm reference.

### Deviations from CLAUDE.md
- Commits are pushed to `feature_ai`, not `main`. Raj asked for this; he merges with a PR after review.
- `test_schema.py` validates a 10 s run in lines mode but only a 1 s run in full mode. Full mode is 2 million values per second (≈140 MB for 10 s), which would slow the suite a lot.

### Open questions / blockers
- None blocking. Q1 (ranges), Q3 (OES mode and range), Q9 (reactor volume) and Q13 (sampling rates) are still open; all are config-only. (mentor)

### For PM (proposed changes, not applied)
- **run_id collisions:** two generator calls on the same day both produce `SYN-YYYYMMDD-001`, which would mix runs in BigQuery. Proposal: add the start time to the ID (e.g. `SYN-20261012-0500-001`) or add a `--first-run-no` flag. Either choice needs a run_id format decision.
- **dead_letter envelope:** the schema requires `run_id`, `seq_no` and `event_ts`, but a message that fails at the `parse` stage may not have them. Proposal: make these nullable in `dead_letter` only, or have Beam fill placeholders. Decide before Day 9.
- **H₂ purity noise:** 1 % relative noise on 99.2 % is ±1 percentage point, larger than the impurity itself (0.8 point). Purity also often clips at 100. Proposal: apply the noise to the impurity (100 − purity) or use an absolute sigma.
- **Full OES mode data volume:** 2048 bins at 1 kHz is about 14 MB/s of JSON (1.4 MB per message, roughly 50 GB per hour). That fits Pub/Sub's 10 MB message limit but strains the D-06 budget and Dataflow throughput. Proposal: use lines mode for streaming demos, or a lower frame rate or binary encoding for full mode. Relevant to Q3 and P-03.
- C/H ratio (slide 4) is left out of v1 as instructed.

### Next
- Per plan: Day 2 / ST3, the GCP foundation (Tue 13 Oct): project, APIs, service accounts, budget alerts. Raj must create or choose the GCP project and billing account first and confirm before Claude Code creates anything in GCP.
- Raj: review and merge the PR from `feature_ai` into `main`.

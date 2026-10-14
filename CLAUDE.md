# Plasma-AI: instructions for Claude Code

Read this whole file before writing any code. It is the brief from the project's PM chat. If something here is unclear or seems wrong, ask Raj; never guess, and never change a decision or the schema on your own (see "Proposing changes").

---

## 1. Project in one paragraph

M.Tech research project (BITS Pilani, AI & ML) for a client running a microwave plasma reactor that cracks methane (CH₄) into solid carbon (graphite/graphene) and hydrogen (H₂). Milestone 1 covers D1.1 (AI system architecture and data framework), D1.2 (synthetic dataset generation) and D1.3 (data pipeline and integration framework). **Deadline: Sat 31 Oct 2026.** "Done" means two things: (1) an architecture deck, built in the PM chat, and (2) an **active pipeline running end to end on GCP**:

```
synthetic generator ──► Pub/Sub ──► Dataflow (Apache Beam, Python) ──► BigQuery + Cloud Storage
```

Later (Milestone 2, not now) a CNN-LSTM model, per-run aggregation, outcome mapping and a genetic-algorithm optimiser are built on top of this data.

## 2. Who does what

| Who | Role |
|---|---|
| Raj | Owner. Reviews every day's output, runs commands that need his laptop or GCP account, answers questions. |
| PM chat (claude.ai, project "AI-Research Project") | Owns the plan, the decision register and the data schema. Source of truth: the doc "D1 Decision Register & Delivery Plan" (tabs ST1 to ST8; schema in tab ST2). |
| Claude Code (you) | Builds the code in this repo, about one hour of work per day, one plan task at a time. |

The PM chat cannot see this session. The only channel back to it is `PROGRESS.md` (section 12). Keep it accurate.

## 3. Environment

- Repo: https://github.com/shubhamraj1601/Plasma-AI (public), default branch `main`.
- Raj's laptop: **Windows**, Python **3.11**, VS Code. Give every command in **PowerShell** form.
- Setup:
  ```powershell
  py -3.11 -m venv .venv
  .venv\Scripts\Activate.ps1
  python -m pip install -r requirements.txt
  ```
- Use `pathlib` for all paths, open files with `encoding="utf-8"` and `newline="\n"`, never hard-code `/` or `\`.
- **GCP:** only through the ST3 scripts in section 6A Part B, and only after Raj approves each command that creates or changes something. Everything else still runs locally.
- Dependencies: keep them few. Allowed now: `numpy`, `pyyaml`, `jsonschema`, `pytest`. Ask Raj before adding anything else. `google-cloud-pubsub` arrives on Day 8, `apache-beam[gcp]` on Day 9.

## 4. Delivery plan (do only the current task)

Story codes: ST1 decisions and architecture · ST2 data contract · ST3 GCP foundation · ST4 synthetic generator · ST5 stream preprocessing · ST6 storage and aggregation · ST7 architecture deck · ST8 review and delivery.

| Day | Date | Story | Task | Output |
|---|---|---|---|---|
| 1 | Mon 12 Oct | ST1 | Register walkthrough; questions to mentor | (PM chat) |
| **2** | Tue 13 Oct | **ST3** | **GCP project, APIs, service accounts, budget alerts (CURRENT TASK, Part B; slipped to 14 Oct)** | Budget and alerts configured; repo up (done) |
| 3 | Wed 14 Oct | ST2 | Message schemas, OES config | Schema draft v0 (done in PM chat) |
| 4 | Thu 15 Oct | ST1 | Architecture diagram v1 | (PM chat, done) |
| 5 | Fri 16 Oct | ST2 | Mentor answers; BigQuery table designs; freeze schema v0.1 | Schema frozen |
| 6 | Sat 17 Oct | ST4 | Parameter ranges from professor's PDFs into config | Ranges config |
| 7 | Sun 18 Oct | ST4 | Generator v1 (DONE 12 Oct; PM fixes are Part A of the current task) | Local run writes messages |
| 8 | Mon 19 Oct | ST4 | Delay, drift, dropouts; publish to Pub/Sub at a set rate | Messages in subscription |
| 9 | Tue 20 Oct | ST5 | Beam v1 on local runner: read, parse, validate, dead-letter | Bad messages routed |
| 10 | Wed 21 Oct | ST5 | Windowing, normalisation, OES features (line peaks, C₂/Hβ ratio) | Feature records |
| 11 | Thu 22 Oct | ST6 | Sinks: spectra to Cloud Storage; process data and features to BigQuery | Rows in BigQuery |
| 12 | Fri 23 Oct | ST6 | Deploy to Dataflow; per-run aggregate table | Aggregate query works |
| 13 | Sat 24 Oct | ST6 | End-to-end demo run; screenshots and cost; drain job | E2E demo recorded |
| 14–16 | 25–27 Oct | ST7 | Deck (PM chat) | |
| 17 | Wed 28 Oct | ST5 | Hardening: README, one-command start and stop scripts | Repeatable runs |
| 18–20 | 29–31 Oct | ST8 | Mentor feedback, rehearsal, delivery | |

Do not start a later day's work unless Raj asks. Leave clear hooks for it instead.

## 5. Decisions

Confirmed (do not change):

| ID | Decision |
|---|---|
| D-01 | GCP only |
| D-02 | PyTorch for ML (later, not in D1 code) |
| D-03 | Pub/Sub for streaming; Kafka is only a documented alternative |
| D-05 | Cost scope: GCP running and build cost only |
| D-06 | Budget: low hundreds of USD in total |
| D-07 | The client's simulator will publish to our Pub/Sub topics later; we have no simulator of our own |
| P-01 | Our synthetic generator publishes sample data to the same Pub/Sub topics; it lands in BigQuery |

Because of D-07, **the generator is replaceable**. Nothing downstream may depend on it except the message schema.

Pending mentor review (build so each is a config change, not a code change):
P-02 Dataflow vs Cloud Run subscriber · P-03 raw spectra in Cloud Storage, tabular data in BigQuery · P-04 two topics plus dead-letter · P-05 versioned schema, OES size in config · P-06 cost guard (Dataflow only during work sessions, no Cloud Composer) · P-07 region `us-central1`.

## 6A. Current task (from Wed 14 Oct): Part A, then Part B

Do Part A first (small), push it, then start Part B. One `PROGRESS.md` entry may cover both.

### Part A: apply PM decisions on generator v1 (from PROGRESS.md "For PM", 12 Oct)
1. **run_id format** changes to `{run.id_prefix}{YYYYMMDD}-{HHMMSS}-{nnn}` from the run's UTC start time, e.g. `SYN-20261014-020000-001`. `nnn` stays the run number within one CLI call. Update the schema pattern, the generator and the tests. (Two calls on the same day no longer collide.)
2. **dead_letter envelope:** in `dead_letter` only, `reactor_id`, `run_id`, `seq_no`, `event_ts` and `source` may be `null`. The pipeline copies them from the original message when it parses, else `null`. `message_id` is a new UUID; `publish_ts` is when the dead letter is written. All other message types keep these fields non-null. Update `dead_letter.schema.json` and add tests for a parse-stage dead letter with nulls.
3. **H₂ purity noise:** apply the relative outcome noise to the impurity, not the purity: impurity = 100 − purity_true; purity = 100 − impurity × (1 + N(0, σ)); then clip to [0, 100]. Other outcomes are unchanged. `--no-noise` still gives exactly 99.20.
4. **Full OES mode:** no code change. `lines` stays the default and the only mode used for streaming to Pub/Sub. State in the README that `full` (~14 MB/s as JSON) is for short local or batch tests only, pending Q3 and P-03.
5. **Branching:** push to `feature_ai`; Raj merges to `main` by PR.

### Part B: ST3 GCP foundation (plan Day 2)

**Ask Raj before running any command that creates or changes something in GCP.** Show the command, wait for a yes. Read-only `gcloud` commands are fine.

Prerequisites from Raj (ask for any that are missing; do not guess them):
- A GCP project ID (a new, dedicated project is recommended, e.g. `plasma-ai-d1`) with a billing account linked.
- The billing account ID and the email that should get budget alerts.
- Google Cloud SDK installed on the laptop, `gcloud auth login` and `gcloud auth application-default login` done.
- Region `us-central1` (P-07, pending; keep it in config).
- Budget: USD 200 (Q2 assumption).

Build (PowerShell scripts that call `gcloud`; no Terraform, per the scope-cut order):
```
config/gcp.yaml                 # project_id, region, billing_account_id, budget_usd, alert_thresholds [0.5, 0.8, 1.0], alert_email
infra/README.md                 # order to run, what each script does, how to undo it
infra/00_check_prereqs.ps1      # read-only: gcloud installed, logged in, project exists, billing linked
infra/01_enable_apis.ps1        # pubsub, dataflow, compute, bigquery, storage, iam, logging, monitoring, billingbudgets, cloudresourcemanager
infra/02_service_accounts.ps1   # sa-generator: roles/pubsub.publisher
                                # sa-dataflow: roles/dataflow.worker, roles/pubsub.subscriber, roles/pubsub.publisher (dead-letter), roles/bigquery.dataEditor, roles/bigquery.jobUser, roles/storage.objectAdmin
infra/03_budget.ps1             # budget of budget_usd on the project, email alerts at 50 / 80 / 100 % of actual spend
infra/04_verify.ps1             # read-only: lists enabled APIs, service accounts with roles, and the budget
```
Rules:
- Scripts are idempotent: re-running them changes nothing and does not fail if a resource exists.
- All values come from `config/gcp.yaml`; nothing project-specific is hard-coded. `config/gcp.yaml` is committed (it holds no secrets); never commit service account keys. Do not create any key files: local runs use Raj's application-default credentials, Dataflow uses `sa-dataflow`.
- Grant roles at project level for now (simplest); note in `infra/README.md` that bucket- and topic-level grants are a hardening step.
- Do not create Pub/Sub topics, buckets, BigQuery datasets or Dataflow jobs yet: those belong to Days 8, 11 and 12.
- Budget alerts only notify; they do not stop spending. Say so in `infra/README.md`.

Done when: `infra/04_verify.ps1` shows the APIs enabled, both service accounts with their roles, and the budget with three thresholds and Raj's email. A real alert cannot fire with zero spend; the first check that alerts arrive is after the Day 12 Dataflow run (PM decision).

## 6. ST4 Generator v1 (done 12 Oct; kept as the reference spec)

### Goal
A local Python generator that produces realistic-looking runs of the reactor as schema v0 messages, written to JSON Lines files (and optionally stdout), with no cloud dependency.

### Scope
In: process time series, OES spectra (lines and full modes), ground-truth plasma labels, per-run product outcomes, run start/end events, Gaussian measurement noise, seeded reproducibility, schema validation, tests.
Out (later days, leave hooks): delay, drift, dropouts, out-of-order messages (Day 8) · Pub/Sub publishing (Day 8) · Beam (Day 9+) · Avro (at schema freeze) · real parameter ranges (Day 6).

### Repo layout to create

```
Plasma-AI/
├─ CLAUDE.md                  # this file (do not edit except when Raj pastes a new version)
├─ PROGRESS.md                # handoff log, you maintain it (section 12)
├─ README.md                  # short: what it is, setup, how to run, how to test
├─ requirements.txt           # numpy, pyyaml, jsonschema, pytest (pinned minor versions)
├─ .gitignore                 # .venv/, __pycache__/, .pytest_cache/, out/, *.pyc
├─ config/
│  └─ generator.yaml          # every number in section 9 lives here
├─ schemas/
│  └─ v0/                     # JSON Schema (draft 2020-12), one file per message type
│     ├─ envelope.schema.json
│     ├─ process_sample.schema.json
│     ├─ oes_block.schema.json
│     ├─ run_start.schema.json
│     ├─ run_end.schema.json
│     ├─ run_outcome.schema.json
│     └─ dead_letter.schema.json
├─ plasma_ai/
│  ├─ __init__.py
│  ├─ config.py               # load + validate YAML into dataclasses
│  ├─ messages.py             # build envelope + payloads; JSON-safe serialisation
│  ├─ physics_placeholder.py  # setpoints → plasma state → outcomes (section 8), ONE swappable module
│  ├─ oes.py                  # OES frames from plasma state (lines and full modes)
│  ├─ impairments.py          # Day 8 hooks: delay, drift, dropout; no-ops in v1
│  ├─ sinks.py                # Sink interface; FileSink, StdoutSink (PubSubSink on Day 8)
│  ├─ validate.py             # validate a message against schemas/v0
│  └─ generator/
│     ├─ __init__.py
│     ├─ __main__.py          # CLI entry: python -m plasma_ai.generator
│     └─ run.py               # orchestrates one run end to end
└─ tests/
   ├─ test_schema.py
   ├─ test_reference_run.py
   ├─ test_counts_and_order.py
   ├─ test_reproducibility.py
   └─ test_oes.py
```

### CLI

```powershell
python -m plasma_ai.generator --config config/generator.yaml --runs 1 --duration-s 60 --seed 42 --out out
```

| Flag | Default | Meaning |
|---|---|---|
| `--config` | `config/generator.yaml` | Config file |
| `--runs` | 1 | Number of runs; setpoints for each are drawn from `sweep` ranges |
| `--duration-s` | 60 | Seconds of data per run |
| `--seed` | none | RNG seed; same seed + same `--start-ts` → byte-identical output |
| `--start-ts` | now (UTC) | ISO-8601 start of the first run, e.g. `2026-10-12T05:00:00Z` |
| `--reference-run` | off | Use the slide 3 setpoints exactly (section 10) instead of sampling |
| `--no-noise` | off | Turn off measurement noise (for tests and calibration) |
| `--oes-mode` | from config | `lines` or `full`, overrides config |
| `--out` | `out` | Output folder for FileSink |
| `--stdout` | off | Also print messages to stdout (one JSON per line) |
| `--validate` | on | Validate every message before writing; fail fast on the first invalid one |

Runs follow each other in time: run k+1 starts at the end of run k plus `run.gap_s` from config.
At the end, print a one-line summary per run (run_id, message counts, file paths, outcome values).

### Output format (local sink)

```
out/<run_id>/process-ts.jsonl     # run_start, process_sample..., run_end, run_outcome
out/<run_id>/oes-spectra.jsonl    # oes_block...
```

Each line is one Pub/Sub-shaped record, so the Day 8 publisher can send it unchanged:
```json
{"attributes": {"schema_version": "0.1", "message_type": "process_sample", "run_id": "SYN-20261012-001", "source": "synthetic_generator"}, "data": { ...the message, envelope + payload... }}
```
Attribute values are strings (a Pub/Sub rule). Lines are written in `event_ts` order within each file.

### Definition of done
1. `python -m plasma_ai.generator --runs 1 --duration-s 60 --seed 42 --out out` runs on Raj's Windows laptop in under 30 s.
2. Every message validates against `schemas/v0`.
3. `python -m pytest -q` passes, covering the tests in section 11.
4. `--reference-run --no-noise` reproduces the slide 3 values (section 10) within 1 %.
5. README explains setup, run and test in under 20 lines.
6. Code is committed and pushed to `feature_ai`; Raj merges to `main` by PR. `PROGRESS.md` has today's entry.

## 7. Schema v0 (exact contract)

Mirror of PM doc tab ST2. Field names, types and units are fixed. Units are in field names. All timestamps are UTC, ISO-8601 with microseconds and a trailing `Z` (e.g. `2026-10-12T05:00:00.100000Z`). A missing reading is JSON `null`, never `0`, `-1` or `NaN`. No NaN or Infinity anywhere in output.

### Envelope (every message, top level of `data`)

| Field | Type | Rule |
|---|---|---|
| schema_version | string | `"0.1"` |
| message_type | string enum | `process_sample`, `oes_block`, `run_start`, `run_end`, `run_outcome`, `dead_letter` |
| message_id | string | UUID v4, derived from the seeded RNG so seeded runs are reproducible |
| source | string enum | `synthetic_generator` (this generator), `client_simulator`, `published_batch` |
| reactor_id | string | `MW-PR-01` (config) |
| run_id | string | `{run.id_prefix}{YYYYMMDD}-{HHMMSS}-{nnn}`, e.g. `SYN-20261014-020000-001`; date and time = run start (UTC); `nnn` = run number within one CLI call |
| seq_no | integer ≥ 0 | Counts per `(run_id, message_type)`, starting at 0, no gaps in v1. Gaps later mean dropouts. |
| event_ts | string timestamp | When the sensor measured. For `oes_block`: time of its first frame. |
| publish_ts | string timestamp | When published. In v1 equals `event_ts` (delay hook = 0). |

Payload fields sit next to the envelope fields at the top level (flat), except `plasma_state`, `setpoints` and `original_attributes`, which are objects.

### process_sample (topic `process-ts`, 10 Hz)

| Field | Type | Sensor |
|---|---|---|
| power_kw | number or null | Power supply (forward power) |
| reflected_power_w | number or null | VNA |
| ch4_slpm | number or null | Mass flow controller |
| h2_slpm | number or null | Mass flow controller |
| pressure_kpa | number or null | Pressure sensor |
| re_z_ohm | number or null | VNA, real part of impedance |
| im_z_ohm | number or null | VNA, imaginary part of impedance |
| gas_temperature_k | number or null | Pyrometer |
| plasma_state | object or null | Ground-truth labels, generator only; `null` from real sensors |

`plasma_state` = `{ne_cm3, te_ev, stability_index, carbon_growth_index}`, all numbers. These are noise-free true values (they are labels for D2.1 model training).

### oes_block (topic `oes-spectra`, 10 messages per second)

| Field | Type | Rule |
|---|---|---|
| spectrometer_id | string | `OES-01` (config) |
| oes_config_id | string | e.g. `oes-lines-v0` or `oes-full2048-v0` (config) |
| mode | string enum | `lines` or `full` |
| frame_count | integer | 100 (config `oes.frames_per_message`) |
| frame_interval_us | integer | 1 000 000 / `oes.sampling_hz` = 1000 |
| integration_time_ms | number | 0.9 (config, placeholder) |
| intensities | array of numbers | Length = frame_count × channels, frame by frame (frame 0 all channels, then frame 1 ...). Channels = 8 in lines mode, `oes.full.n_bins` in full mode. Round to 1 decimal. |
| saturated | boolean | True if any value in the block hit `oes.saturation_counts` (values are clipped to it) |

`oes_block` carries no plasma_state; downstream joins it to process samples by `run_id` and time.

### run_start (topic `process-ts`, once per run, `event_ts` = run start)
`setpoints` = `{power_kw, ch4_slpm, h2_slpm, pressure_kpa}` · `oes_config_id` (string) · `generator_seed` (integer or null) · `duration_s` (number).

### run_end (topic `process-ts`, once, `event_ts` = run start + duration)
`end_reason`: `completed` or `aborted` (always `completed` in v1).

### run_outcome (topic `process-ts`, once, `event_ts` = run_end + `run.outcome_delay_s`)
`graphite_yield_percent`, `raman_id_ig`, `xrd_002_fwhm_deg`, `h2_purity_percent` (numbers). Computed from run-average plasma state (section 8), plus outcome noise.

### dead_letter (topic `dead-letter`; written by the Beam pipeline from Day 9, not by the generator)
`original_message` (base64 string) · `original_attributes` (object of strings) · `error_stage` (`parse`, `schema`, `range`, `ordering`) · `error_code` (string) · `error_detail` (string) · `failed_ts` (timestamp). In `dead_letter` only, the envelope fields `reactor_id`, `run_id`, `seq_no`, `event_ts` and `source` may be `null` (copied from the original message when it parses).

### JSON Schema rules
- Draft 2020-12. Unknown fields must be rejected, so typos are caught.
- `required`: every field listed above (nullable fields are required but may be `null`).
- Each message schema composes the envelope with `allOf` + `$ref` and sets `unevaluatedProperties: false` (not `additionalProperties`, which does not see fields defined inside `allOf`). Nested objects (`plasma_state`, `setpoints`) set `additionalProperties: false`. Test that an extra field fails.

### Versioning rule
Adding a nullable field keeps `0.x`; renaming or removing a field bumps the major version. Either is a PM decision.

## 8. Physics placeholder (assumption Q8; replaced by the D2.3 model later)

All of this lives in `physics_placeholder.py` behind one function pair, so it can be swapped without touching anything else:

```python
def plasma_state(setpoints) -> PlasmaState          # power_kw, ch4_slpm, h2_slpm, pressure_kpa → state + derived signals
def run_outcomes(mean_state, setpoints) -> Outcomes  # run-average state → product outcomes
```

Every coefficient below is a **placeholder**, chosen only so the reference run reproduces slide 3. Put them all in `config/generator.yaml` under `physics:` and comment them as placeholders. Reference values: P₀ = 1.85 kW, Q_CH4,0 = 12.0 SLPM, Q_H2,0 = 2.0 SLPM, p₀ = 85 kPa, x = Q_CH4 / (Q_CH4 + Q_H2), x₀ = 12/14.

| Quantity | Placeholder relation |
|---|---|
| ne_cm3 | 3.1e14 × (P/P₀)^1.0 × (p/p₀)^−0.3 |
| te_ev | 2.9 × (P/P₀)^0.2 × (p/p₀)^−0.4 |
| gas_temperature_k | 2220 × (P/P₀)^0.3 × (p/p₀)^0.1 |
| reflected_power_w | 110 × (P/P₀) × (1 + 0.5 × \|p/p₀ − 1\|) |
| re_z_ohm | 34 × (ne / 3.1e14)^−0.2 |
| im_z_ohm | 11 × (p/p₀)^0.2 |
| stability_index | clip(1 − 0.6727 × reflected_power_w / (P × 1000) − 0.2 × \|p/p₀ − 1\|, 0, 1) |
| carbon_growth_index | 0.81 × (x/x₀)^1.5 × (te/2.9)^0.5 × (stability/0.96) |
| graphite_yield_percent | clip(68 × (CGI_mean / 0.81)^0.8, 0, 100) |
| raman_id_ig | 0.22 × (0.81 / CGI_mean)^0.5 |
| xrd_002_fwhm_deg | 0.38 × (2220 / T_gas_mean)^0.7 |
| h2_purity_percent | clip(100 − 0.8 × (3.1e14 / ne_mean)^0.5 × (x/x₀)², 0, 100) |

Here P = power_kw, p = pressure_kpa. Within a run, the setpoints are constant in v1. The "true" signal at each sample is the relation above; the measured value adds noise (section 9). Over the default sweep ranges these give yields of about 46–77 %, which is fine for a demo.

Not derivable yet (do not invent): power density P_d (kW/m³) and residence time τ (ms) from slide 4 need the reactor volume (Q9). Add `reactor.volume_m3: null` to config and a helper that returns `None` while it is null. The C/H ratio in slide 4 (0.45–0.60) does not match the reference run's gas mix under any obvious definition; leave C/H out of v1 and list it under "For PM".

## 9. Config (`config/generator.yaml`) values

```yaml
schema_version: "0.1"
reactor_id: MW-PR-01
source: synthetic_generator

run:
  id_prefix: "SYN-"
  gap_s: 5                 # seconds between runs
  outcome_delay_s: 1       # run_outcome arrives after run_end

process:
  sampling_hz: 10          # Q13 assumption
  noise_rel_sigma:         # Gaussian, relative to true value (placeholder)
    power_kw: 0.005
    reflected_power_w: 0.02
    ch4_slpm: 0.005
    h2_slpm: 0.005
    pressure_kpa: 0.003
    re_z_ohm: 0.01
    im_z_ohm: 0.01
    gas_temperature_k: 0.005

outcomes:
  noise_rel_sigma: 0.01    # applied once per run to each outcome; for H2 purity it applies to the impurity (100 - purity) (placeholder)

sweep:                     # placeholder ranges around the reference run; real ranges from professor's PDFs on Day 6 (Q1)
  power_kw: [1.5, 2.2]
  ch4_slpm: [8.0, 16.0]
  h2_slpm: [1.0, 4.0]
  pressure_kpa: [70.0, 100.0]

reference_run:             # slide 3, RUN-042
  power_kw: 1.85
  ch4_slpm: 12.0
  h2_slpm: 2.0
  pressure_kpa: 85.0

oes:
  mode: lines              # Q3 assumption; alt: full
  spectrometer_id: OES-01
  sampling_hz: 1000        # Q13 assumption
  frames_per_message: 100
  integration_time_ms: 0.9 # placeholder
  saturation_counts: 65535 # 16-bit detector, placeholder
  dark_noise_counts: 50    # Gaussian sigma, placeholder
  shot_noise_rel: 0.01     # Gaussian sigma relative to signal, placeholder
  lines_nm: [480, 485, 486, 490, 500, 510, 516, 520]   # slide 2
  config_id:
    lines: oes-lines-v0
    full: oes-full2048-v0
  full:
    n_bins: 2048           # slide 2 allows 2048–4096
    wavelength_range_nm: [400.0, 700.0]   # placeholder, Q3 open
    line_fwhm_nm: 0.5      # placeholder

reactor:
  volume_m3: null          # Q9 open; needed for P_d and tau

window:
  samples: 50              # slide 2 allows 50–100; used from Day 10, keep here
```

Validate the config on load (ranges low < high, sampling rates > 0, `mode` in {lines, full}, `n_bins` in 2048–4096) and fail with a clear message.

### OES model (placeholder, in `oes.py`)
Line intensity (counts) for each line at the true plasma state, then noise per frame:

| Line (nm) | Driver | Amplitude at reference |
|---|---|---|
| 486 (Hβ) | (1 − x)/(1 − x₀) × (ne / 3.1e14) | 20 000 |
| 516 (C₂ Swan band head) | (x/x₀) × (te / 2.9) | 30 000 |
| 510, 520 (C₂ band shoulders) | same driver as 516 | 12 000 each |
| 480, 485, 490, 500 (background) | (T_gas / 2220)^4 | 3 000 each |

Measured = true + N(0, dark_noise) + N(0, shot_noise_rel × true), then clipped to [0, saturation_counts]. Full mode: a continuum of (T_gas/2220)^4 × 1 500 counts across all bins plus a Gaussian peak of the table amplitude and `line_fwhm_nm` width at each line position. Keep the line list and amplitudes in config. Specair, LIFBASE and PGOPHER are out of scope (Q12).

## 10. Reference run (slide 3, RUN-042, for calibration tests)

| Group | Values |
|---|---|
| Setpoints | power 1.85 kW, CH₄ 12.0 SLPM, H₂ 2.0 SLPM, pressure 85 kPa |
| Signals | reflected 110 W, Z = 34 + 11j Ω, T_gas 2220 K |
| Plasma state | nₑ 3.1e14 cm⁻³, Tₑ 2.9 eV, stability 0.96, CGI 0.81 |
| Outcomes | yield 68 %, ID/IG 0.22, XRD (002) FWHM 0.38°, H₂ purity 99.2 % |

Slide 3 also lists per-run averages (avg nₑ 2.9e14 cm⁻³, avg Tₑ 2.8 eV, CGI integral 184). These come from per-run aggregation in ST6, not from the generator; ignore them for v1 calibration.

## 11. Tests (pytest, all must pass)

- `test_schema.py`: every message of a 10 s run (both OES modes) validates; a message with an extra field, a wrong type, or a missing required field fails.
- `test_reference_run.py`: `--reference-run --no-noise` gives every signal, plasma_state field and outcome in section 10 within 1 %.
- `test_counts_and_order.py`: for a 10 s run: 100 `process_sample`, 100 `oes_block`, exactly 1 each of `run_start`, `run_end`, `run_outcome`; `seq_no` contiguous from 0 per message type; `event_ts` non-decreasing per file; no `NaN`/`Infinity` in output; attribute values are strings.
- `test_reproducibility.py`: same seed + same `--start-ts` → identical files; different seed → different values.
- `test_oes.py`: intensities length = frame_count × channels in both modes; values within [0, saturation]; `saturated` true when a value is clipped; 516 nm rises when CH₄ share rises.

Use small durations in tests so the suite finishes in a few seconds.

## 12. PROGRESS.md (required, the handoff to the PM chat)

Create `PROGRESS.md` at the repo root if it does not exist. At the **end of every session**, before your final reply:
1. Update the **Status** table at the top.
2. Add a new **dated entry directly under it** (newest first). Never delete old entries.
3. Commit it with the code and push.
4. Print the new entry in your final reply so Raj can paste it into the PM chat.

Write it so someone who has not seen this session understands it. Facts only: what exists, what ran, what failed. No "should work". If a test was not run, say so.

Template:

~~~markdown
# PROGRESS: Plasma-AI

## Status (updated YYYY-MM-DD)

| Story | Plan day(s) | State | Notes |
|---|---|---|---|
| ST3 GCP foundation | 2 | Not started / In progress / Done / Blocked | |
| ST4 Synthetic generator | 6–8 | | |
| ST5 Stream preprocessing | 9–10, 17 | | |
| ST6 Storage and aggregation | 11–13 | | |

---

## YYYY-MM-DD: Day N / STx: <task name>

**State:** Done / Partly done / Blocked
**Commit(s):** <short hash> <message>, ...

### Built
- <file or module>: <what it does, one line>

### How to run
```powershell
<exact command(s)>
```
<one line on what output to expect>

### Tests
- `python -m pytest -q`: <N passed, M failed>; <what failed and why>

### Sample output
<one process_sample message and one run_outcome, trimmed, as JSON>

### Assumptions made in this session
- <anything not specified in CLAUDE.md that you had to decide>

### Deviations from CLAUDE.md
- <none, or what and why>

### Open questions / blockers
- <question> (who can answer: Raj / PM / mentor)

### For PM (proposed changes, not applied)
- <change to decisions, schema or plan, with the reason>

### Next
- <next task per plan, and anything Raj must do first>
~~~

## 13. Proposing changes

You may decide implementation details (function names, internal structure, file splitting) yourself and list them under "Assumptions". You must **not** change, without the PM chat agreeing: the schema (fields, names, types, units, topics), confirmed decisions, the plan or its dates, or the definition of done. Write the proposal under "For PM" and build to the current contract meanwhile.

## 14. Working rules

- One plan task per session. If done early, improve tests or docs for that task; do not start the next day.
- Small commits, imperative messages, e.g. `ST4: add OES lines model`. Push to `feature_ai` at the end of each session; Raj merges to `main` by PR.
- Never commit secrets, service account keys, `.env` files or generated data (`out/` is git-ignored).
- Type hints everywhere; docstrings on public functions; no dead code.
- Seed every random draw from one `numpy.random.Generator` created from `--seed`.
- If a command fails on Windows, fix it for Windows; do not tell Raj to switch to WSL or Linux.
- Ask Raj before: adding a dependency, creating anything in GCP, or deleting files you did not create.
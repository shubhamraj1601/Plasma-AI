# PROGRESS: Plasma-AI

## Status (updated 2026-10-17)

| Story | Plan day(s) | State | Notes |
|---|---|---|---|
| ST3 GCP foundation | 2 | Blocked | Terraform ready, not applied. `infra/terraform/` validates; nothing run on GCP. Waiting for Q2 (billing), project id and billing account. |
| ST4 Synthetic generator | 6–8 | In progress | v1 done; PM fixes (Part A) applied. Day 8 local half done: disturbances, plus `--sink pubsub` tested on the local emulator. Day 6 (real ranges) not started; Day 8 on real Pub/Sub waits on ST3. |
| ST5 Stream preprocessing | 9–10, 17 | Not started | `dead_letter` schema allows null copied fields (Part A). |
| ST6 Storage and aggregation | 11–13 | Not started | Bucket and `plasma_d1` dataset are in `infra/terraform/` (not applied). Tables wait for the Day 11 schema freeze. |

---

## 2026-10-17: Day 2 / ST3: GCP foundation as Terraform (not applied)

**State:** Blocked. Terraform written and validated locally and in CI; **nothing applied to GCP** (billing waits on the mentor, Q2).
**Commit(s):** 09fb0e2 ST3: add Terraform config for the GCP foundation (not applied) · bb402dc ST3: remove the 14 Oct PowerShell scripts; document the Terraform workflow · 0d5719e Add CI: pytest plus terraform fmt and validate · (this entry) Add PROGRESS entry for 17 Oct

### Built
- `infra/terraform/` replaces the 14 Oct PowerShell scripts, with the same resources and settings:
  - `versions.tf`, `providers.tf`: Terraform ≥ 1.5, `hashicorp/google ~> 8.0` (8.7.0 in the committed `.terraform.lock.hcl`, hashes for Windows, Linux and macOS). `user_project_override = true` and `billing_project = var.project_id`, so the Billing Budgets API has a quota project with Raj's user credentials.
  - `variables.tf`: `project_id`, `billing_account` (both required, format-checked), `region` (`us-central1`), `budget_usd` (200), `alert_thresholds` (`[0.5, 0.8, 1.0]`), `alert_email` (optional, empty).
  - `apis.tf`: the same 11 APIs, `google_project_service` with `disable_on_destroy = false`.
  - `iam.tf`: `sa-generator` (`pubsub.publisher`) and `sa-dataflow` (`dataflow.worker`, `pubsub.subscriber`, `pubsub.publisher`, `bigquery.dataEditor`, `bigquery.jobUser`, `storage.objectAdmin`), project level, `google_project_iam_member` only. No keys.
  - `budget.tf`: `plasma-ai-budget`, `budget_usd` USD on this project only, one `CURRENT_SPEND` threshold rule per entry in `alert_thresholds`. With `alert_email` set, also a Monitoring email channel `plasma-ai-budget-email`, attached to the budget.
  - `pubsub.tf`: topics `process-ts`, `oes-spectra`, `dead-letter`, each with a `<topic>-sub` subscription that never expires.
  - `storage.tf`: `<project_id>-oes-raw`, STANDARD, uniform access, public access prevention enforced, `force_destroy = true`, delete objects under `oes_raw/` after 30 days.
  - `bigquery.tf`: dataset `plasma_d1` in `var.region`, no tables, with a commented Day 11 hook.
  - `outputs.tf`: service account emails, topic and subscription names, bucket name, dataset id.
  - `terraform.tfvars.example`: placeholders. `terraform.tfvars` is git-ignored.
  - State: local backend. `infra/README.md` says how to move it to a GCS bucket later.
- Deleted: `infra/setup.ps1`, `teardown.ps1`, `check.ps1`, `_common.ps1`, `gcp.psd1` (Raj approved).
- `infra/README.md` rewritten: step 0 by hand, then `init` / `fmt -check` / `validate` / `plan` / `apply` / `destroy`; cost per piece; alerts only notify; project-level grants are a hardening step.
- `.gitignore`: `.terraform/`, `*.tfstate`, `*.tfstate.*`, `terraform.tfvars`, `crash.log`.
- `.github/workflows/ci.yml`: on push and PR. Job `pytest` (Python 3.11, `python -m pytest -q`) and job `terraform` (1.16.6: `fmt -check -recursive`, `init -backend=false`, `validate`). No GCP credentials.
- References to the old scripts updated in `README.md`, `plasma_ai/emulator.py` (docstrings) and `config/generator.yaml` (comment).

### How to run
```powershell
cd infra\terraform
terraform fmt -check -recursive
terraform init -backend=false
terraform validate
cd ..\..
python -m pytest -q
```
Expect no output from `fmt`, `Success! The configuration is valid.` from `validate`, and `137 passed, 1 skipped` from pytest. After Q2: README step 0, copy `terraform.tfvars.example` to `terraform.tfvars`, then `terraform init`, `plan -out tfplan`, `apply tfplan`.

### Tests
- Local (Windows 11, Terraform 1.16.6, Python 3.11):
  - `terraform fmt -check -recursive`: no output, exit 0.
  - `terraform init -backend=false`: installed `hashicorp/google v8.7.0 (signed by HashiCorp)`; "Terraform has been successfully initialized!"
  - `terraform validate`: `Success! The configuration is valid.`
  - `python -m pytest -q`: **137 passed, 1 skipped** in 7.45 s.
- CI on `feature_ai` at 0d5719e (run 39106574084, push): **green**. Job `pytest` passed (19 s); job `terraform` passed `fmt -check`, `init -backend=false` and `validate` (8 s). The per-test count is in the job log, which needs a GitHub login to read, so it was not checked.
- **Not run:** `terraform plan`, `apply`, `destroy` (by instruction; they need GCP and billing). So the resource count (29, or 30 with `alert_email`) and the absence of diffs after apply are untested.

### Assumptions made in this session
- **Install (Raj approved):** Terraform 1.16.6 via `winget install Hashicorp.Terraform`. New terminals pick it up on PATH.
- **Provider major 8** is what `terraform init` found (8.7.0, released 13 Oct). `~> 8.0` allows 8.x minor updates when the lock file is upgraded.
- **Budget filter** uses `projects/<project number>`, read with a `google_project` data source; the API stores the number, so the id would show a diff on every plan.
- **Dataset** has `delete_contents_on_destroy = true`, so `destroy` removes it with any tables, as the 14 Oct teardown (`bq rm -r -f`) did.
- **Step 0 order:** `set-quota-project` runs after `projects create`, because the project must exist first.
- Topic names, the bucket prefix and retention, and the budget name are `locals`, not variables: they change only with a PM decision.

### Deviations from CLAUDE.md
- **ST3 layout follows the 17 Oct brief, not 6A Part B:** Terraform in `infra/terraform/` instead of `config/gcp.yaml` + `00_`…`04_` PowerShell scripts. CLAUDE.md is unchanged, by instruction.
- **ST3 "done when" is not met:** nothing was applied, by instruction (Q2).
- The 14 Oct entry below still names the deleted scripts. It is kept as written, because entries are never deleted; it now carries a "superseded" note.

### Open questions / blockers
- **Q2 billing approval** blocks `terraform plan` and `apply`. (mentor)
- Raj to provide: `project_id`, `billing_account` and, optionally, `alert_email`. (Raj)
- Still not verified: whether `sa-dataflow` needs more than its six roles. First real test: the Day 12 Dataflow deploy. (Claude Code, Day 12)

### For PM: where the Terraform differs from the 14 Oct scripts
- **Same:** every name (APIs, `sa-generator`, `sa-dataflow`, roles, `plasma-ai-budget`, `plasma-ai-budget-email`, topics, `<topic>-sub`, `<project>-oes-raw`, `plasma_d1`) and every setting (region, 200 USD, 50/80/100 % of actual spend, no-expiry subscriptions, STANDARD + uniform access + public access prevention, 30-day rule on `oes_raw/`). No extra GCP resources. The only addition is a read-only lookup of the project number.
- **Budget changes** are now updated in place by `apply`; before, the script skipped an existing budget and you had to delete and recreate it.
- **No partial runs by step.** The 14 Oct note said "run only APIs, service accounts and budget now, the rest later" with `-Steps`. With Terraform that needs `-target` (for example `terraform apply -target=google_billing_budget.project`), which Terraform recommends only as an exception. If the PM wants topics, bucket and dataset on Days 8 and 11 instead, the cleaner way is to apply everything now (all free while idle) or to add a switch variable; say which.
- **Destroy** asks for `yes` instead of the project id. It never disables APIs (the old `-DisableApis` option is gone).
- **No separate check script.** `terraform plan` showing "No changes" after `apply` is the check; `terraform output` lists what exists. It does not check login or the billing link up front; `plan` fails if they are missing.
- **New one-time step 0 command:** `gcloud auth application-default set-quota-project <project_id>`.

### Next
- **Raj, after Q2:**
  1. README step 0: log in, create the project, link billing, set the ADC quota project.
  2. Copy `infra/terraform/terraform.tfvars.example` to `terraform.tfvars` and fill it in; set `pubsub.project_id` in `config/generator.yaml`.
  3. In `infra\terraform`: `terraform init`, `terraform plan -out tfplan`, paste the plan, then `terraform apply tfplan` and paste `terraform output`.
  4. Then Day 8's remote half: `python -m plasma_ai.generator --sink pubsub` against real Pub/Sub, with `PUBSUB_EMULATOR_HOST` unset.
- Raj: review and merge `feature_ai` → `main` by PR.
- Plan: Day 5 (freeze schema v0.1, PM chat), Day 6 (parameter ranges), then Day 9 (Beam v1 on the local runner).

---

## 2026-10-14: Day 2 / ST3 (scripts only) and Day 8 / ST4 (local half), plus Part A fixes

> **Superseded 17 Oct (ST3 only):** the PowerShell scripts in this entry were deleted and replaced by Terraform in `infra/terraform/`. See the 17 Oct entry. The ST4 and Part A parts still hold.

**State:** Partly done. Part A (PM fixes) and Day 8 local half: done. ST3: scripts written and dry-run tested, **not run on GCP** (billing waits on the mentor, Q2).
**Commit(s):** 2e1a850 Update CLAUDE.md brief (14 Oct: Part A and ST3 Part B) · ecf96e9 ST4: apply PM decisions on run_id, dead_letter nulls and H2 purity noise · af9dfe0 ST4: add stream disturbances and Pub/Sub sink with emulator helper · 38e305f ST3: add GCP setup, check and teardown scripts (not run; billing pending) · (this entry) Add PROGRESS entry for 14 Oct

### Built
**Part A (CLAUDE.md 6A, applied after Raj confirmed in this session):**
- `run_id` is now `SYN-YYYYMMDD-HHMMSS-nnn` from the run's UTC start time (e.g. `SYN-20261014-020000-001`). The schema pattern is `^[A-Za-z0-9_-]*[0-9]{8}-[0-9]{6}-[0-9]{3,}$`, so old-format IDs now fail validation.
- `dead_letter`: `reactor_id`, `run_id`, `seq_no`, `event_ts` and `source` may be `null`. When not null, each keeps its normal rule. All other message types still reject `null` in these fields (tested).
- H₂ purity noise now scales the impurity: `100 − (100 − purity) × (1 + N(0, σ))`, then clipped. `--no-noise` still gives exactly 99.20.
- README states that `full` OES mode is for short local or batch tests only, and that `lines` is the only streaming mode.

**Task 2, Day 8 local half (ST4):**
- `config/generator.yaml` → `disturbances:` has four switches, all `enabled: false` by default:
  - `publish_delay`: `publish_ts − event_ts` = 50 ms + Exponential(mean 150 ms).
  - `drift`: linear relative drift per hour since run start; pressure +0.3/h, T_gas −0.2/h.
  - `dropout`: per-signal chance that a reading is `null`.
  - `missing_messages`: chance that a whole `process_sample` or `oes_block` is lost. Its `seq_no` is still used, so gaps appear.
- `plasma_ai/impairments.py`: implements the four disturbances. A disabled switch draws nothing from the RNG, so default output is byte-identical to v1. It keeps per-run counts, which the CLI summary prints.
- `plasma_ai/sinks.py` → `PubSubSink`:
  - Publishes each record to `projects/<pubsub.project_id>/topics/<topic>`. The body is the message JSON; the attributes are `schema_version`, `message_type`, `run_id` and `source`.
  - Sends in `publish_ts` order, so delayed messages arrive late, out of `event_ts` order.
  - Paces to real time ÷ `--speed` (0 = as fast as possible).
  - Waits for every publish future at the end. A failed publish exits with code 3.
- CLI: `--sink file|pubsub` and `--speed`. `--sink pubsub` with `--oes-mode full` is refused (exit 2). `--no-noise` now also turns off every disturbance.
- `config/generator.yaml` → `pubsub: {project_id: plasma-ai-local, speed: 1.0}`. The client uses the emulator when `PUBSUB_EMULATOR_HOST` is set. For real Pub/Sub, unset it and set `project_id`; no code changes.
- `plasma_ai/emulator.py`: `python -m plasma_ai.emulator setup | pull`. It creates the 3 topics and one `<topic>-sub` subscription each (idempotent), and pulls and counts messages. It refuses to run unless `PUBSUB_EMULATOR_HOST` is set.
- `requirements.txt`: adds `google-cloud-pubsub~=2.42.0`.
- Tests:
  - `tests/test_disturbances.py` (15): dropout rate within 4σ, drift direction and size, delay distribution, `seq_no` gaps match the lost count, all messages validate with everything on, and `--reference-run --no-noise` is byte-identical with every switch on.
  - `tests/test_pubsub_sink.py` (11): uses a fake client.
  - `tests/test_pubsub_emulator.py` (1): skipped unless `PUBSUB_EMULATOR_HOST` is set.

**Task 1, Day 2 / ST3, scripts only (`infra/`):**
- `infra/gcp.psd1`: all settings. `PROJECT_ID`, `BILLING_ACCOUNT` and optional `ALERT_EMAIL` are placeholders. `REGION=us-central1` and `BUDGET_USD=200` come from the plan.
- `infra/setup.ps1 [-DryRun] [-Steps ...]`: runs six idempotent steps.
  1. APIs: 11 (Pub/Sub, Dataflow, BigQuery, Storage, Compute, IAM, Billing Budgets, Cloud Billing, Resource Manager, Logging, Monitoring).
  2. Service accounts: `sa-generator` (pubsub.publisher) and `sa-dataflow` (dataflow.worker, pubsub.subscriber, pubsub.publisher, bigquery.dataEditor, bigquery.jobUser, storage.objectAdmin), roles at project level.
  3. Budget: 200 USD with alerts at 50/80/100 % of actual spend.
  4. Topics `process-ts`, `oes-spectra`, `dead-letter`, each with a `<topic>-sub` subscription.
  5. Bucket `<project>-oes-raw` with a 30-day delete rule on `oes_raw/`.
  6. BigQuery dataset `plasma_d1`, with no tables.
- `infra/teardown.ps1 [-DryRun] [-Steps ...] [-DisableApis] [-Force]`: removes all of the above in reverse order. It asks you to type the project id first.
- `infra/check.ps1 [-DryRun]`: read-only. Prints `[OK]`/`[MISSING]` per item and exits 0 only when everything exists.
- `infra/_common.ps1`: shared helpers.
- `infra/README.md`: step order, cost per step, what Raj fills in, and how to undo. It says that budget alerts only notify and that project-level grants are a hardening step.

### How to run
```powershell
python -m pip install -r requirements.txt
# Emulator (terminal 1; Java + gcloud are now installed on this laptop)
gcloud beta emulators pubsub start --project=plasma-ai-local --host-port=localhost:8085
# Terminal 2
$env:PUBSUB_EMULATOR_HOST = "localhost:8085"
python -m plasma_ai.emulator setup
python -m plasma_ai.generator --duration-s 10 --seed 42 --sink pubsub      # real time; --speed 0 = no pacing
python -m plasma_ai.emulator pull
python -m pytest -q
# GCP scripts, print only (nothing runs)
.\infra\setup.ps1 -DryRun ; .\infra\teardown.ps1 -DryRun ; .\infra\check.ps1 -DryRun
```
A 10 s run without disturbances gives 100 `oes_block` and 103 `process-ts` messages, and 0 dead letters. In this session a 3 s run pulled back exactly 30, 33 and 0. With disturbances on, counts drop by the lost messages, and the summary line lists them (`disturbances: missing.oes_block=3 ... null.power_kw=2`).

### Tests
- `python -m pytest -q` without the emulator: **137 passed, 1 skipped** (the emulator test), 6.5 s.
- With `PUBSUB_EMULATOR_HOST=localhost:8085` and the emulator running: **138 passed**, 10.9 s. The 73 tests from 12 Oct all still pass unchanged, except `test_consecutive_runs_follow_each_other`, which now expects the new run_id format.
- Manual emulator runs, all disturbances on:
  - 10 s at `--speed 1` took 12.4 s wall time (11 s of stream, including the 1 s outcome delay). All 199 published messages were pulled back.
  - 60 s at `--speed 20` took about 3 s of stream: 593 `oes_block` and 594 `process-ts` messages were published and all of them pulled back.
- DoD 1: a 60 s file run takes 1.6 s. DoD 4: `--reference-run --no-noise` gives purity 99.20 and yield 68.00 exactly.
- ST3 scripts:
  - `setup.ps1 -DryRun`, `teardown.ps1 -DryRun -DisableApis` and `check.ps1 -DryRun` ran clean on Windows PowerShell 5.1.
  - `check.ps1` without `-DryRun` ran its local checks: gcloud found, not logged in, placeholders not filled. It made no GCP call.
  - `setup.ps1` without `-DryRun` refuses while placeholders remain.
  - Every gcloud flag used was checked against the local `gcloud ... --help`.
  - **No command has run against GCP**, so idempotency on real resources is untested.

### Sample output
```json
{"schema_version":"0.1","message_type":"process_sample","message_id":"f9b399c5-2a3e-4974-a13d-c91c0dc421b1","source":"synthetic_generator","reactor_id":"MW-PR-01","run_id":"SYN-20261014-020000-001","seq_no":8,"event_ts":"2026-10-14T02:00:00.800000Z","publish_ts":"2026-10-14T02:00:00.892155Z","power_kw":null,"reflected_power_w":124.6977,"ch4_slpm":11.4395,"h2_slpm":3.5632,"pressure_kpa":91.2687,"re_z_ohm":33.9687,"im_z_ohm":11.0211,"gas_temperature_k":2296.7431,"plasma_state":{"ne_cm3":3.3529e14,"te_ev":2.8792,"stability_index":0.9447,"carbon_growth_index":0.6670}}
{"schema_version":"0.1","message_type":"run_outcome","message_id":"b976badf-cabe-4d0b-afb4-4b650ddcab27","source":"synthetic_generator","reactor_id":"MW-PR-01","run_id":"SYN-20261014-020000-001","seq_no":0,"event_ts":"2026-10-14T02:00:11.000000Z","publish_ts":"2026-10-14T02:00:11.067580Z","graphite_yield_percent":58.1092,"raman_id_ig":0.2417,"xrd_002_fwhm_deg":0.3794,"h2_purity_percent":99.3919}
```
(Numbers are trimmed to 4 decimals here. Disturbances were all on, seed 42: `power_kw` dropped out and `publish_ts` is 92 ms after `event_ts`.)

### Assumptions made in this session
- **Installs (Raj approved):** Eclipse Temurin JRE 21 and Google Cloud SDK 589.0.0 via winget, plus the gcloud components `pubsub-emulator` and `beta`. Installing components non-interactively needs `CLOUDSDK_PYTHON` set from `gcloud components copy-bundled-python`. New terminals pick up gcloud on PATH.
- **Disturbances are off by default** so the v1 contract and the existing tests hold. `--no-noise` turns them all off, so the slide 3 reference stays exact whatever the config says.
- Drift is linear in time since run start and resets each run.
- Dropouts apply to the 8 process signals only; `plasma_state` labels are never null.
- Only `process_sample` and `oes_block` can be lost; run events never are.
- Disturbance magnitudes are placeholders, sized to be visible in short demos.
- **`publish_ts` is the simulated value** (`event_ts` + delay), not the wall-clock send time. With `--speed` ≠ 1 or a past `--start-ts`, the two differ. Pub/Sub's own `publish_time` holds the real arrival time.
- The Pub/Sub sink publishes in `publish_ts` order. Out-of-order arrival (by `event_ts`) therefore comes from delay jitter; there is no separate out-of-order switch. The file sink keeps `event_ts` order.
- No ordering keys and no batching settings: client defaults.
- `pubsub.project_id` lives in `config/generator.yaml`, so the project id is set in two files (that one and `infra/gcp.psd1`).
- **dead_letter schema:** done with a `$defs/dead_letter_envelope` in `envelope.schema.json` that reuses the envelope field rules, because `allOf` cannot loosen the strict envelope.
- **ST3 config is `infra/gcp.psd1`**, a PowerShell data file read with `Import-PowerShellDataFile`. Windows PowerShell 5.1 has no YAML parser, and the brief allowed "gcp.env or similar". Keys use the brief's names.
- **APIs:** the union of the brief's list and CLAUDE.md's list, plus `cloudbilling` (needed to read the billing link).
- **Budget mail:** goes to the billing account's admins and users by default. `ALERT_EMAIL`, if set, adds a Cloud Monitoring email channel.
- **Subscriptions:** `--expiration-period=never` (the default is 31 idle days); other settings are defaults. The bucket is STANDARD storage with uniform access and public access prevention. The dataset is in `us-central1`.
- **Teardown:** keeps the APIs unless `-DisableApis` is given. It never touches the project or the billing link.
- **Not automated:** creating the project and linking billing (README step 0, by hand).

### Deviations from CLAUDE.md
- **ST3 layout follows the session brief, not 6A Part B:** `setup.ps1` / `teardown.ps1` / `check.ps1` + `infra/gcp.psd1`, instead of `config/gcp.yaml` + `00_`…`04_` scripts.
- **`setup.ps1` also creates resources CLAUDE.md assigned to later days** (as the brief asked): topics and subscriptions (Day 8), the bucket and the dataset (Day 11). Nothing was run.
- **ST3 "done when" is not met:** no command was run against GCP, by instruction (Q2).
- Day 8 (local half) was done before Days 5–6, at Raj's request.

### Open questions / blockers
- **Q2 billing approval** blocks running `infra/setup.ps1`. (mentor)
- Raj to provide: `PROJECT_ID`, `BILLING_ACCOUNT` and, optionally, `ALERT_EMAIL`. (Raj)
- Not verified: whether `sa-dataflow` needs more than its six roles (for example `roles/pubsub.viewer` for subscription metadata). The first real test is the Day 12 Dataflow deploy. (Claude Code, Day 12)

### For PM (proposed changes, not applied)
- **Disturbances for demos:** they are off by default. Proposal: turn on `publish_delay`, `dropout` and `missing_messages` for the Day 13 end-to-end demo, so Beam's null handling, gap detection and late-data windowing are shown. This is a config change only.
- **Drift and dropout magnitudes** (pressure +30 %/h, T_gas −20 %/h, 1–2 % nulls, 1 % lost messages) are demo placeholders. Real sensor drift is far smaller. Replace them once the client gives sensor specs.
- **ST2 note on timestamps:** Beam should window on `event_ts`. `publish_ts` is the producer's claim, and Pub/Sub `publish_time` is the real arrival. Proposal: add one line to ST2 saying so.
- **ST3 scope moved earlier:** topics, subscriptions, bucket and dataset are now in the ST3 setup script (not run). If the PM prefers creating them on Days 8 and 11, use `setup.ps1 -Steps apis,serviceaccounts,budget` now and the rest later; no code change is needed.

### Next
- **Raj, after Q2:**
  1. README step 0: `gcloud auth login`, ADC login, create the project, link billing.
  2. Fill in `infra/gcp.psd1` and `pubsub.project_id` in `config/generator.yaml`.
  3. Run `.\infra\check.ps1` → `.\infra\setup.ps1 -DryRun` → `.\infra\setup.ps1` → `.\infra\check.ps1`, and paste the output.
  4. Then Day 8's remote half: `python -m plasma_ai.generator --sink pubsub` against real Pub/Sub, with `PUBSUB_EMULATOR_HOST` unset.
- Raj: review and merge `feature_ai` → `main` by PR.
- Plan: Day 5 (freeze schema v0.1, PM chat), Day 6 (parameter ranges), then Day 9 (Beam v1 on the local runner; it can read from the emulator).

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

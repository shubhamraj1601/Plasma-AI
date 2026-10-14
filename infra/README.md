# infra: GCP foundation (ST3)

PowerShell scripts that call `gcloud` and `bq` to set up, check and remove the Plasma-AI resources on GCP. No Terraform.

| File | What it does |
|---|---|
| `gcp.psd1` | All settings: project, billing account, region, budget, APIs, service accounts, topics, bucket, dataset. Committed; holds no secrets. |
| `setup.ps1` | Creates everything below. Idempotent: anything that exists is skipped. |
| `check.ps1` | Read-only. Lists what exists (`[OK]` / `[MISSING]`); exit code 0 only when all is there. |
| `teardown.ps1` | Removes what `setup.ps1` created, in reverse order. Asks you to type the project id first. |
| `_common.ps1` | Shared helpers (dot-sourced by the three scripts). |

Every script takes `-DryRun`: it prints each command and runs none (read-only checks are printed too, not run). `setup.ps1` and `teardown.ps1` take `-Steps` to run only some steps, e.g. `-Steps apis,serviceaccounts,budget`.

## What Raj fills in

In `gcp.psd1`:
- `PROJECT_ID`: a new, dedicated project, e.g. `plasma-ai-d1`.
- `BILLING_ACCOUNT`: format `000000-000000-000000` (`gcloud billing accounts list`).
- `ALERT_EMAIL` (optional): budget mail always goes to the billing account's admins and users; set this to add one more address (it creates a Cloud Monitoring email channel).

The scripts refuse to run (except with `-DryRun`) while `PROJECT_ID` or `BILLING_ACCOUNT` still start with `REPLACE-ME`. `REGION` (us-central1, P-07) and `BUDGET_USD` (200, Q2) are already set from the plan.

Then set `pubsub.project_id` in `config/generator.yaml` to the same project id (used by the generator's `--sink pubsub`).

## Order of steps

**Step 0, by hand (Raj, once Q2 billing is approved).** These create the project and link billing, so the scripts do not do them:

```powershell
gcloud auth login
gcloud auth application-default login
gcloud projects create plasma-ai-d1 --name="Plasma-AI D1"
gcloud billing projects link plasma-ai-d1 --billing-account=000000-000000-000000
gcloud config set project plasma-ai-d1
```

If scripts are blocked, allow local scripts once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

**Steps 1 to 6: `setup.ps1`.** Look at the dry run first, then run it:

```powershell
.\infra\check.ps1                 # read-only: login, project, billing
.\infra\setup.ps1 -DryRun         # print every command
.\infra\setup.ps1                 # run all six steps
.\infra\check.ps1                 # everything [OK]
```

| # | Step (`-Steps` name) | Creates | Cost |
|---|---|---|---|
| 1 | `apis` | Enables Pub/Sub, Dataflow, BigQuery, Cloud Storage, Compute, IAM, Billing Budgets, Cloud Billing, Resource Manager, Logging, Monitoring | Free. Enabling an API costs nothing; no VM or job is started. |
| 2 | `serviceaccounts` | `sa-generator` (`roles/pubsub.publisher`); `sa-dataflow` (`dataflow.worker`, `pubsub.subscriber`, `pubsub.publisher` for dead-letter, `bigquery.dataEditor`, `bigquery.jobUser`, `storage.objectAdmin`) | Free |
| 3 | `budget` | Budget of 200 USD on this project, alerts at 50 / 80 / 100 % of actual spend | Free |
| 4 | `pubsub` | Topics `process-ts`, `oes-spectra`, `dead-letter`, each with one subscription `<topic>-sub` (no expiry) | Free while idle. Throughput: first 10 GiB/month free, then about 40 USD/TiB. A lines-mode demo is about 0.27 GB/h published, plus the same again for delivery, so roughly 20 h/month fits the free tier. |
| 5 | `bucket` | `gs://<project>-oes-raw` in us-central1, uniform access, public access blocked, lifecycle rule: delete objects under `oes_raw/` after 30 days | Free while empty. Standard storage is about 0.02 USD/GB-month; the free tier covers 5 GB-month in us-central1. The 30-day rule caps growth. |
| 6 | `bigquery` | Dataset `plasma_d1` in us-central1, no tables (designs in the plan doc, tab ST2; created on Day 11) | Free while empty. Storage: first 10 GiB/month free; queries: first 1 TiB/month free. |

Prices are approximate list prices; check the GCP pricing pages before the Day 13 cost report. The cost that matters is Dataflow (Day 12), which this folder does not start. Per P-06, run Dataflow only during work sessions and drain it afterwards.

## Notes

- **Budget alerts only notify. They do not stop spending.** A real alert cannot fire with zero spend. The first check that alerts arrive is after the Day 12 Dataflow run.
- **Changing the budget:** `setup.ps1` skips an existing budget. To change the amount or email, run `teardown.ps1 -Steps budget`, then `setup.ps1 -Steps budget`.
- **Roles are granted at project level** for now (simplest). Topic-, bucket- and dataset-level grants are a hardening step. No role is broader than needed for its job, and no service account keys are created. Local runs use your application-default credentials; Dataflow runs as `sa-dataflow`. To publish locally as `sa-generator` without a key: `gcloud auth application-default login --impersonate-service-account=sa-generator@<project>.iam.gserviceaccount.com` (needs `roles/iam.serviceAccountTokenCreator` on it).
- **Topic names** must match `topics:` in `config/generator.yaml`. The subscription naming rule `<topic>-sub` matches `python -m plasma_ai.emulator setup`, which builds the same layout on the local emulator.
- **Undo:** `.\infra\teardown.ps1 -DryRun`, then `.\infra\teardown.ps1`. It deletes the dataset (with any tables), the bucket (with all objects), the subscriptions, the topics, the budget (and email channel), and the role grants and service accounts. APIs stay enabled (free); add `-DisableApis` to turn them off too. The project and its billing link are not touched; to delete the whole project: `gcloud projects delete <project>`.
- If a newly created service account is not visible yet, role grants are retried up to 5 times, 10 s apart.

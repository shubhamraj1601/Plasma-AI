# infra: GCP foundation (ST3)

Terraform for the Plasma-AI resources on GCP. Everything lives in `infra/terraform/`. **Nothing has been applied yet** (billing waits on Q2).

| File | What it holds |
|---|---|
| `versions.tf` | Terraform ≥ 1.5 and the `hashicorp/google` provider `~> 8.0` (8.7.0 in `.terraform.lock.hcl`, which is committed). |
| `providers.tf` | Provider settings: project, region, and `user_project_override` + `billing_project` (the Billing Budgets API needs a quota project with user credentials). |
| `variables.tf` | `project_id`, `billing_account`, `region`, `budget_usd`, `alert_thresholds`, `alert_email`. |
| `apis.tf` | The 11 APIs. |
| `iam.tf` | `sa-generator` and `sa-dataflow` with their project-level roles. |
| `budget.tf` | The budget and the optional email notification channel. |
| `pubsub.tf` | Three topics, one `<topic>-sub` subscription each. |
| `storage.tf` | The raw OES bucket and its lifecycle rule. |
| `bigquery.tf` | Dataset `plasma_d1`, no tables (commented hook for Day 11). |
| `outputs.tf` | Service account emails, topic and subscription names, bucket name, dataset id. |
| `terraform.tfvars.example` | Template for your values. Copy it to `terraform.tfvars`, which is git-ignored. |

State is local (`infra/terraform/terraform.tfstate`, git-ignored). Never commit state, `.terraform/`, `terraform.tfvars` or any key file.

## What Raj fills in

Copy `infra/terraform/terraform.tfvars.example` to `infra/terraform/terraform.tfvars` and set:
- `project_id`: a new, dedicated project, e.g. `plasma-ai-d1`.
- `billing_account`: format `000000-000000-000000` (`gcloud billing accounts list`).
- `alert_email` (optional): budget mail always goes to the billing account's admins and users; set this to add one more address (it creates a Cloud Monitoring email channel).

`region` (us-central1, P-07), `budget_usd` (200, Q2) and `alert_thresholds` (50 / 80 / 100 %) already default to the plan's values.

Then set `pubsub.project_id` in `config/generator.yaml` to the same project id (used by the generator's `--sink pubsub`).

## Order of steps

**Step 0, by hand (Raj, once Q2 billing is approved).** Log in, then create the project and link billing; Terraform does not do these:

```powershell
gcloud auth login
gcloud auth application-default login
gcloud projects create plasma-ai-d1 --name="Plasma-AI D1"
gcloud billing projects link plasma-ai-d1 --billing-account=000000-000000-000000
gcloud auth application-default set-quota-project plasma-ai-d1
gcloud config set project plasma-ai-d1
```

`set-quota-project` comes after `projects create`, because the project must exist first.

**Then Terraform**, from `infra/terraform`. Read the plan before you apply it:

```powershell
cd infra\terraform
terraform init                    # downloads the provider pinned in .terraform.lock.hcl
terraform fmt -check -recursive   # formatting (no output = clean)
terraform validate                # syntax and types; no GCP calls
terraform plan -out tfplan        # read-only: lists what would be created
terraform apply tfplan            # creates it
terraform output                  # service account emails, topics, bucket, dataset
```

The first `plan` should show 29 resources to add (30 with `alert_email` set): 11 APIs, 2 service accounts, 7 role grants, the budget, 3 topics, 3 subscriptions, the bucket and the dataset. Re-running `plan` after `apply` should show no changes.

**Undo:** `terraform plan -destroy` to see what would go, then `terraform destroy`. It deletes the dataset (with any tables), the bucket (with all objects), the subscriptions, the topics, the budget (and email channel), the role grants and the service accounts. APIs stay enabled (`disable_on_destroy = false`; enabling them is free). The project and its billing link are not touched; to delete the whole project: `gcloud projects delete <project>`.

## What gets created and what it costs

| Piece | Creates | Cost |
|---|---|---|
| APIs | Pub/Sub, Dataflow, BigQuery, Cloud Storage, Compute, IAM, Billing Budgets, Cloud Billing, Resource Manager, Logging, Monitoring | Free. Enabling an API costs nothing; no VM or job is started. |
| Service accounts | `sa-generator` (`roles/pubsub.publisher`); `sa-dataflow` (`dataflow.worker`, `pubsub.subscriber`, `pubsub.publisher` for dead-letter, `bigquery.dataEditor`, `bigquery.jobUser`, `storage.objectAdmin`) | Free |
| Budget | `plasma-ai-budget`: 200 USD on this project only, alerts at 50 / 80 / 100 % of current spend | Free |
| Pub/Sub | Topics `process-ts`, `oes-spectra`, `dead-letter`, each with one subscription `<topic>-sub` (never expires) | Free while idle. Throughput: first 10 GiB/month free, then about 40 USD/TiB. A lines-mode demo is about 0.27 GB/h published, plus the same again for delivery, so roughly 20 h/month fits the free tier. |
| Bucket | `<project>-oes-raw` in us-central1, STANDARD, uniform access, public access prevention enforced, lifecycle rule: delete objects under `oes_raw/` after 30 days | Free while empty. Standard storage is about 0.02 USD/GB-month; the free tier covers 5 GB-month in us-central1. The 30-day rule caps growth. |
| BigQuery | Dataset `plasma_d1` in us-central1, no tables (designs in the plan doc, tab ST2; created on Day 11) | Free while empty. Storage: first 10 GiB/month free; queries: first 1 TiB/month free. |

Prices are approximate list prices; check the GCP pricing pages before the Day 13 cost report. The cost that matters is Dataflow (Day 12), which this folder does not start. Per P-06, run Dataflow only during work sessions and drain it afterwards.

## Notes

- **Budget alerts only notify. They do not stop spending.** A real alert cannot fire with zero spend. The first check that alerts arrive is after the Day 12 Dataflow run.
- **Changing the budget:** edit `budget_usd`, `alert_thresholds` or `alert_email` in `terraform.tfvars`, then `plan` and `apply`. Terraform updates the budget in place.
- **Roles are granted at project level** for now (simplest). Topic-, bucket- and dataset-level grants are a hardening step. Grants use `google_project_iam_member`, which adds one member to one role; never switch to `_iam_binding` or `_iam_policy`, which would remove other members' roles. No role is broader than needed for its job, and no service account keys are created. Local runs use your application-default credentials; Dataflow runs as `sa-dataflow`. To publish locally as `sa-generator` without a key: `gcloud auth application-default login --impersonate-service-account=sa-generator@<project>.iam.gserviceaccount.com` (needs `roles/iam.serviceAccountTokenCreator` on it).
- **Topic names** must match `topics:` in `config/generator.yaml`. The subscription naming rule `<topic>-sub` matches `python -m plasma_ai.emulator setup`, which builds the same layout on the local emulator.
- **Demo data only:** the bucket has `force_destroy = true` and the dataset `delete_contents_on_destroy = true`, so `terraform destroy` removes their contents without asking again.
- **If the first `apply` stops with "API has not been used in project … or it is disabled"**, the new APIs were still switching on. Wait a minute and run `terraform apply` again; finished resources are not touched.
- **CI** (`.github/workflows/ci.yml`) runs `terraform fmt -check`, `init -backend=false` and `validate` on every push and PR. It has no GCP credentials and never plans or applies.

## State

State is local for now. To move it to Cloud Storage later (once more than one person applies, or before the laptop matters):

1. Create a separate state bucket by hand, e.g. `gcloud storage buckets create gs://<project>-tfstate --location=us-central1 --uniform-bucket-level-access --public-access-prevention`, then `gcloud storage buckets update gs://<project>-tfstate --versioning`. Do not use `<project>-oes-raw`: it has `force_destroy` and a delete rule.
2. Add a backend block inside `terraform { }` in `versions.tf`:
   ```hcl
   backend "gcs" {
     bucket = "<project>-tfstate"
     prefix = "plasma-ai/st3"
   }
   ```
3. Run `terraform init -migrate-state` and answer `yes`. Then delete the local `terraform.tfstate*` files.

CI keeps working unchanged, because it runs `init -backend=false`.

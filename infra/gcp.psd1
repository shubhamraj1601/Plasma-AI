# GCP settings for infra/setup.ps1, teardown.ps1 and check.ps1 (PowerShell data file).
# No secrets here: this file is committed. Never put service account keys in the repo.
#
# Raj fills in the three REPLACE-ME values once the project and billing exist (Q2).
@{
    # --- Raj fills these in -------------------------------------------------
    PROJECT_ID      = 'REPLACE-ME-project-id'        # e.g. plasma-ai-d1 (a new, dedicated project)
    BILLING_ACCOUNT = 'REPLACE-ME-billing-account'   # format 000000-000000-000000 (gcloud billing accounts list)
    ALERT_EMAIL     = ''                             # optional extra recipient; billing admins always get budget mail

    # --- Defaults from the plan (change only with a PM decision) -------------
    REGION           = 'us-central1'                 # P-07 (pending)
    BUDGET_USD       = 200                           # Q2 assumption
    ALERT_THRESHOLDS = @(0.5, 0.8, 1.0)              # share of the budget, actual spend
    BUDGET_NAME      = 'plasma-ai-budget'

    APIS = @(
        'pubsub.googleapis.com'
        'dataflow.googleapis.com'
        'bigquery.googleapis.com'
        'storage.googleapis.com'
        'compute.googleapis.com'
        'iam.googleapis.com'
        'billingbudgets.googleapis.com'
        'cloudbilling.googleapis.com'
        'cloudresourcemanager.googleapis.com'
        'logging.googleapis.com'
        'monitoring.googleapis.com'
    )

    # Project-level roles for now; topic-, bucket- and dataset-level grants are a hardening step.
    SERVICE_ACCOUNTS = @(
        @{ Name = 'sa-generator'; DisplayName = 'Plasma-AI synthetic generator'; Roles = @('roles/pubsub.publisher') }
        @{ Name = 'sa-dataflow'; DisplayName = 'Plasma-AI Dataflow workers'; Roles = @(
                'roles/dataflow.worker'
                'roles/pubsub.subscriber'
                'roles/pubsub.publisher'          # dead-letter topic
                'roles/bigquery.dataEditor'
                'roles/bigquery.jobUser'
                'roles/storage.objectAdmin'
            )
        }
    )

    # P-04 (pending): two topics plus dead-letter, one subscription each, named <topic>-sub.
    # Must match `topics:` in config/generator.yaml.
    TOPICS = @('process-ts', 'oes-spectra', 'dead-letter')

    # P-03 (pending): raw spectra in Cloud Storage. Bucket name = <PROJECT_ID><BUCKET_SUFFIX>.
    BUCKET_SUFFIX         = '-oes-raw'
    RAW_PREFIX            = 'oes_raw/'
    RAW_RETENTION_DAYS    = 30

    # BigQuery dataset only; tables come on Day 11 (design in the plan doc, tab ST2).
    BQ_DATASET = 'plasma_d1'
}

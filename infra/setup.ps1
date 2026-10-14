<#
.SYNOPSIS
    Create the Plasma-AI GCP foundation (ST3). Idempotent: anything that already exists is skipped.

.DESCRIPTION
    Steps, in order (all by default; pick some with -Steps):
      apis             enable the APIs listed in gcp.psd1
      serviceaccounts  sa-generator (Pub/Sub publisher) and sa-dataflow (worker roles), project-level roles
      budget           USD budget on the project with alerts at 50 / 80 / 100 % of actual spend
      pubsub           topics process-ts, oes-spectra, dead-letter, one <topic>-sub subscription each
      bucket           gs://<project>-oes-raw with a 30-day delete rule on oes_raw/
      bigquery         dataset plasma_d1 (no tables; they come on Day 11)
    The project itself and its billing link are made by Raj beforehand (see README.md).

.EXAMPLE
    .\infra\setup.ps1 -DryRun                       # print every command, run nothing
    .\infra\setup.ps1                               # run all steps
    .\infra\setup.ps1 -Steps apis,serviceaccounts,budget
#>
[CmdletBinding()]
param(
    [switch]$DryRun,
    [ValidateSet('apis', 'serviceaccounts', 'budget', 'pubsub', 'bucket', 'bigquery')]
    [string[]]$Steps = @('apis', 'serviceaccounts', 'budget', 'pubsub', 'bucket', 'bigquery'),
    [string]$Config = ''   # default: gcp.psd1 next to this script
)
$ErrorActionPreference = 'Stop'
if (-not $Config) { $Config = Join-Path $PSScriptRoot 'gcp.psd1' }
. (Join-Path $PSScriptRoot '_common.ps1')

Initialize-Gcp -DryRun $DryRun
$cfg = Read-GcpConfig -Path $Config -AllowPlaceholders:$DryRun
$P = $cfg.PROJECT_ID
if ($DryRun) { Write-Host 'DRY RUN: nothing is created or changed. Read-only checks are printed and assumed "missing".' -ForegroundColor Cyan }
Write-Host "Project $P, region $($cfg.REGION), steps: $($Steps -join ', ')"

if (-not $DryRun) {
    $account = Get-Lines gcloud.cmd @('config', 'list', '--format=value(core.account)')
    if (-not $account) { throw 'No gcloud account is active. Run: gcloud auth login' }
    if (-not (Test-Exists gcloud.cmd @('projects', 'describe', $P))) { throw "Project $P not found or not visible to $account." }
    $billing = Get-Lines gcloud.cmd @('billing', 'projects', 'describe', $P, '--format=value(billingEnabled)')
    if ("$billing" -ne 'True') { throw "Billing is not enabled on $P. Link the billing account first (README.md, step 0)." }
}

if ($Steps -contains 'apis') {
    Write-Step 'APIs'
    $enabled = @(Get-Lines gcloud.cmd @('services', 'list', '--enabled', "--project=$P", '--format=value(config.name)'))
    $missing = @($cfg.APIS | Where-Object { $enabled -notcontains $_ })
    $cfg.APIS | Where-Object { $enabled -contains $_ } | ForEach-Object { Write-Skip "API $_" }
    if ($missing) { Invoke-Change gcloud.cmd (@('services', 'enable') + $missing + @("--project=$P")) | Out-Null }
}

if ($Steps -contains 'serviceaccounts') {
    Write-Step 'Service accounts and project-level roles'
    foreach ($sa in $cfg.SERVICE_ACCOUNTS) {
        if (Test-Exists gcloud.cmd @('iam', 'service-accounts', 'describe', $sa.Email, "--project=$P")) {
            Write-Skip "service account $($sa.Email)"
        } else {
            Invoke-Change gcloud.cmd @('iam', 'service-accounts', 'create', $sa.Name, "--display-name=$($sa.DisplayName)", "--project=$P") | Out-Null
        }
        $granted = @(Get-SaRoles $cfg $sa.Email)
        foreach ($role in $sa.Roles) {
            if ($granted -contains $role) { Write-Skip "$role for $($sa.Name)"; continue }
            Invoke-Change gcloud.cmd @('projects', 'add-iam-policy-binding', $P, "--member=serviceAccount:$($sa.Email)",
                "--role=$role", '--condition=None', '--quiet', '--format=none') -Retries 5 | Out-Null
        }
    }
}

if ($Steps -contains 'budget') {
    Write-Step "Budget $($cfg.BUDGET_USD) USD with alerts at $(($cfg.ALERT_THRESHOLDS | ForEach-Object { '{0:P0}' -f $_ }) -join ' / ')"
    if (@(Get-BudgetNames $cfg)) {
        Write-Skip "budget $($cfg.BUDGET_NAME) (to change it: teardown.ps1 -Steps budget, then setup.ps1 -Steps budget)"
    } else {
        $budgetArgs = @('billing', 'budgets', 'create', "--billing-account=$($cfg.BILLING_ACCOUNT)",
            "--display-name=$($cfg.BUDGET_NAME)", "--budget-amount=$($cfg.BUDGET_USD)USD", "--filter-projects=projects/$P")
        foreach ($t in $cfg.ALERT_THRESHOLDS) { $budgetArgs += "--threshold-rule=percent=$($t.ToString($script:Invariant))" }
        if ($cfg.ALERT_EMAIL) {
            # Billing admins get budget mail by default; an extra address needs a Cloud Monitoring email channel.
            $channel = @(Get-ChannelNames $cfg) | Select-Object -First 1
            if ($channel) {
                Write-Skip "notification channel $($cfg.CHANNEL_NAME)"
            } else {
                $channel = @(Invoke-Change gcloud.cmd @('beta', 'monitoring', 'channels', 'create', "--project=$P",
                        "--display-name=$($cfg.CHANNEL_NAME)", '--type=email', "--channel-labels=email_address=$($cfg.ALERT_EMAIL)",
                        '--format=value(name)')) | Select-Object -Last 1
                if (-not $channel) { $channel = "projects/$P/notificationChannels/<id from the command above>" }
            }
            $budgetArgs += "--notifications-rule-monitoring-notification-channels=$channel"
        }
        Invoke-Change gcloud.cmd $budgetArgs | Out-Null
    }
}

if ($Steps -contains 'pubsub') {
    Write-Step 'Pub/Sub topics and subscriptions'
    foreach ($topic in $cfg.TOPICS) {
        if (Test-Exists gcloud.cmd @('pubsub', 'topics', 'describe', $topic, "--project=$P")) { Write-Skip "topic $topic" }
        else { Invoke-Change gcloud.cmd @('pubsub', 'topics', 'create', $topic, "--project=$P") | Out-Null }
        $sub = "$topic-sub"
        if (Test-Exists gcloud.cmd @('pubsub', 'subscriptions', 'describe', $sub, "--project=$P")) { Write-Skip "subscription $sub" }
        else {
            # Default: subscriptions expire after 31 idle days; "never" keeps them for the whole project.
            Invoke-Change gcloud.cmd @('pubsub', 'subscriptions', 'create', $sub, "--topic=$topic", '--expiration-period=never',
                "--project=$P") | Out-Null
        }
    }
}

if ($Steps -contains 'bucket') {
    Write-Step "Cloud Storage bucket gs://$($cfg.BUCKET)"
    if (Test-Exists gcloud.cmd @('storage', 'buckets', 'describe', "gs://$($cfg.BUCKET)", '--format=none')) {
        Write-Skip "bucket gs://$($cfg.BUCKET)"
    } else {
        Invoke-Change gcloud.cmd @('storage', 'buckets', 'create', "gs://$($cfg.BUCKET)", "--project=$P", "--location=$($cfg.REGION)",
            '--default-storage-class=STANDARD', '--uniform-bucket-level-access', '--public-access-prevention') | Out-Null
    }
    if (Test-LifecycleApplied $cfg) {
        Write-Skip "lifecycle rule: delete $($cfg.RAW_PREFIX) after $($cfg.RAW_RETENTION_DAYS) days"
    } else {
        $rulePath = Join-Path ([IO.Path]::GetTempPath()) 'plasma-ai-lifecycle.json'
        if (-not $DryRun) { [IO.File]::WriteAllText($rulePath, (Get-LifecycleRule $cfg), (New-Object Text.UTF8Encoding($false))) }
        Write-Host "  lifecycle file $rulePath = $(Get-LifecycleRule $cfg)"
        Invoke-Change gcloud.cmd @('storage', 'buckets', 'update', "gs://$($cfg.BUCKET)", "--lifecycle-file=$rulePath") | Out-Null
    }
}

if ($Steps -contains 'bigquery') {
    Write-Step "BigQuery dataset $($cfg.BQ_DATASET) (no tables yet)"
    $dataset = "${P}:$($cfg.BQ_DATASET)"
    if (Test-Exists bq.cmd @("--project_id=$P", 'show', '--format=none', $dataset)) { Write-Skip "dataset $dataset" }
    else {
        Invoke-Change bq.cmd @("--project_id=$P", "--location=$($cfg.REGION)", 'mk', '--dataset',
            '--description=Plasma-AI D1 data (tables from Day 11)', $dataset) | Out-Null
    }
}

Write-Host "`nDone. Verify with: .\infra\check.ps1" -ForegroundColor Green

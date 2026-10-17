<#
.SYNOPSIS
    Remove what setup.ps1 created, in reverse order. Missing resources are skipped.

.DESCRIPTION
    Steps (all by default; pick some with -Steps):
      bigquery         delete dataset plasma_d1 AND ALL ITS TABLES
      bucket           delete gs://<project>-oes-raw AND ALL ITS OBJECTS
      pubsub           delete the subscriptions, then the topics
      budget           delete the budget and the optional email notification channel
      serviceaccounts  remove the project-level roles, then delete both service accounts
    APIs stay enabled (they cost nothing); add -DisableApis to turn them off too.
    The project and its billing link are left alone.
    Asks you to type the project id before deleting anything, unless -DryRun or -Force.

.EXAMPLE
    .\infra\teardown.ps1 -DryRun
    .\infra\teardown.ps1
    .\infra\teardown.ps1 -Steps budget
#>
[CmdletBinding()]
param(
    [switch]$DryRun,
    [ValidateSet('bigquery', 'bucket', 'pubsub', 'budget', 'serviceaccounts')]
    [string[]]$Steps = @('bigquery', 'bucket', 'pubsub', 'budget', 'serviceaccounts'),
    [switch]$DisableApis,
    [switch]$Force,
    [string]$Config = ''   # default: gcp.psd1 next to this script
)
$ErrorActionPreference = 'Stop'
if (-not $Config) { $Config = Join-Path $PSScriptRoot 'gcp.psd1' }
. (Join-Path $PSScriptRoot '_common.ps1')

Initialize-Gcp -DryRun $DryRun
$cfg = Read-GcpConfig -Path $Config -AllowPlaceholders:$DryRun
$P = $cfg.PROJECT_ID
if ($DryRun) { Write-Host 'DRY RUN: nothing is deleted. Read-only checks are printed; deletions are printed as if everything existed.' -ForegroundColor Cyan }
Write-Host "Project $P, steps: $($Steps -join ', ')$(if ($DisableApis) { ', disable APIs' })"

if (-not $DryRun -and -not $Force) {
    $answer = Read-Host "This deletes data in $P (dataset, bucket objects, topics). Type the project id to continue"
    if ($answer -ne $P) { Write-Host 'Cancelled; nothing was deleted.'; exit 1 }
}

# In dry-run every existence check is "missing", so print deletions unconditionally there.
function Test-Present { param([string]$Exe, [string[]]$Arguments) return ($script:GcpDryRun -or (Test-Exists $Exe $Arguments)) }

if ($Steps -contains 'bigquery') {
    Write-Step "BigQuery dataset $($cfg.BQ_DATASET)"
    $dataset = "${P}:$($cfg.BQ_DATASET)"
    if (Test-Present bq.cmd @("--project_id=$P", 'show', '--format=none', $dataset)) {
        Invoke-Change bq.cmd @("--project_id=$P", 'rm', '-r', '-f', '-d', $dataset) | Out-Null
    } else { Write-Host "  [skip]    dataset $dataset (not found)" -ForegroundColor DarkGray }
}

if ($Steps -contains 'bucket') {
    Write-Step "Cloud Storage bucket gs://$($cfg.BUCKET)"
    if (Test-Present gcloud.cmd @('storage', 'buckets', 'describe', "gs://$($cfg.BUCKET)", '--format=none')) {
        Invoke-Change gcloud.cmd @('storage', 'rm', '--recursive', "gs://$($cfg.BUCKET)") | Out-Null
    } else { Write-Host "  [skip]    bucket gs://$($cfg.BUCKET) (not found)" -ForegroundColor DarkGray }
}

if ($Steps -contains 'pubsub') {
    Write-Step 'Pub/Sub subscriptions and topics'
    foreach ($topic in $cfg.TOPICS) {
        $sub = "$topic-sub"
        if (Test-Present gcloud.cmd @('pubsub', 'subscriptions', 'describe', $sub, "--project=$P")) {
            Invoke-Change gcloud.cmd @('pubsub', 'subscriptions', 'delete', $sub, "--project=$P", '--quiet') | Out-Null
        } else { Write-Host "  [skip]    subscription $sub (not found)" -ForegroundColor DarkGray }
    }
    foreach ($topic in $cfg.TOPICS) {
        if (Test-Present gcloud.cmd @('pubsub', 'topics', 'describe', $topic, "--project=$P")) {
            Invoke-Change gcloud.cmd @('pubsub', 'topics', 'delete', $topic, "--project=$P", '--quiet') | Out-Null
        } else { Write-Host "  [skip]    topic $topic (not found)" -ForegroundColor DarkGray }
    }
}

if ($Steps -contains 'budget') {
    Write-Step "Budget $($cfg.BUDGET_NAME) and notification channel"
    $budgets = @(Get-BudgetNames $cfg)
    if ($DryRun) { $budgets = @("billingAccounts/$($cfg.BILLING_ACCOUNT)/budgets/<id>") }
    if (-not $budgets) { Write-Host "  [skip]    budget $($cfg.BUDGET_NAME) (not found)" -ForegroundColor DarkGray }
    foreach ($name in $budgets) { Invoke-Change gcloud.cmd @('billing', 'budgets', 'delete', $name, '--quiet') | Out-Null }
    $channels = @(Get-ChannelNames $cfg)
    if ($DryRun -and $cfg.ALERT_EMAIL) { $channels = @("projects/$P/notificationChannels/<id>") }
    foreach ($name in $channels) {
        Invoke-Change gcloud.cmd @('beta', 'monitoring', 'channels', 'delete', $name, "--project=$P", '--force', '--quiet') | Out-Null
    }
}

if ($Steps -contains 'serviceaccounts') {
    Write-Step 'Service accounts and their project-level roles'
    foreach ($sa in $cfg.SERVICE_ACCOUNTS) {
        $granted = @(Get-SaRoles $cfg $sa.Email)
        if ($DryRun) { $granted = $sa.Roles }
        foreach ($role in $sa.Roles | Where-Object { $granted -contains $_ }) {
            Invoke-Change gcloud.cmd @('projects', 'remove-iam-policy-binding', $P, "--member=serviceAccount:$($sa.Email)",
                "--role=$role", '--condition=None', '--quiet', '--format=none') | Out-Null
        }
        if (Test-Present gcloud.cmd @('iam', 'service-accounts', 'describe', $sa.Email, "--project=$P")) {
            Invoke-Change gcloud.cmd @('iam', 'service-accounts', 'delete', $sa.Email, "--project=$P", '--quiet') | Out-Null
        } else { Write-Host "  [skip]    service account $($sa.Email) (not found)" -ForegroundColor DarkGray }
    }
}

if ($DisableApis) {
    Write-Step 'APIs'
    $enabled = @(Get-Lines gcloud.cmd @('services', 'list', '--enabled', "--project=$P", '--format=value(config.name)'))
    if ($DryRun) { $enabled = $cfg.APIS }
    $toDisable = @($cfg.APIS | Where-Object { $enabled -contains $_ })
    if ($toDisable) { Invoke-Change gcloud.cmd (@('services', 'disable') + $toDisable + @("--project=$P", '--force', '--quiet')) | Out-Null }
}

Write-Host "`nDone. Check what is left with: .\infra\check.ps1" -ForegroundColor Green

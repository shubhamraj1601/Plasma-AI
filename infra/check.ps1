<#
.SYNOPSIS
    Read-only: show what exists of the Plasma-AI GCP foundation. Never creates or changes anything.

.DESCRIPTION
    Checks tools, login, project, billing, APIs, service accounts and roles, budget, Pub/Sub topics and
    subscriptions, the bucket and its lifecycle rule, and the BigQuery dataset. Prints [OK] / [MISSING]
    per item. Exit code 0 when everything exists, 1 otherwise.

.EXAMPLE
    .\infra\check.ps1
    .\infra\check.ps1 -DryRun     # print the read-only commands without running them
#>
[CmdletBinding()]
param(
    [switch]$DryRun,
    [string]$Config = ''   # default: gcp.psd1 next to this script
)
$ErrorActionPreference = 'Stop'
if (-not $Config) { $Config = Join-Path $PSScriptRoot 'gcp.psd1' }
. (Join-Path $PSScriptRoot '_common.ps1')

$script:Missing = 0
function Write-Result {
    param([bool]$Ok, [string]$What, [string]$Detail = '')
    if ($script:GcpDryRun) { return }
    if ($Ok) { Write-Host "  [OK]      $What $Detail" -ForegroundColor Green }
    else { Write-Host "  [MISSING] $What $Detail" -ForegroundColor Red; $script:Missing++ }
}

Initialize-Gcp -DryRun $DryRun
$script:GcpQueriesMayFail = $true
$cfg = Read-GcpConfig -Path $Config -AllowPlaceholders
$P = $cfg.PROJECT_ID

Write-Step 'Local tools and login'
$gcloud = Get-Command gcloud.cmd -ErrorAction SilentlyContinue
Write-Result ([bool]$gcloud) 'gcloud' $(if ($gcloud) { $gcloud.Source })
if (-not $gcloud) { Write-Host 'Install the Google Cloud SDK first (infra/README.md).'; exit 1 }
$account = @(Get-Lines gcloud.cmd @('config', 'list', '--format=value(core.account)'))
Write-Result ([bool]$account) 'gcloud auth login' $(if ($account) { "($account)" } else { '(run: gcloud auth login)' })
$adc = Join-Path $env:APPDATA 'gcloud\application_default_credentials.json'
Write-Result (Test-Path $adc) 'application-default credentials' $(if (-not (Test-Path $adc)) { '(run: gcloud auth application-default login)' })
if ($cfg.HasPlaceholders) {
    Write-Result $false "values in $Config" '(PROJECT_ID / BILLING_ACCOUNT still REPLACE-ME)'
    if (-not $DryRun) { Write-Host "`nFill in $Config, then run this again."; exit 1 }
}
if (-not $account -and -not $DryRun) { Write-Host "`nLog in first, then run this again."; exit 1 }

Write-Step "Project $P"
$state = @(Get-Lines gcloud.cmd @('projects', 'describe', $P, '--format=value(lifecycleState)'))
Write-Result ("$state" -eq 'ACTIVE') "project $P" "($state)"
$billing = @(Get-Lines gcloud.cmd @('billing', 'projects', 'describe', $P, '--format=value(billingEnabled,billingAccountName)'))
Write-Result ("$billing" -like 'True*') 'billing linked' "($billing)"

Write-Step 'APIs'
$enabled = @(Get-Lines gcloud.cmd @('services', 'list', '--enabled', "--project=$P", '--format=value(config.name)'))
foreach ($api in $cfg.APIS) { Write-Result ($enabled -contains $api) $api }

Write-Step 'Service accounts and project-level roles'
foreach ($sa in $cfg.SERVICE_ACCOUNTS) {
    Write-Result (Test-Exists gcloud.cmd @('iam', 'service-accounts', 'describe', $sa.Email, "--project=$P")) $sa.Email
    $granted = @(Get-SaRoles $cfg $sa.Email)
    foreach ($role in $sa.Roles) { Write-Result ($granted -contains $role) "  $role" }
    foreach ($extra in $granted | Where-Object { $sa.Roles -notcontains $_ }) {
        if (-not $DryRun) { Write-Host "  [EXTRA]     $extra (granted outside setup.ps1)" -ForegroundColor Yellow }
    }
}

Write-Step "Budget $($cfg.BUDGET_NAME)"
$budgetJson = @(Get-Lines gcloud.cmd @('billing', 'budgets', 'list', "--billing-account=$($cfg.BILLING_ACCOUNT)",
        "--filter=displayName=$($cfg.BUDGET_NAME)", '--format=json'))
$budgets = @()
if ($budgetJson) { $budgets = @(($budgetJson -join "`n") | ConvertFrom-Json) }
Write-Result ($budgets.Count -ge 1) "budget $($cfg.BUDGET_NAME)"
foreach ($b in $budgets) {
    $amount = "$($b.amount.specifiedAmount.units) $($b.amount.specifiedAmount.currencyCode)"
    $thresholds = @($b.thresholdRules | ForEach-Object { '{0:P0}' -f [double]$_.thresholdPercent }) -join ' / '
    $channels = @($b.notificationsRule.monitoringNotificationChannels) -join ', '
    Write-Host "            amount $amount; thresholds $thresholds; projects $(@($b.budgetFilter.projects) -join ', ')"
    Write-Host "            recipients: billing admins$(if ($channels) { " + channel(s) $channels" })"
}
if ($cfg.ALERT_EMAIL) {
    $channelJson = @(Get-Lines gcloud.cmd @('beta', 'monitoring', 'channels', 'list', "--project=$P",
            "--filter=displayName=$($cfg.CHANNEL_NAME)", '--format=json(name,labels.email_address)'))
    $found = $false
    if ($channelJson) { $found = @(($channelJson -join "`n") | ConvertFrom-Json).Count -ge 1 }
    Write-Result $found "email channel $($cfg.CHANNEL_NAME)" "($($cfg.ALERT_EMAIL))"
}

Write-Step 'Pub/Sub'
foreach ($topic in $cfg.TOPICS) {
    Write-Result (Test-Exists gcloud.cmd @('pubsub', 'topics', 'describe', $topic, "--project=$P", '--format=none')) "topic $topic"
    Write-Result (Test-Exists gcloud.cmd @('pubsub', 'subscriptions', 'describe', "$topic-sub", "--project=$P", '--format=none')) "subscription $topic-sub"
}

Write-Step 'Cloud Storage'
Write-Result (Test-Exists gcloud.cmd @('storage', 'buckets', 'describe', "gs://$($cfg.BUCKET)", '--format=none')) "bucket gs://$($cfg.BUCKET)"
if (-not $DryRun) {
    Write-Result (Test-LifecycleApplied $cfg) "lifecycle: delete $($cfg.RAW_PREFIX) after $($cfg.RAW_RETENTION_DAYS) days"
}

Write-Step 'BigQuery'
Write-Result (Test-Exists bq.cmd @("--project_id=$P", 'show', '--format=none', "${P}:$($cfg.BQ_DATASET)")) "dataset $($cfg.BQ_DATASET)"

if ($DryRun) { Write-Host "`nDry run: the read-only commands above were printed, not run."; exit 0 }
if ($script:Missing -eq 0) { Write-Host "`nAll present." -ForegroundColor Green; exit 0 }
Write-Host "`n$($script:Missing) item(s) missing." -ForegroundColor Red
exit 1

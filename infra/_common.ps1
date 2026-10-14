# Shared helpers for setup.ps1, teardown.ps1 and check.ps1. Dot-source it; do not run it directly.
# Windows PowerShell 5.1 compatible (no ternary, no ??, no &&).

$script:GcpDryRun = $false
$script:GcpQueriesMayFail = $false   # check.ps1 sets this: a failed query then reads as "nothing found"
$script:Invariant = [Globalization.CultureInfo]::InvariantCulture

function Initialize-Gcp {
    <# Remember the dry-run switch and put gcloud on PATH if it is installed but the shell has not picked it up yet. #>
    param([bool]$DryRun)
    $script:GcpDryRun = $DryRun
    if (-not (Get-Command gcloud.cmd -ErrorAction SilentlyContinue)) {
        $sdkBin = Join-Path $env:LOCALAPPDATA 'Google\Cloud SDK\google-cloud-sdk\bin'
        if (Test-Path (Join-Path $sdkBin 'gcloud.cmd')) { $env:PATH = "$sdkBin;$env:PATH" }
    }
    if (-not $DryRun -and -not (Get-Command gcloud.cmd -ErrorAction SilentlyContinue)) {
        throw 'gcloud is not installed or not on PATH. Install the Google Cloud SDK first (see infra/README.md).'
    }
}

function Read-GcpConfig {
    <# Load infra/gcp.psd1 and add derived names. Placeholders are allowed only in dry-run mode. #>
    param([string]$Path, [switch]$AllowPlaceholders)
    if (-not (Test-Path $Path)) { throw "Config file not found: $Path" }
    $cfg = Import-PowerShellDataFile -Path $Path
    foreach ($key in 'PROJECT_ID', 'BILLING_ACCOUNT', 'REGION', 'BUDGET_USD', 'ALERT_THRESHOLDS', 'BUDGET_NAME',
        'APIS', 'SERVICE_ACCOUNTS', 'TOPICS', 'BUCKET_SUFFIX', 'RAW_PREFIX', 'RAW_RETENTION_DAYS', 'BQ_DATASET') {
        if (-not $cfg.ContainsKey($key)) { throw "$Path is missing $key" }
    }
    $placeholders = @('PROJECT_ID', 'BILLING_ACCOUNT') | Where-Object { $cfg[$_] -like 'REPLACE-ME*' }
    $cfg.HasPlaceholders = [bool]$placeholders
    if ($placeholders -and -not $AllowPlaceholders) {
        throw "Fill in $($placeholders -join ' and ') in $Path first (or use -DryRun to only print the commands)."
    }
    $cfg.BUCKET = "$($cfg.PROJECT_ID)$($cfg.BUCKET_SUFFIX)"
    $cfg.CHANNEL_NAME = "$($cfg.BUDGET_NAME)-email"
    foreach ($sa in $cfg.SERVICE_ACCOUNTS) { $sa.Email = "$($sa.Name)@$($cfg.PROJECT_ID).iam.gserviceaccount.com" }
    return $cfg
}

function Format-CommandLine {
    param([string]$Exe, [string[]]$Arguments)
    $parts = @($Exe -replace '\.cmd$', '') + ($Arguments | ForEach-Object { if ($_ -match '\s') { "`"$_`"" } else { $_ } })
    return $parts -join ' '
}

function Invoke-NativeQuiet {
    <# Run a native command; returns @{ Code; Lines }. stderr is merged into Lines as text. #>
    param([string]$Exe, [string[]]$Arguments)
    $ErrorActionPreference = 'Continue'   # stderr from native tools must not throw in Windows PowerShell 5.1
    $lines = & $Exe @Arguments 2>&1 | ForEach-Object { "$_" }
    return @{ Code = $LASTEXITCODE; Lines = @($lines) }
}

function Invoke-Change {
    <# Run a command that creates, changes or deletes something. Dry-run only prints it. Throws on failure. #>
    param([string]$Exe, [string[]]$Arguments, [int]$Retries = 0)
    $line = Format-CommandLine $Exe $Arguments
    if ($script:GcpDryRun) { Write-Host "  [dry-run] $line" -ForegroundColor Cyan; return @() }
    Write-Host "  [run]     $line" -ForegroundColor Yellow
    for ($attempt = 0; $attempt -le $Retries; $attempt++) {
        $result = Invoke-NativeQuiet $Exe $Arguments
        if ($result.Code -eq 0) { return $result.Lines }
        if ($attempt -lt $Retries) {
            Write-Host "            failed (exit $($result.Code)); retrying in 10 s (new service accounts take a moment to appear)"
            Start-Sleep -Seconds 10
        }
    }
    $result.Lines | ForEach-Object { Write-Host "            $_" }
    throw "Command failed (exit $($result.Code)): $line"
}

function Test-Exists {
    <# Read-only existence check: exit code 0 means the resource exists. Dry-run prints it and assumes "missing". #>
    param([string]$Exe, [string[]]$Arguments)
    $line = Format-CommandLine $Exe $Arguments
    if ($script:GcpDryRun) { Write-Host "  [dry-run] $line   (read-only check; assumed missing)" -ForegroundColor DarkCyan; return $false }
    return (Invoke-NativeQuiet $Exe $Arguments).Code -eq 0
}

function Get-Lines {
    <# Read-only query returning output lines. Dry-run prints it and returns nothing. Throws on failure. #>
    param([string]$Exe, [string[]]$Arguments)
    $line = Format-CommandLine $Exe $Arguments
    if ($script:GcpDryRun) { Write-Host "  [dry-run] $line   (read-only query)" -ForegroundColor DarkCyan; return @() }
    $result = Invoke-NativeQuiet $Exe $Arguments
    if ($result.Code -ne 0) {
        if ($script:GcpQueriesMayFail) {
            Write-Host "            (query failed: $(@($result.Lines)[0]))" -ForegroundColor DarkYellow
            return @()
        }
        $result.Lines | ForEach-Object { Write-Host "            $_" }
        throw "Query failed (exit $($result.Code)): $line"
    }
    return @($result.Lines | Where-Object { $_ -ne '' })
}

function Write-Skip { param([string]$What) Write-Host "  [skip]    $What (already exists)" -ForegroundColor DarkGray }
function Write-Step { param([string]$What) Write-Host "`n== $What" -ForegroundColor Green }

function Get-SaRoles {
    <# Project-level roles currently granted to one service account. #>
    param($Cfg, [string]$Email)
    return Get-Lines gcloud.cmd @('projects', 'get-iam-policy', $Cfg.PROJECT_ID, '--flatten=bindings[].members',
        "--filter=bindings.members:serviceAccount:$Email", '--format=value(bindings.role)')
}

function Get-BudgetNames {
    param($Cfg)
    return Get-Lines gcloud.cmd @('billing', 'budgets', 'list', "--billing-account=$($Cfg.BILLING_ACCOUNT)",
        "--filter=displayName=$($Cfg.BUDGET_NAME)", '--format=value(name)')
}

function Get-ChannelNames {
    param($Cfg)
    return Get-Lines gcloud.cmd @('beta', 'monitoring', 'channels', 'list', "--project=$($Cfg.PROJECT_ID)",
        "--filter=displayName=$($Cfg.CHANNEL_NAME)", '--format=value(name)')
}

function Get-LifecycleRule {
    <# The JSON lifecycle config setup.ps1 applies: delete objects under RAW_PREFIX after RAW_RETENTION_DAYS. #>
    param($Cfg)
    $rule = @{ action = @{ type = 'Delete' }; condition = @{ age = $Cfg.RAW_RETENTION_DAYS; matchesPrefix = @($Cfg.RAW_PREFIX) } }
    return (@{ rule = @($rule) } | ConvertTo-Json -Depth 5 -Compress)
}

function Test-LifecycleApplied {
    <# True if the bucket already has the delete rule (age + prefix) from the config. #>
    param($Cfg)
    if ($script:GcpDryRun) { return $false }
    $result = Invoke-NativeQuiet gcloud.cmd @('storage', 'buckets', 'describe', "gs://$($Cfg.BUCKET)", '--format=json(lifecycle_config)')
    if ($result.Code -ne 0) { return $false }
    $json = ($result.Lines -join "`n") | ConvertFrom-Json
    if (-not $json.lifecycle_config) { return $false }
    foreach ($r in @($json.lifecycle_config.rule)) {
        if ($r.action.type -eq 'Delete' -and $r.condition.age -eq $Cfg.RAW_RETENTION_DAYS -and
            @($r.condition.matchesPrefix) -contains $Cfg.RAW_PREFIX) { return $true }
    }
    return $false
}

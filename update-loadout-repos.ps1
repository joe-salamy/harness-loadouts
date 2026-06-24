<#
.SYNOPSIS
    Reapply a loadout to every repository recorded for that loadout.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [string]$Loadout
)

$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$LoadoutsDir = Join-Path $ScriptRoot "loadouts"
$LoadoutPath = Join-Path $LoadoutsDir $Loadout
$UsagePath = Join-Path $LoadoutPath ".harness-loadout/applied-repos.json"
$HarnessInit = Join-Path $ScriptRoot "harness-init.ps1"

if (-not (Test-Path $LoadoutPath -PathType Container)) {
    Write-Host "Error: Loadout '$Loadout' not found." -ForegroundColor Red
    Write-Host "Available loadouts:"
    Get-ChildItem -Path $LoadoutsDir -Directory | ForEach-Object { Write-Host "  - $($_.Name)" }
    exit 1
}

if (-not (Test-Path $UsagePath)) {
    Write-Host "No repositories recorded for loadout '$Loadout'."
    exit 0
}

try {
    $data = Get-Content -Raw $UsagePath | ConvertFrom-Json
} catch {
    Write-Host "Error: Could not parse registry '$UsagePath'." -ForegroundColor Red
    exit 1
}

if ($data.version -ne 1) {
    Write-Host "Error: Unsupported registry version in '$UsagePath'." -ForegroundColor Red
    exit 1
}

if (-not $data.PSObject.Properties["repos"]) {
    Write-Host "Error: Registry '$UsagePath' is missing repos." -ForegroundColor Red
    exit 1
}

$Pwsh = (Get-Command pwsh -ErrorAction Stop).Source
$updated = 0
$planned = 0
$skipped = 0
$failed = 0

foreach ($repo in @($data.repos)) {
    if ($null -eq $repo -or [string]::IsNullOrWhiteSpace([string]$repo.path) -or [string]::IsNullOrWhiteSpace([string]$repo.harness)) {
        Write-Warning "Skipping malformed registry entry in $UsagePath."
        $skipped++
        continue
    }

    if (-not (Test-Path $repo.path -PathType Container)) {
        Write-Warning "Skipping missing repo: $($repo.path)"
        $skipped++
        continue
    }

    if (-not $PSCmdlet.ShouldProcess($repo.path, "Apply loadout '$Loadout' for harness '$($repo.harness)'")) {
        Write-Host "Planned update for repo: $($repo.path)" -ForegroundColor Cyan
        & $Pwsh -NoProfile -ExecutionPolicy Bypass -File $HarnessInit -Loadout $Loadout -Target $repo.path -Harness $repo.harness -Force -PlanChanges
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Failed to plan repo: $($repo.path)"
            $failed++
            continue
        }
        $planned++
        continue
    }

    & $Pwsh -NoProfile -ExecutionPolicy Bypass -File $HarnessInit -Loadout $Loadout -Target $repo.path -Harness $repo.harness -Force
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Failed to update repo: $($repo.path)"
        $failed++
        continue
    }

    $updated++
}

Write-Host "Updated: $updated; planned: $planned; skipped: $skipped; failed: $failed."
if ($failed -gt 0) {
    exit 1
}
exit 0

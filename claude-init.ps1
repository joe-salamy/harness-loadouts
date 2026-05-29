<#
.SYNOPSIS
    Deprecated compatibility wrapper for harness-init.ps1.
#>
param(
    [string]$Loadout,
    [string]$Target = ".",
    [ValidateSet("opencode", "codex", "gemini", "claude-code")]
    [string]$Harness = "claude-code",
    [switch]$List
)

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$HarnessInit = Join-Path $ScriptRoot "harness-init.ps1"

Write-Host "claude-init.ps1 is deprecated. Use harness-init.ps1 instead." -ForegroundColor DarkYellow

& $HarnessInit -Loadout $Loadout -Target $Target -Harness $Harness -List:$List
exit $LASTEXITCODE

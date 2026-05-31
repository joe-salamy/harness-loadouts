<#
.SYNOPSIS
    Apply an agent harness loadout to a target repository.
.DESCRIPTION
    Copies instructions, skills, hooks, agents, commands, and other files from
    a harness-agnostic loadout template into a target repo. Templates use
    AGENTS.md and .harness/; the required -Harness flag controls the target
    config directory.
.EXAMPLE
    .\harness-init.ps1 -Loadout python -Target C:\path\to\repo -Harness codex
.EXAMPLE
    .\harness-init.ps1 -List
#>
param(
    [string]$Loadout,
    [string]$Target = ".",
    [ValidateSet("opencode", "codex", "gemini", "claude", "claude-code", "omp")]
    [string]$Harness,
    [switch]$List
)

$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$LoadoutsDir = Join-Path $ScriptRoot "loadouts"

function Join-RepoPath {
    param([string]$Root, [string]$RelativePath)
    $parts = $RelativePath -split "[/\\]" | Where-Object { $_ }
    $path = $Root
    foreach ($part in $parts) {
        $path = Join-Path $path $part
    }
    return $path
}

function Get-HarnessProfile {
    param([string]$Name)

    $normalizedName = if ($Name -eq "claude-code") { "claude" } else { $Name }
    $configDir = ".$normalizedName"
    $hookConfigPath = $null
    $hookSourcePaths = @(".harness/hooks.json")

    switch ($normalizedName) {
        "codex" {
            $hookConfigPath = ".codex/hooks.json"
            $hookSourcePaths += @(".codex/hooks.json")
        }
        "gemini" {
            $hookConfigPath = ".gemini/settings.json"
            $hookSourcePaths += @(".gemini/settings.json")
        }
        "claude" {
            $hookConfigPath = ".claude/settings.local.json"
            $hookSourcePaths += @(".claude/settings.local.json", ".claude/hooks.json")
        }
    }

    return [PSCustomObject]@{
        Name = $normalizedName
        InstructionFile = "AGENTS.md"
        InstructionAliases = @("CLAUDE.md", "GEMINI.md")
        TemplateConfigDir = ".harness"
        ConfigDir = $configDir
        ConfigDirs = @($configDir)
        SkillsPath = "$configDir/skills"
        SkillSourcePaths = @(".harness/skills", "$configDir/skills", ".opencode/skills", ".codex/skills", ".agents/skills", ".claude/skills")
        HookConfigPath = $hookConfigPath
        HookSourcePaths = $hookSourcePaths
    }
}

function ConvertTo-Array {
    param($Value)
    if ($null -eq $Value) {
        return @()
    }
    if ($Value -is [System.Array]) {
        return @($Value)
    }
    return @($Value)
}

function Get-HookEntryKey {
    param($Entry)

    if ($null -eq $Entry) {
        return ""
    }
    return ($Entry | ConvertTo-Json -Depth 20 -Compress)
}

function Merge-HooksObject {
    param($Existing, $Incoming)

    if ($null -eq $Existing) {
        $Existing = [PSCustomObject]@{}
    }
    if ($null -eq $Incoming) {
        return $Existing
    }

    foreach ($event in $Incoming.PSObject.Properties) {
        $eventName = $event.Name
        $incomingEntries = @(ConvertTo-Array $event.Value)

        if ($Existing.PSObject.Properties[$eventName]) {
            $existingEntries = @(ConvertTo-Array $Existing.$eventName)
            $existingKeys = @{}
            foreach ($entry in $existingEntries) {
                $existingKeys[(Get-HookEntryKey $entry)] = $true
            }

            $addedCount = 0
            foreach ($entry in $incomingEntries) {
                $key = Get-HookEntryKey $entry
                if (-not $existingKeys.ContainsKey($key)) {
                    $existingEntries += $entry
                    $existingKeys[$key] = $true
                    $addedCount++
                }
            }

            $Existing.$eventName = [object[]]$existingEntries
            if ($addedCount -gt 0) {
                Write-Host "  [MERGED]   $addedCount new hook(s) into '$eventName'" -ForegroundColor Green
            } else {
                Write-Host "  [SKIPPED]  '$eventName' hooks already present" -ForegroundColor DarkYellow
            }
        } else {
            $Existing | Add-Member -NotePropertyName $eventName -NotePropertyValue ([object[]]$incomingEntries)
            Write-Host "  [ADDED]    '$eventName' hooks ($($incomingEntries.Count) entry/entries)" -ForegroundColor Green
        }
    }

    return $Existing
}

function Merge-HookConfig {
    param([string]$Source, [string]$Dest)

    if (-not (Test-Path $Source)) {
        return
    }

    $sourceData = Get-Content -Raw $Source | ConvertFrom-Json
    $destDir = Split-Path -Parent $Dest
    if (-not (Test-Path $destDir)) {
        New-Item -ItemType Directory -Force -Path $destDir | Out-Null
    }

    if (Test-Path $Dest) {
        $destData = Get-Content -Raw $Dest | ConvertFrom-Json
    } else {
        $destData = [PSCustomObject]@{}
    }

    if ($sourceData.PSObject.Properties["hooks"]) {
        if (-not $destData.PSObject.Properties["hooks"]) {
            $destData | Add-Member -NotePropertyName "hooks" -NotePropertyValue ([PSCustomObject]@{})
        }
        $destData.hooks = Merge-HooksObject -Existing $destData.hooks -Incoming $sourceData.hooks
    }

    foreach ($property in $sourceData.PSObject.Properties) {
        if ($property.Name -eq "hooks") {
            continue
        }
        if (-not $destData.PSObject.Properties[$property.Name]) {
            $destData | Add-Member -NotePropertyName $property.Name -NotePropertyValue $property.Value
            Write-Host "  [ADDED]    '$($property.Name)' into $($Dest.Replace($Target, '').TrimStart('\', '/'))" -ForegroundColor Green
        }
    }

    $destJson = $destData | ConvertTo-Json -Depth 20
    [System.IO.File]::WriteAllText($Dest, $destJson)
    Write-Host "  [MERGED]   $($Dest.Replace($Target, '').TrimStart('\', '/'))" -ForegroundColor Green
}

function Copy-FileWithPrompt {
    param([string]$Source, [string]$Dest)

    if (Test-Path $Dest) {
        $relPath = $Dest.Replace($Target, "").TrimStart("\", "/")
        Write-Host "  [EXISTS]   '$relPath' already exists in target." -ForegroundColor DarkYellow
        $overwrite = Read-Host "           Overwrite? (y/N)"
        if ($overwrite -eq "y" -or $overwrite -eq "Y") {
            Copy-Item -Path $Source -Destination $Dest -Force
            Write-Host "           Overwritten." -ForegroundColor Yellow
        } else {
            Write-Host "           Skipped." -ForegroundColor DarkYellow
        }
    } else {
        $destDir = Split-Path -Parent $Dest
        if (-not (Test-Path $destDir)) {
            New-Item -ItemType Directory -Force -Path $destDir | Out-Null
        }
        Copy-Item -Path $Source -Destination $Dest -Force
        $relPath = $Dest.Replace($Target, "").TrimStart("\", "/")
        Write-Host "  [COPIED]   $relPath" -ForegroundColor Green
    }
}

function Copy-DirectoryWithPrompt {
    param([string]$Source, [string]$Dest, [string[]]$SkipRelativePaths = @(), [string]$Base = $Source)

    if (-not (Test-Path $Dest)) {
        New-Item -ItemType Directory -Force -Path $Dest | Out-Null
    }

    foreach ($child in Get-ChildItem -Path $Source -Force) {
        $relative = $child.FullName.Substring($Base.Length).TrimStart("\", "/")
        $normalized = $relative.Replace("\", "/")
        if ($SkipRelativePaths -contains $normalized) {
            continue
        }

        $childDest = Join-Path $Dest $child.Name
        if ($child.PSIsContainer) {
            Copy-DirectoryWithPrompt -Source $child.FullName -Dest $childDest -SkipRelativePaths $SkipRelativePaths -Base $Base
        } else {
            Copy-FileWithPrompt -Source $child.FullName -Dest $childDest
        }
    }
}

function Copy-Skills {
    param([string]$Source, [string]$Dest)

    if (-not $Source -or -not (Test-Path $Source)) {
        return
    }

    New-Item -ItemType Directory -Force -Path $Dest | Out-Null
    $copiedCount = 0
    $skippedCount = 0

    foreach ($skill in Get-ChildItem -Path $Source -Force) {
        $targetSkillPath = Join-Path $Dest $skill.Name
        if (Test-Path $targetSkillPath) {
            Write-Host "  [EXISTS]   Skill '$($skill.Name)' already exists in target." -ForegroundColor DarkYellow
            $overwrite = Read-Host "           Overwrite? (y/N)"
            if ($overwrite -eq "y" -or $overwrite -eq "Y") {
                Copy-Item -Path $skill.FullName -Destination $Dest -Recurse -Force
                $copiedCount++
                Write-Host "           Overwritten." -ForegroundColor Yellow
            } else {
                $skippedCount++
                Write-Host "           Skipped." -ForegroundColor DarkYellow
            }
        } else {
            Copy-Item -Path $skill.FullName -Destination $Dest -Recurse -Force
            $copiedCount++
        }
    }

    Write-Host "  [SKILLS]   $copiedCount copied, $skippedCount skipped" -ForegroundColor Green
}

function Copy-InstructionFile {
    param([object]$Profile, [string]$LoadoutPath, [string]$Target)

    $sourceFile = Join-RepoPath $LoadoutPath $Profile.InstructionFile
    foreach ($alias in $Profile.InstructionAliases) {
        if (-not (Test-Path $sourceFile)) {
            $sourceFile = Join-RepoPath $LoadoutPath $alias
        }
    }

    if (-not (Test-Path $sourceFile)) {
        return
    }

    $targetFile = Join-RepoPath $Target $Profile.InstructionFile
    $loadoutContent = [System.IO.File]::ReadAllText($sourceFile)

    if (Test-Path $targetFile) {
        $existing = [System.IO.File]::ReadAllText($targetFile)
        if ($existing.Contains($loadoutContent.Trim())) {
            Write-Host "  [SKIPPED]  $($Profile.InstructionFile) (loadout content already present)" -ForegroundColor DarkYellow
        } else {
            $date = Get-Date -Format "yyyy-MM-dd"
            $separator = "`n`n---`n`n<!-- Loadout: $Loadout; harness: $($Profile.Name); applied $date -->`n`n"
            [System.IO.File]::WriteAllText($targetFile, $existing + $separator + $loadoutContent)
            Write-Host "  [APPENDED] $($Profile.InstructionFile)" -ForegroundColor Yellow
        }
    } else {
        [System.IO.File]::WriteAllText($targetFile, $loadoutContent)
        Write-Host "  [COPIED]   $($Profile.InstructionFile)" -ForegroundColor Green
    }
}

if ($List) {
    Write-Host "Available loadouts:"
    Get-ChildItem -Path $LoadoutsDir -Directory | ForEach-Object { Write-Host "  - $($_.Name)" }
    Write-Host ""
    Write-Host "Harnesses: opencode, codex, gemini, claude (alias: claude-code), omp"
    exit 0
}

if (-not $Loadout) {
    Write-Host "Error: -Loadout is required. Use -List to see available loadouts." -ForegroundColor Red
    exit 1
}

if (-not $Harness) {
    Write-Host "Error: -Harness is required. Supported values: opencode, codex, gemini, claude, claude-code, omp." -ForegroundColor Red
    exit 1
}

$LoadoutPath = Join-Path $LoadoutsDir $Loadout
if (-not (Test-Path $LoadoutPath)) {
    Write-Host "Error: Loadout '$Loadout' not found." -ForegroundColor Red
    Write-Host "Available loadouts:"
    Get-ChildItem -Path $LoadoutsDir -Directory | ForEach-Object { Write-Host "  - $($_.Name)" }
    exit 1
}

$Target = (Resolve-Path $Target).Path
if (-not (Test-Path $Target -PathType Container)) {
    Write-Host "Error: Target '$Target' is not a directory." -ForegroundColor Red
    exit 1
}

$profile = Get-HarnessProfile $Harness
Write-Host "Applying loadout '$Loadout' for '$Harness' to: $Target" -ForegroundColor Cyan

Copy-InstructionFile -Profile $profile -LoadoutPath $LoadoutPath -Target $Target

if ($profile.SkillsPath) {
    $sourceSkills = $null
    foreach ($skillSourcePath in $profile.SkillSourcePaths) {
        $candidate = Join-RepoPath $LoadoutPath $skillSourcePath
        if (Test-Path $candidate) {
            $sourceSkills = $candidate
            break
        }
    }
    $targetSkills = Join-RepoPath $Target $profile.SkillsPath
    Copy-Skills -Source $sourceSkills -Dest $targetSkills
}

$skipTopLevel = @($profile.InstructionFile) + $profile.InstructionAliases
$skipByConfigDir = @{}

if ($profile.SkillsPath) {
    $skillsParts = $profile.SkillsPath -split "[/\\]"
    $configDir = $skillsParts[0]
    $skipRel = ($skillsParts[1..($skillsParts.Length - 1)] -join "/")
    $skipByConfigDir[$configDir] = @($skipByConfigDir[$configDir]) + $skipRel
}

if ($profile.HookConfigPath) {
    $sourceHookConfig = Join-RepoPath $LoadoutPath $profile.HookConfigPath
    if ($profile.PSObject.Properties["HookSourcePaths"]) {
        foreach ($hookSourcePath in $profile.HookSourcePaths) {
            $candidate = Join-RepoPath $LoadoutPath $hookSourcePath
            if (Test-Path $candidate) {
                $sourceHookConfig = $candidate
                break
            }
        }
    }
    $targetHookConfig = Join-RepoPath $Target $profile.HookConfigPath
    Merge-HookConfig -Source $sourceHookConfig -Dest $targetHookConfig

    $hookParts = $profile.HookConfigPath -split "[/\\]"
    $configDir = $hookParts[0]
    $skipRel = ($hookParts[1..($hookParts.Length - 1)] -join "/")
    $skipByConfigDir[$configDir] = @($skipByConfigDir[$configDir]) + $skipRel
    if ($profile.PSObject.Properties["HookSourcePaths"]) {
        foreach ($hookSourcePath in $profile.HookSourcePaths) {
            $sourceParts = $hookSourcePath -split "[/\\]"
            if ($sourceParts[0] -eq $configDir -or $sourceParts[0] -eq $profile.TemplateConfigDir) {
                $sourceSkipRel = ($sourceParts[1..($sourceParts.Length - 1)] -join "/")
                $skipByConfigDir[$configDir] = @($skipByConfigDir[$configDir]) + $sourceSkipRel
            }
        }
    }
}

$knownHarnessDirs = @(".harness", ".claude", ".opencode", ".codex", ".agents", ".gemini", ".omp")

foreach ($item in Get-ChildItem -Path $LoadoutPath -Force) {
    if ($skipTopLevel -contains $item.Name) {
        continue
    }
    if ($item.PSIsContainer -and ($knownHarnessDirs -contains $item.Name) -and ($item.Name -ne $profile.TemplateConfigDir) -and -not ($profile.ConfigDirs -contains $item.Name)) {
        continue
    }

    $destName = if ($item.PSIsContainer -and $item.Name -eq $profile.TemplateConfigDir) { $profile.ConfigDir } else { $item.Name }
    $destPath = Join-Path $Target $destName
    if ($item.PSIsContainer) {
        $skipRelativePaths = @()
        if ($skipByConfigDir.ContainsKey($destName)) {
            $skipRelativePaths = @($skipByConfigDir[$destName])
        }
        Copy-DirectoryWithPrompt -Source $item.FullName -Dest $destPath -SkipRelativePaths $skipRelativePaths
    } else {
        Copy-FileWithPrompt -Source $item.FullName -Dest $destPath
    }
}

Write-Host "`nDone!" -ForegroundColor Cyan

# Restore this project's Ghidra setup on a new machine.
#
#   powershell -ExecutionPolicy Bypass -File ghidra\restore-ghidra.ps1
#   powershell -ExecutionPolicy Bypass -File ghidra\restore-ghidra.ps1 -Force
#   powershell -ExecutionPolicy Bypass -File ghidra\restore-ghidra.ps1 -SkipSleigh
#
# What it does:
#   1. Resolves this machine's Ghidra install / JDK (machine-paths.ps1).
#   2. Installs the modified SuperH4 SLEIGH (Continental variant-opcode NOP
#      stubs) into the Ghidra install, backing up the stock file first, and
#      deletes the stale compiled SuperH4_be.sla so Ghidra recompiles it.
#   3. Unpacks the archived Ghidra workspaces into the local workspace dir.
#
# Idempotent: existing workspaces and an already-patched SLEIGH are left alone
# unless -Force is given.

[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$SkipSleigh,
    [switch]$SkipWorkspaces
)

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\machine-paths.ps1"

Write-Host "Machine      : $env:COMPUTERNAME"
Write-Host "Ghidra home  : $GhidraHome"
Write-Host "JAVA_HOME    : $GhidraJavaHome"
Write-Host "Workspace dir: $GhidraWorkspaceDir"
Write-Host ""

# ---------------------------------------------------------------- SLEIGH ----
if (-not $SkipSleigh) {
    $langDir = Join-Path $GhidraHome 'Ghidra\Processors\SuperH4\data\languages'
    if (-not (Test-Path $langDir)) {
        throw "SuperH4 language dir not found: $langDir"
    }

    $target  = Join-Path $langDir 'SuperH4.sinc'
    $backup  = Join-Path $langDir 'SuperH4.sinc.stock'
    $source  = Join-Path $PSScriptRoot 'sleigh\SuperH4.sinc'
    $compiled = Join-Path $langDir 'SuperH4_be.sla'

    $targetHash = $null
    if (Test-Path $target) { $targetHash = (Get-FileHash $target -Algorithm MD5).Hash }
    $sourceHash = (Get-FileHash $source -Algorithm MD5).Hash

    if ($targetHash -eq $sourceHash -and -not $Force) {
        Write-Host "SLEIGH   : already patched (MD5 $sourceHash) - skipping."
    }
    else {
        if ((Test-Path $target) -and -not (Test-Path $backup)) {
            Copy-Item $target $backup
            Write-Host "SLEIGH   : stock SuperH4.sinc backed up to SuperH4.sinc.stock"
        }
        Copy-Item $source $target -Force
        # Bump mtime so Ghidra sees the .sinc as newer than any compiled .sla.
        (Get-Item $target).LastWriteTime = Get-Date
        Write-Host "SLEIGH   : installed modified SuperH4.sinc (MD5 $sourceHash)"

        if (Test-Path $compiled) {
            Remove-Item $compiled -Force
            Write-Host "SLEIGH   : removed stale SuperH4_be.sla (Ghidra will recompile on next load)"
        }
    }
}

# ------------------------------------------------------------ WORKSPACES ----
if (-not $SkipWorkspaces) {
    if (-not (Test-Path $GhidraWorkspaceDir)) {
        New-Item -ItemType Directory -Path $GhidraWorkspaceDir -Force | Out-Null
        Write-Host "WORKSPACE: created $GhidraWorkspaceDir"
    }

    # zip name -> a path that exists after a successful extract (used as the
    # "already restored" marker)
    $workspaces = @{
        'dlcm_analysis' = 'dlcm_analysis.rep'
        'coda_gateway'  = 'coda_gateway\coda_gateway.rep'
    }

    foreach ($name in $workspaces.Keys) {
        $zip    = Join-Path $PSScriptRoot "workspaces\$name.zip"
        $marker = Join-Path $GhidraWorkspaceDir $workspaces[$name]

        if (-not (Test-Path $zip)) {
            Write-Warning "WORKSPACE: $name.zip not found - skipping."
            continue
        }
        if ((Test-Path $marker) -and -not $Force) {
            Write-Host "WORKSPACE: $name already present - skipping (use -Force to overwrite)."
            continue
        }
        if ((Test-Path $marker) -and $Force) {
            Write-Warning "WORKSPACE: -Force given; overwriting $marker"
            Remove-Item $marker -Recurse -Force
        }
        Expand-Archive -Path $zip -DestinationPath $GhidraWorkspaceDir -Force
        Write-Host "WORKSPACE: restored $name -> $GhidraWorkspaceDir"
    }

    # Headless script output folder referenced by the runners.
    $exportDir = Join-Path $GhidraWorkspaceDir 'dlcm_export'
    if (-not (Test-Path $exportDir)) {
        New-Item -ItemType Directory -Path $exportDir -Force | Out-Null
        Write-Host "WORKSPACE: created $exportDir (headless script output)"
    }
}

Write-Host ""
Write-Host "Done. Headless scripts live in ghidra\scripts\ - pass that folder to -scriptPath."
Write-Host "Example:"
Write-Host "  & '$GhidraHeadless' '$GhidraWorkspaceDir' dlcm_analysis -process coda_dlcm_prog.bin ``"
Write-Host "      -noanalysis -postScript DlcmTest.java -scriptPath '$PSScriptRoot\scripts'"

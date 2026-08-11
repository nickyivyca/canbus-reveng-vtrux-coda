# Ghidra per-machine path resolution.
#
# Dot-source this from any Ghidra runner script so the runner itself stays
# machine-agnostic:
#
#     . "$PSScriptRoot\..\..\ghidra\machine-paths.ps1"     # adjust depth to taste
#     & cmd /c "`"$GhidraHeadless`" `"$proj`" MyProject ..."
#
# Variables set by this script:
#   $RepoRoot            - absolute path of the reverse-it project root
#   $GhidraHome          - Ghidra install directory
#   $GhidraHeadless      - full path to support\analyzeHeadless.bat
#   $GhidraJavaHome      - JDK used by Ghidra (also exported as $env:JAVA_HOME)
#   $GhidraWorkspaceDir  - local (non-SeaDrive) directory holding .gpr/.rep projects
#
# Adding a new machine: add a row to $GhidraMachines below, keyed by hostname
# ($env:COMPUTERNAME), and add the same machine to the table in
# ghidra\README.md and in tools-reference.md.

$RepoRoot = Split-Path $PSScriptRoot -Parent

$GhidraMachines = @{
    'the bench PC' = @{
        GhidraHome   = '<home>\Programs\ghidra_12.0.4_PUBLIC'
        JavaHome     = 'C:\Program Files\Eclipse Adoptium\jdk-25.0.2.10-hotspot'
        WorkspaceDir = "$env:LOCALAPPDATA\ghidra-projects"
    }
}

$hostName = $env:COMPUTERNAME
$entry = $GhidraMachines[$hostName]

if ($null -ne $entry) {
    $GhidraHome         = $entry.GhidraHome
    $GhidraJavaHome     = $entry.JavaHome
    $GhidraWorkspaceDir = $entry.WorkspaceDir
}
else {
    # Unknown machine: fall back to environment variables so a new box can work
    # before it has been added to the table above.
    $GhidraHome         = $env:GHIDRA_HOME
    $GhidraJavaHome     = $env:JAVA_HOME
    $GhidraWorkspaceDir = "$env:LOCALAPPDATA\ghidra-projects"

    if ([string]::IsNullOrWhiteSpace($GhidraHome)) {
        throw ("Machine '$hostName' is not in the `$GhidraMachines table in " +
               "$PSScriptRoot\machine-paths.ps1, and GHIDRA_HOME is not set. " +
               "Add a row for this machine (see ghidra\README.md) or set GHIDRA_HOME.")
    }
    Write-Warning "Machine '$hostName' not in the table - using GHIDRA_HOME/JAVA_HOME. Add a row to machine-paths.ps1."
}

$GhidraHeadless = Join-Path $GhidraHome 'support\analyzeHeadless.bat'

if (-not (Test-Path $GhidraHeadless)) {
    throw "analyzeHeadless.bat not found at '$GhidraHeadless'. Check GhidraHome for '$hostName'."
}
if (-not [string]::IsNullOrWhiteSpace($GhidraJavaHome)) {
    $env:JAVA_HOME = $GhidraJavaHome
}

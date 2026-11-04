# JAVA_HOME comes from the environment: a JDK 17-21, e.g. Android Studio's JBR (path in local-paths.md).
if (-not $env:JAVA_HOME) { Write-Error 'Set JAVA_HOME to a JDK 17-21 first (see local-paths.md)'; exit 1 }
Set-Location $PSScriptRoot
.\gradlew.bat :vtrux:assembleDebug 2>&1 | Select-Object -Last 10

$env:JAVA_HOME = '<ANDROID_STUDIO_JBR>'
Set-Location $PSScriptRoot
.\gradlew.bat :vtrux:assembleDebug 2>&1 | Select-Object -Last 10

$env:JAVA_HOME = '<ANDROID_STUDIO_JBR>'
Set-Location '<repo>\android-app\CanLoggerApps'
.\gradlew.bat :vtrux:assembleDebug 2>&1 | Select-Object -Last 10

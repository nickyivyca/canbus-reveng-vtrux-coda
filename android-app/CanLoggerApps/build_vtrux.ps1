$env:JAVA_HOME = 'C:\Program Files\Android\Android Studio1\jbr'
Set-Location 'E:\Seafile\Projects\reverse-it\android-app\CanLoggerApps'
.\gradlew.bat :vtrux:assembleDebug 2>&1 | Select-Object -Last 10

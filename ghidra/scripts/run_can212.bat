@echo off
set GHIDRA=<home>\Programs\ghidra_12.0.4_PUBLIC\support\analyzeHeadless.bat
set PROJ=%LOCALAPPDATA%\ghidra-projects
set SCRIPTS=%LOCALAPPDATA%\ghidra-projects
set LOG=%LOCALAPPDATA%\ghidra-projects\dlcm_export\can212_run.log
set JAVA_HOME=C:\Program Files\Eclipse Adoptium\jdk-25.0.2.10-hotspot
call "%GHIDRA%" "%PROJ%" dlcm_analysis -process coda_dlcm_prog.bin -noanalysis -postScript DlcmCan212.java -scriptPath "%SCRIPTS%" > "%LOG%" 2>&1
echo Exit code: %ERRORLEVEL%

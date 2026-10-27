@echo off
setlocal
cd /d "%~dp0\.."

if not exist "dist\ADBFlowStudio.exe" (
    echo ERROR: dist\ADBFlowStudio.exe not found. Run desktop\build_windows.bat first.
    exit /b 1
)
if not exist "dist\adb-flow-studio-recorder.exe" (
    echo ERROR: Recorder helper is missing. Run desktop\build_windows.bat first.
    exit /b 1
)
if not exist "dist\adb-flow-studio-replayer.exe" (
    echo ERROR: Replayer helper is missing. Run desktop\build_windows.bat first.
    exit /b 1
)

set "ISCC="
where iscc >nul 2>&1
if not errorlevel 1 set "ISCC=iscc.exe"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC (
    echo ERROR: Inno Setup 6 was not found. Install it and run this script again.
    exit /b 1
)

echo Building ADB Flow Studio installer...
"%ISCC%" /O"dist" installer\ADBFlowStudio.iss
if errorlevel 1 (
    echo ERROR: Inno Setup compilation failed.
    exit /b 1
)

if not exist "dist\ADBFlowStudioSetup.exe" (
    echo ERROR: Installer output was not created.
    exit /b 1
)

echo Installer ready: dist\ADBFlowStudioSetup.exe
exit /b 0

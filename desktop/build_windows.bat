@echo off
setlocal
cd /d "%~dp0\.."

echo [1/5] Creating build environment...
if not exist ".venv-desktop\Scripts\python.exe" (
    py -3 -m venv .venv-desktop
    if errorlevel 1 goto :error
)

call ".venv-desktop\Scripts\activate.bat"
if errorlevel 1 goto :error

echo [2/5] Installing desktop dependencies...
python -m pip install --upgrade pip
if errorlevel 1 goto :error
python -m pip install -r requirements-desktop.txt pyinstaller
if errorlevel 1 goto :error

echo [3/5] Running unit tests...
python -m unittest discover -s desktop\tests -v
if errorlevel 1 goto :error

echo [4/5] Building the desktop GUI...
python -m PyInstaller --noconfirm --clean --onefile --windowed --name ADBFlowStudio --paths . desktop\main.py
if errorlevel 1 goto :error

echo [5/5] Building recorder and replayer helpers...
python -m PyInstaller --noconfirm --clean --onefile --console --name adb-flow-studio-recorder --paths . desktop\recorder_worker.py
if errorlevel 1 goto :error
python -m PyInstaller --noconfirm --clean --onefile --console --name adb-flow-studio-replayer --paths . desktop\replayer_worker.py
if errorlevel 1 goto :error

echo.
echo Build complete. Keep all executables in the dist folder together.
echo GUI: dist\ADBFlowStudio.exe
echo Helpers: dist\adb-flow-studio-recorder.exe and dist\adb-flow-studio-replayer.exe
exit /b 0

:error
echo.
echo BUILD FAILED. Read the error above before retrying.
exit /b 1

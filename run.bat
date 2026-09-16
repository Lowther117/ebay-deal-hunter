@echo off
setlocal EnableExtensions
REM Run eBay Deal Hunter from source on Windows, setting up a virtual
REM environment the first time. Use build-exe.bat if you want a standalone
REM .exe instead.
cd /d "%~dp0"
set "VENV=%~dp0.venv"
if not exist "%VENV%\Scripts\python.exe" (
  echo First run - setting Python up. This happens once.
  for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\ensure_python.ps1"`) do set "PY=%%P"
  if not defined PY ( echo Could not find or install Python. & pause & exit /b 1 )
  "%PY%" -m venv "%VENV%" || ( echo Could not create the environment. & pause & exit /b 1 )
  "%VENV%\Scripts\python.exe" -m pip install --upgrade pip >nul
  REM proxy_tools (needed by pywebview) is source-only on PyPI, so it goes in
  REM before --only-binary is applied to everything else - same as the build.
  "%VENV%\Scripts\python.exe" -m pip install proxy_tools >nul
  "%VENV%\Scripts\python.exe" -m pip install --only-binary :all: -r "%~dp0requirements.txt" || ( pause & exit /b 1 )
  REM The native window needs pythonnet; without it the app opens in the browser.
  "%VENV%\Scripts\python.exe" -m pip install --only-binary :all: pythonnet clr-loader >nul 2>&1 || echo pythonnet did not install - the app will open in your browser instead.
)
start "" "%VENV%\Scripts\pythonw.exe" "%~dp0app.py"
exit /b 0

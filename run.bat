@echo off
setlocal EnableExtensions
REM Run eBay Deal Hunter from source on Windows, setting up a virtual
REM environment the first time. Use build-exe.bat if you want a standalone
REM .exe instead.
cd /d "%~dp0"
set "VENV=%~dp0.venv"
if exist "%VENV%\Scripts\python.exe" goto :run

echo First run - setting Python up. This happens once.
REM  %PY% is set and used in separate statements on purpose: inside one
REM  parenthesised block cmd expands variables before the block runs, so the
REM  venv step used to run with an empty interpreter path and fail.
for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\ensure_python.ps1"`) do set "PY=%%P"
if not defined PY goto :nopython
if not exist "%PY%" goto :nopython
"%PY%" -m venv "%VENV%"
if errorlevel 1 ( echo Could not create the environment. & pause & exit /b 1 )
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip >nul
REM proxy_tools (needed by pywebview) is source-only on PyPI, so it goes in
REM before --only-binary is applied to everything else - same as the build.
"%VENV%\Scripts\python.exe" -m pip install proxy_tools >nul
"%VENV%\Scripts\python.exe" -m pip install --only-binary :all: -r "%~dp0requirements.txt"
if errorlevel 1 ( pause & exit /b 1 )
REM The native window needs pythonnet; without it the app opens in the browser.
"%VENV%\Scripts\python.exe" -m pip install --only-binary :all: pythonnet clr-loader >nul 2>&1 || echo pythonnet did not install - the app will open in your browser instead.

:run
start "" "%VENV%\Scripts\pythonw.exe" "%~dp0app.py"
exit /b 0

:nopython
echo Could not find or install Python.
pause
exit /b 1

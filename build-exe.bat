@echo off
rem Build "Deal Hunter.exe" - a standalone single-file app that runs without
rem Python.
rem
rem Double-click this file, or run build-exe.bat from a Command Prompt.
rem
rem dealhunter.spec decides the shape of the build; this script only arranges
rem a Python and the dependencies around it. The noisy output of pip and
rem PyInstaller goes to build-win-log.txt so this window stays readable; if
rem anything fails, the tail of that log is shown here. The finished exe is
rem tested before this script claims success.

setlocal
cd /d "%~dp0"
set "HERE=%~dp0"
set "VENV=%HERE%.venv-build"
set "PY=%VENV%\Scripts\python.exe"
set "LOG=%HERE%build-win-log.txt"
set "EXE=%HERE%dist\Deal Hunter.exe"
set "REPORT=%HERE%dist\dealhunter-selftest.txt"

echo eBay Deal Hunter exe build> "%LOG%"
echo %DATE% %TIME%>> "%LOG%"
echo.
echo Building the standalone "Deal Hunter.exe". This takes a few minutes.
echo Detail goes to build-win-log.txt.

rem ---------------------------------------------------------------------
rem 1. A Python to build with - installed automatically if the PC has none.
rem ---------------------------------------------------------------------
echo.
echo == Python
if exist "%PY%" goto :haveenv

set "SYSPY="
for /f "usebackq delims=" %%p in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE%tools\ensure_python.ps1" 2^>nul`) do set "SYSPY=%%p"
if not defined SYSPY goto :nopython
if not exist "%SYSPY%" goto :nopython
echo    Using %SYSPY%
"%SYSPY%" -m venv "%VENV%" >> "%LOG%" 2>&1
if not exist "%PY%" (
    echo    ERROR: could not create the build environment.
    goto :failed
)

:haveenv
echo    Installing PyInstaller...
"%PY%" -m pip install --upgrade pip --quiet >> "%LOG%" 2>&1
"%PY%" -m pip install --upgrade --only-binary :all: pyinstaller >> "%LOG%" 2>&1
if errorlevel 1 (
    echo    ERROR: could not install PyInstaller.
    goto :failed
)

rem ---------------------------------------------------------------------
rem 2. Everything the app should carry with it.
rem
rem --only-binary :all: everywhere: a missing wheel then fails in seconds
rem instead of trying to compile from source and hunting for Visual Studio.
rem ---------------------------------------------------------------------
echo.
echo == Components to bake in
rem proxy_tools (a pure-Python dependency of pywebview) is source-only on
rem PyPI, so under --only-binary pip rejects every pywebview - install it
rem first on its own. No compiler involved.
echo    Window wrapper and icon tools...
"%PY%" -m pip install proxy_tools >> "%LOG%" 2>&1
"%PY%" -m pip install --only-binary :all: -r "%HERE%requirements.txt" >> "%LOG%" 2>&1
if errorlevel 1 (
    echo    ERROR: could not install the app's requirements.
    goto :failed
)

rem pywebview draws its window with WebView2, reached through pythonnet's clr.
rem Without it the app still runs - it just opens in the browser instead.
echo    Windows window backend ^(pythonnet^)...
"%PY%" -m pip install --only-binary :all: pythonnet clr-loader >> "%LOG%" 2>&1
if errorlevel 1 echo    WARNING: pythonnet did not install - the app will fall back to the browser.

"%PY%" -c "import webview, clr" >nul 2>&1
if errorlevel 1 (
    echo    WARNING: the native window backend is not importable - the app will
    echo             fall back to opening in your browser.
) else (
    echo    native window backend ^(pywebview + WebView2^) ok
)

rem ---------------------------------------------------------------------
rem 3. Icon
rem
rem dealhunter.spec uses assets\icon.ico when it is there and shrugs when it
rem is not, so a failure here is never worth stopping a build for.
rem ---------------------------------------------------------------------
echo.
echo == Icon
"%PY%" "%HERE%tools\make_icons.py" >> "%LOG%" 2>&1
if exist "%HERE%assets\icon.ico" (
    echo    assets\icon.ico written
) else (
    echo    WARNING: the icon could not be generated - building with the default one.
)

rem ---------------------------------------------------------------------
rem 4. Build
rem ---------------------------------------------------------------------
echo.
echo == Building ^(a few minutes^)
if exist "%HERE%build" rd /s /q "%HERE%build"
if exist "%HERE%dist" rd /s /q "%HERE%dist"

"%PY%" -m PyInstaller --noconfirm --clean "%HERE%dealhunter.spec" >> "%LOG%" 2>&1
if errorlevel 1 (
    echo    Build failed.
    goto :failed
)
if not exist "%EXE%" (
    echo    The build finished but dist\Deal Hunter.exe is not there.
    goto :failed
)

rem ---------------------------------------------------------------------
rem 5. Prove it runs before saying it works.
rem
rem A windowed exe has no console of its own, so the self-test writes its
rem report to a file beside the exe and that file is shown here. It is also
rem why this uses start /wait - a windowed exe otherwise hands the prompt
rem straight back and there would be nothing to read yet.
rem ---------------------------------------------------------------------
echo.
echo == Testing the built exe
if exist "%REPORT%" del /q "%REPORT%"
start "Deal Hunter self-test" /wait "%EXE%" selftest
set "RC=%ERRORLEVEL%"
if exist "%REPORT%" (
    type "%REPORT%"
    type "%REPORT%" >> "%LOG%"
) else (
    echo    The exe did not produce a self-test report.
    set "RC=1"
)

echo.
if "%RC%"=="0" (
    echo Done: %EXE%
    echo.
    echo Copy it anywhere - Desktop, or C:\Users\%USERNAME%\Apps\. It keeps its
    echo settings and its database in %%APPDATA%%\eBay Deal Hunter, not next to
    echo the exe, so it can be moved or replaced without losing anything.
    echo.
    echo First launch only: the exe is not code-signed, so SmartScreen shows
    echo "Windows protected your PC". Click More info, then Run anyway. Your
    echo antivirus may also scan it once - normal for a fresh PyInstaller exe.
) else (
    echo The exe was built but the self-test above found problems, so it may
    echo not open properly. The report is in %REPORT% and the whole run is in
    echo %LOG%.
)
echo.
echo Log: %LOG%
pause
exit /b 0

:nopython
echo    ERROR: Python 3.9+ is needed to BUILD the exe ^(not to run it^), and
echo    it could not be installed automatically.
echo    Install it from https://www.python.org/downloads/windows/
echo    ^(tick "Add python.exe to PATH"^), then run this again. If Python was
echo    just installed, close this window and open a new one first.
goto :failed

:failed
echo.
echo ---- last 40 lines of the log ----
powershell -NoProfile -Command "Get-Content -LiteralPath '%LOG%' -Tail 40" 2>nul
echo ----------------------------------
echo Full log: %LOG%
echo.
pause
exit /b 1

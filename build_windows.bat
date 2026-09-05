@echo off
setlocal

rem ==========================================================================
rem  Build "Deal Hunter.exe" for Windows.
rem
rem    Double-click this file, or run it from a Command Prompt:
rem        build_windows.bat
rem
rem    Produces:  dist\Deal Hunter.exe   (a single self-contained .exe)
rem ==========================================================================

set "APP_NAME=Deal Hunter"
set "HERE=%~dp0"
cd /d "%HERE%"

set "VENV=%HERE%.venv"
set "PY=%VENV%\Scripts\python.exe"

rem --------------------------------------------------------------------------
echo.
echo ==^> Checking prerequisites
echo.

rem Find a REAL Python - the py launcher counts, the Microsoft Store's fake
rem python.exe stub does not - and install Python automatically if there is
rem none (winget first, python.org directly when winget is broken).
powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE%tools\ensure_python.ps1" >nul
if errorlevel 1 goto :no_python

set "SYSPY="
for /f "usebackq delims=" %%I in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE%tools\ensure_python.ps1" -NoInstall`) do set "SYSPY=%%I"
if not defined SYSPY goto :no_python
echo     Using Python: %SYSPY%

rem --------------------------------------------------------------------------
echo.
echo ==^> Setting up the virtual environment
echo.

if exist "%PY%" (
    echo     Reusing existing .venv
) else (
    echo     Creating .venv
    "%SYSPY%" -m venv "%VENV%"
    if errorlevel 1 (
        echo.
        echo !! Failed to create the virtual environment.
        echo    Delete the .venv folder if it exists and run this again.
        goto :fail
    )
)

if not exist "%PY%" (
    echo.
    echo !! .venv looks broken - delete the .venv folder and run this again.
    goto :fail
)

rem --------------------------------------------------------------------------
echo.
echo ==^> Installing dependencies
echo.

"%PY%" -m pip install --upgrade pip
if errorlevel 1 goto :fail

echo     Installing requirements.txt
"%PY%" -m pip install -r "%HERE%requirements.txt"
if errorlevel 1 goto :fail

echo     Installing pyinstaller
"%PY%" -m pip install pyinstaller
if errorlevel 1 goto :fail

rem --------------------------------------------------------------------------
echo.
echo ==^> Generating icons
echo.

"%PY%" "%HERE%tools\make_icons.py"
if errorlevel 1 goto :fail

if not exist "%HERE%assets\icon.ico" (
    echo.
    echo !! assets\icon.ico was not created.
    goto :fail
)

rem --------------------------------------------------------------------------
echo.
echo ==^> Running PyInstaller
echo.

if exist "%HERE%build" rmdir /s /q "%HERE%build"
if exist "%HERE%dist"  rmdir /s /q "%HERE%dist"

"%PY%" -m PyInstaller --noconfirm --clean "%HERE%dealhunter.spec"
if errorlevel 1 goto :fail

if not exist "%HERE%dist\%APP_NAME%.exe" (
    echo.
    echo !! Build finished but dist\%APP_NAME%.exe is missing.
    goto :fail
)

rem --------------------------------------------------------------------------
echo.
echo ==^> Build complete
echo.
echo   Your app is here:
echo.
echo       %HERE%dist\%APP_NAME%.exe
echo.
echo   It is a single self-contained file - you can move it anywhere,
echo   for example to your Desktop or C:\Users\%USERNAME%\Apps\.
echo.
echo   NEXT STEPS
echo   ----------
echo   1. Right-click "%APP_NAME%.exe" and choose "Pin to Start" so it
echo      sits in your Start Menu like a normal app. ("Pin to taskbar"
echo      works too.^)
echo.
echo   2. FIRST LAUNCH - SmartScreen will stop it.
echo      The .exe is not code-signed (that needs a paid certificate^),
echo      so Windows shows a blue box saying:
echo.
echo          "Windows protected your PC"
echo.
echo      Click "More info", then click the "Run anyway" button that
echo      appears. You only need to do this once.
echo.
echo   3. Your antivirus may also scan it on first run - that is normal
echo      for a freshly built, unsigned PyInstaller exe.
echo.
pause
exit /b 0

rem --------------------------------------------------------------------------
:no_python
echo.
echo !! Python could not be found, and the automatic install did not
echo    complete either (the messages above say why).
echo.
echo    If Python was just installed for the first time, simply close
echo    this window and run build_windows.bat again - a fresh window
echo    picks up the new install.
echo.
echo    Otherwise install it yourself from:
echo        https://www.python.org/downloads/windows/
echo    and tick  [x] Add python.exe to PATH  on the first screen.
echo.
pause
exit /b 1

:fail
echo.
echo !! Build failed. Scroll up for the first error message.
echo.
pause
exit /b 1

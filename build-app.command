#!/bin/bash
# Build "Deal Hunter.app" - a standalone Mac app that runs without Python.
#
# Double-click this file in Finder, or run ./build-app.command in Terminal.
#
# dealhunter.spec decides the shape of the build; this script only arranges a
# Python, the dependencies and the signing around it. Everything printed here
# is also written to build-mac-log.txt, and the built app is tested before
# this script claims success.

cd "$(dirname "$0")" || exit 1
LOG="build-mac-log.txt"
: > "$LOG"
exec > >(tee -a "$LOG") 2>&1

VENV=".venv-build-mac"
PY="$VENV/bin/python"
APP="dist/Deal Hunter.app"
BIN="$APP/Contents/MacOS/Deal Hunter"
REPORT="dist/dealhunter-selftest.txt"

say()  { printf '\n== %s\n' "$1"; }
fail() { printf '\nBuild stopped: %s\nFull log: %s/%s\n' "$1" "$PWD" "$LOG"; exit 1; }

printf 'eBay Deal Hunter app build - %s\n' "$(date)"
printf 'macOS %s on %s\n' "$(sw_vers -productVersion 2>/dev/null)" "$(uname -m)"

# --------------------------------------------------------------------------
# Homebrew - where a bundle-able Python and any external tools come from.
#
# A double-clicked .command starts with a bare PATH, so Homebrew's folders are
# added by hand, and Homebrew itself is installed if the Mac has none (its
# installer asks for the Mac password once, in this window).
# --------------------------------------------------------------------------
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

ensure_brew() {
    command -v brew >/dev/null 2>&1 && return 0
    say "Installing Homebrew"
    echo "   This asks for your Mac password once, then takes a few minutes."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" < /dev/tty
    export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
    command -v brew >/dev/null 2>&1
}

# brew_install <formula>... - installs each one (a formula that is already
# there is a no-op). Non-zero if Homebrew is unavailable or an install failed.
brew_install() {
    ensure_brew || { echo "   Homebrew is not available, so $* cannot be installed automatically."; return 1; }
    local f rc=0
    for f in "$@"; do
        echo "   brew install $f"
        HOMEBREW_NO_AUTO_UPDATE=1 brew install "$f" < /dev/null || rc=1
    done
    return $rc
}

[ "$(uname -s)" = "Darwin" ] || fail "this builds the Mac app and must be run on a Mac (on Windows use build-exe.bat)"

# --------------------------------------------------------------------------
# 1. Pick an interpreter that can actually be bundled.
#
# Apple's own /usr/bin/python3 is a Command Line Tools shim without a real
# shared library to bundle: PyInstaller either refuses it or produces an app
# that dies on launch with no window and no message. So a Homebrew or
# python.org Python is required, and Apple's is refused by name.
# --------------------------------------------------------------------------
say "Choosing a Python to build with"

usable() {   # prints the version, or nothing if this one is no good
    "$1" -c 'import sys;
v = sys.version_info
print("%d.%d" % v[:2]) if v >= (3, 9) else None' 2>/dev/null
}

CANDIDATES=()
[ -n "$DEALHUNTER_BUILD_PYTHON" ] && CANDIDATES+=("$DEALHUNTER_BUILD_PYTHON")
for v in 3.14 3.13 3.12 3.11 3.10 3.9; do
    CANDIDATES+=("/opt/homebrew/bin/python$v" "/usr/local/bin/python$v" \
                 "/Library/Frameworks/Python.framework/Versions/$v/bin/python3")
done
CANDIDATES+=("$(command -v python3 2>/dev/null)")

pick_python() {
CHOSEN=""
for c in "${CANDIDATES[@]}"; do
    [ -n "$c" ] && [ -x "$c" ] || continue
    # readlink, not python: on a fresh Mac the only "python3" is Apple's stub,
    # and merely running it pops up the Xcode command-line-tools installer.
    real="$(readlink -f "$c" 2>/dev/null || echo "$c")"
    case "$real" in
        /usr/bin/python3|/Library/Developer/CommandLineTools/*|/Applications/Xcode.app/*)
            printf '   skipping %s - Apple system Python, it cannot be bundled\n' "$c"
            continue ;;
    esac
    ver="$(usable "$c")"
    if [ -z "$ver" ]; then
        printf '   skipping %s - not a working Python 3.9+\n' "$c"
        continue
    fi
    CHOSEN="$c"; printf '   using %s (Python %s)\n' "$c" "$ver"; break
done
}
pick_python

if [ -z "$CHOSEN" ]; then
    echo "   None of the Pythons here can be bundled - adding one with Homebrew."
    echo "   (a Python that can be bundled; Apple's own /usr/bin/python3 does not qualify.)"
    if brew_install python; then
        pick_python
    fi
fi

if [ -z "$CHOSEN" ]; then
    cat <<'MSG'

None of the Pythons on this Mac can be used to build the app.

The one Apple ships (/usr/bin/python3) cannot be packaged into an app - that
is why a build can appear to finish and the app still not open. Install a
real one, then run this again:

    brew install python                     (Homebrew - simplest)
    https://www.python.org/downloads/macos/ (official installer)

If you already have one somewhere unusual, point this script at it:

    DEALHUNTER_BUILD_PYTHON=/path/to/python3 ./build-app.command

None of this is needed to RUN the app from source - python3 app.py keeps
working exactly as before whether or not you ever build the .app.
MSG
    fail "no suitable Python found"
fi

# --------------------------------------------------------------------------
# 2. Build environment
# --------------------------------------------------------------------------
say "Build environment"
if [ ! -x "$PY" ]; then
    "$CHOSEN" -m venv "$VENV" || fail "could not create the build environment"
else
    # a venv built by a different (or since moved) Python is worse than none
    if ! "$PY" -c 'import sys' >/dev/null 2>&1; then
        rm -rf "$VENV"
        "$CHOSEN" -m venv "$VENV" || fail "could not recreate the build environment"
    fi
fi
"$PY" -m pip install --upgrade pip --quiet
"$PY" -m pip install --upgrade --only-binary :all: pyinstaller \
    || fail "could not install PyInstaller"

# --only-binary :all: everywhere: a missing wheel then fails in seconds
# instead of trying to compile from source and hunting for a toolchain.
# The one exception is proxy_tools, a pure-Python dependency of pywebview
# that PyPI only carries as a source package - under --only-binary pip
# rejects every pywebview version and the build stops. It needs no
# compiler, so it goes in first on its own.
say "Components to bake in"
"$PY" -m pip install proxy_tools \
    || fail "could not install proxy_tools (needed by pywebview)"
"$PY" -m pip install --only-binary :all: -r requirements.txt \
    || fail "could not install the app's requirements"

# pywebview draws its window with WKWebView, reached through pyobjc. Without
# these the app still runs - it just opens in the browser instead.
"$PY" -m pip install --only-binary :all: \
        pyobjc-core pyobjc-framework-Cocoa pyobjc-framework-WebKit \
    || echo "   WARNING: pyobjc did not install - the app will fall back to the browser."

if "$PY" -c 'import webview, objc, WebKit' >/dev/null 2>&1; then
    echo "   native window backend (pywebview + WKWebView) ok"
else
    echo "   WARNING: the native window backend is not importable - the app will"
    echo "            fall back to opening in your browser."
fi

# --------------------------------------------------------------------------
# 3. Icon
#
# dealhunter.spec uses assets/icon.icns when it is there and shrugs when it is
# not, so a failure here is never worth stopping a build for.
# --------------------------------------------------------------------------
say "Icon"
if "$PY" tools/make_icons.py >/dev/null 2>&1 && [ -f assets/icon.icns ]; then
    echo "   assets/icon.icns written"
else
    echo "   WARNING: the icon could not be generated - building with the default one."
fi

# --------------------------------------------------------------------------
# 4. Build
# --------------------------------------------------------------------------
say "Building (a few minutes)"
rm -rf build dist
"$PY" -m PyInstaller --noconfirm --clean dealhunter.spec \
    || fail "PyInstaller failed - the messages above say why"

[ -x "$BIN" ] || fail "the build finished but $APP is not there"

# --------------------------------------------------------------------------
# 5. Make it launchable
#
# An ad-hoc signature is what lets a locally built app open at all on Apple
# silicon, and stray extended attributes invalidate it.
# --------------------------------------------------------------------------
say "Signing"
xattr -cr "$APP" 2>/dev/null || true
if command -v codesign >/dev/null 2>&1; then
    codesign --force --deep --sign - --timestamp=none "$APP" \
        && codesign --verify --deep --strict "$APP" \
        && echo "   ad-hoc signature ok" \
        || echo "   WARNING: signing did not complete - the app may be blocked on first open"
else
    echo "   codesign not available (install the Xcode command line tools)"
fi

# --------------------------------------------------------------------------
# 6. Prove it runs before saying it works
#
# A windowed app has no console, so the self-test also writes its report
# beside the app - dist/dealhunter-selftest.txt.
# --------------------------------------------------------------------------
say "Testing the built app"
rm -f "$REPORT"
if "$BIN" selftest; then
    RESULT=ok
else
    RESULT=problems
fi
[ -f "$REPORT" ] || { echo "   the app produced no self-test report"; RESULT=problems; }

echo
if [ "$RESULT" = ok ]; then
    cat <<MSG
Done: $PWD/$APP

Drag it into /Applications. It keeps its settings and its database in
~/Library/Application Support/eBay Deal Hunter, not inside the app, so it
can be moved or replaced without losing anything.

First launch only: the app is not signed with a paid Apple developer
certificate, so macOS refuses it once. Right-click the app, choose Open,
then Open again - or System Settings > Privacy & Security > Open Anyway.
After that it opens like any other app.
MSG
else
    cat <<MSG
The app was built but the self-test above found problems, so it may not open
properly. The report is in $PWD/$REPORT and the whole run is in $PWD/$LOG.
MSG
fi
echo "Log: $PWD/$LOG"

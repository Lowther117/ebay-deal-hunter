#!/usr/bin/env bash
#
# Build "Deal Hunter.app" for macOS.
#
#   chmod +x build_mac.sh
#   ./build_mac.sh
#
# Produces:  dist/Deal Hunter.app
#
set -euo pipefail

APP_NAME="Deal Hunter"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

VENV="$HERE/.venv"
PY="$VENV/bin/python"

step()  { printf '\n\033[1;34m==>\033[0m \033[1m%s\033[0m\n' "$1"; }
info()  { printf '    %s\n' "$1"; }
fail()  { printf '\n\033[1;31m!! %s\033[0m\n' "$1" >&2; exit 1; }

# --------------------------------------------------------------------------
step "Checking prerequisites"

if ! command -v python3 >/dev/null 2>&1; then
    fail "python3 was not found on your PATH.
    Install it from https://www.python.org/downloads/macos/
    (or run:  xcode-select --install)  and then re-run this script."
fi
info "python3: $(command -v python3) ($(python3 --version 2>&1))"

if [[ "$(uname -s)" != "Darwin" ]]; then
    fail "This script builds the macOS app and must be run on a Mac.
    On Windows use build_windows.bat instead."
fi

# --------------------------------------------------------------------------
step "Setting up the virtual environment"

if [[ ! -d "$VENV" ]]; then
    info "Creating $VENV"
    python3 -m venv "$VENV"
else
    info "Reusing existing $VENV"
fi

[[ -x "$PY" ]] || fail "Virtual environment looks broken - delete .venv and re-run."

# --------------------------------------------------------------------------
step "Installing dependencies"

"$PY" -m pip install --upgrade pip >/dev/null
info "Installing requirements.txt"
"$PY" -m pip install -r "$HERE/requirements.txt"
info "Installing pyinstaller"
"$PY" -m pip install pyinstaller

# --------------------------------------------------------------------------
step "Generating icons"

"$PY" "$HERE/tools/make_icons.py"

[[ -d "$HERE/assets/icon.iconset" ]] || fail "assets/icon.iconset was not created."

# --------------------------------------------------------------------------
step "Converting iconset to icon.icns"

if ! command -v iconutil >/dev/null 2>&1; then
    fail "iconutil not found. It ships with the Xcode command line tools:
    xcode-select --install"
fi

iconutil -c icns "$HERE/assets/icon.iconset" -o "$HERE/assets/icon.icns"
info "assets/icon.icns ($(wc -c < "$HERE/assets/icon.icns" | tr -d ' ') bytes)"

# --------------------------------------------------------------------------
step "Running PyInstaller"

rm -rf "$HERE/build" "$HERE/dist"
"$PY" -m PyInstaller --noconfirm --clean "$HERE/dealhunter.spec"

[[ -d "$HERE/dist/$APP_NAME.app" ]] || fail "Build finished but dist/$APP_NAME.app is missing."

# Remove the quarantine flag we may have inherited from downloaded wheels.
xattr -cr "$HERE/dist/$APP_NAME.app" 2>/dev/null || true

# --------------------------------------------------------------------------
step "Build complete"

cat <<EOF

  Your app is here:

      $HERE/dist/$APP_NAME.app

  NEXT STEPS
  ----------
  1. Drag "$APP_NAME.app" into your /Applications folder.

  2. FIRST LAUNCH - macOS Gatekeeper will block it.
     This app is not code-signed or notarised (that needs a paid Apple
     Developer account), so double-clicking it the first time shows:

         "$APP_NAME" cannot be opened because it is from an
         unidentified developer.

     To get past it, either:

       a) RIGHT-CLICK (or Control-click) the app in /Applications,
          choose "Open", then click "Open" in the dialog.
          You only have to do this once.

       or

       b) Open System Settings > Privacy & Security, scroll to the
          Security section, and click "Open Anyway" next to the message
          about "$APP_NAME", then launch it again.

  3. After that first approval it opens normally like any other app,
     and you can keep it in the Dock.

EOF

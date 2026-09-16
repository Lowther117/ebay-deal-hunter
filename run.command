#!/bin/bash
# Run eBay Deal Hunter from source on macOS, setting up a virtual environment
# the first time. Use build-app.command if you want a standalone .app instead.
cd "$(dirname "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
VENV=".venv"
pick() {
  for c in /opt/homebrew/bin/python3.14 /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 \
           /opt/homebrew/bin/python3.11 /opt/homebrew/bin/python3.10 /opt/homebrew/bin/python3.9 \
           /usr/local/bin/python3.14 /usr/local/bin/python3.13 /usr/local/bin/python3.12 \
           /usr/local/bin/python3.11 /usr/local/bin/python3.10 /usr/local/bin/python3.9 \
           /Library/Frameworks/Python.framework/Versions/3.1*/bin/python3 \
           /Library/Frameworks/Python.framework/Versions/3.9/bin/python3 \
           "$(command -v python3 2>/dev/null)"; do
    [ -n "$c" ] && [ -x "$c" ] || continue
    if "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
      echo "$c"; return 0
    fi
  done
  return 1
}
if [ ! -x "$VENV/bin/python" ]; then
  echo "First run - setting Python up. This happens once."
  PY="$(pick)" || { echo "No Python 3.9+ found. Run build-app.command once; it installs one."; read -r; exit 1; }
  "$PY" -m venv "$VENV" || { echo "Could not create the environment."; read -r; exit 1; }
  "$VENV/bin/python" -m pip install --upgrade pip >/dev/null
  # proxy_tools (needed by pywebview) is source-only on PyPI, so it goes in
  # before --only-binary is applied to everything else - same as the build.
  "$VENV/bin/python" -m pip install proxy_tools >/dev/null
  "$VENV/bin/python" -m pip install --only-binary :all: -r requirements.txt || { read -r; exit 1; }
  # The native window needs pyobjc; without it the app opens in the browser.
  "$VENV/bin/python" -m pip install --only-binary :all: \
      pyobjc-core pyobjc-framework-Cocoa pyobjc-framework-WebKit \
      || echo "pyobjc did not install - the app will open in your browser instead."
fi
exec "$VENV/bin/python" app.py

#!/usr/bin/env python3
"""
eBay Deal Hunter - desktop app entry point.

Starts the local engine and opens it in a native window. If pywebview isn't
installed (or has no backend on this machine) it falls back to the default
browser, so the app always starts rather than dying with an import error.

    python3 app.py              open the app
    python3 app.py --browser    skip the native window, use the browser
    python3 app.py --scan       run one scan in the terminal and exit
    python3 app.py --list       list every watch and exit
    python3 app.py selftest     report what this build can and cannot do

A packaged build (see build-app.command / build-exe.bat) is windowed: it has
nowhere to print, so if it fails while starting up the window never appears
and macOS or Windows simply closes it with no message. Everything that can go
wrong on the way in is therefore caught here, written to dealhunter-crash.log
beside the app, and shown in a dialog where the system offers one.

Nothing from dealhunter/ is imported at the top of this file for the same
reason - an import error would happen before the safety net is in place.
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback


# --------------------------------------------------------------------------- #
# where this program is, and where it may leave a report
# --------------------------------------------------------------------------- #

def _app_folder() -> str:
    """The folder the program itself sits in.

    Run as a script that is the repo folder. In a packaged build it is the
    folder holding the executable - except on macOS, where the executable
    lives three levels down inside "Deal Hunter.app". Anything written inside
    a bundle invalidates its code signature and the next launch is killed by
    Gatekeeper, so the folder *containing* the .app is used instead.
    """
    if not getattr(sys, "frozen", False):
        return os.path.dirname(os.path.realpath(__file__))
    exe_dir = os.path.dirname(os.path.realpath(sys.executable))
    parts = exe_dir.split(os.sep)
    if (sys.platform == "darwin" and len(parts) >= 3
            and parts[-1] == "MacOS" and parts[-2] == "Contents"
            and parts[-3].endswith(".app")):
        return os.path.dirname(os.path.dirname(os.path.dirname(exe_dir)))
    return exe_dir


def _writable(folder: str) -> bool:
    return bool(folder) and os.path.isdir(folder) and os.access(folder, os.W_OK)


def _report_dir() -> str:
    """Somewhere to leave a crash or self-test report, in order of usefulness.

    Beside the app is where anyone would look first. The data folder is the
    fallback for an app dragged into /Applications, and the temp folder is the
    last resort so a report is never simply lost.
    """
    here = _app_folder()
    if _writable(here):
        return here
    try:
        from dealhunter.paths import DATA_DIR
        if _writable(str(DATA_DIR)):
            return str(DATA_DIR)
    except Exception:
        pass
    import tempfile
    return tempfile.gettempdir()


def _show_dialog(title: str, text: str) -> None:
    """Best-effort message box. There is no Tk in this app, so use the system.

    Failing to show a dialog must never be the thing that hides the error, so
    every route is wrapped and silence is acceptable - the log file still has
    the whole story.
    """
    try:
        if sys.platform == "darwin":
            import subprocess
            script = (
                'display dialog {} with title {} buttons {{"OK"}} '
                'default button "OK" with icon stop'
            ).format(_applescript_string(text), _applescript_string(title))
            subprocess.run(["osascript", "-e", script], timeout=120,
                           capture_output=True, check=False)
        elif os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)
    except Exception:
        pass


def _applescript_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _report(exc: BaseException) -> None:
    """Record a start-up failure and, if possible, show it."""
    text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    path = os.path.join(_report_dir(), "dealhunter-crash.log")
    try:
        import datetime
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n===== {} =====\npython {}\nexecutable {}\n{}\n".format(
                datetime.datetime.now().isoformat(timespec="seconds"),
                sys.version.replace("\n", " "), sys.executable, text))
    except Exception:
        path = "(could not be written)"
    try:
        sys.stderr.write(text)
    except Exception:
        pass
    summary = text.strip().splitlines()[-1] if text.strip() else repr(exc)
    _show_dialog("eBay Deal Hunter could not start",
                 "{}\n\nFull details: {}".format(summary, path))


# --------------------------------------------------------------------------- #
# terminal modes
# --------------------------------------------------------------------------- #

def run_headless_scan(args) -> int:
    """Terminal mode - handy for a scheduled scan without opening the window."""
    from dealhunter import core

    cfg = core.load_config()
    conn = core.open_db()
    try:
        result = core.scan_all(
            cfg, conn,
            names=args.watch.split(",") if args.watch else None,
            group=args.group.split(",") if args.group else None,
            demo=args.demo,
        )
    finally:
        conn.close()
    if not result.get("ok"):
        core.log("Scan failed: " + result.get("error", "unknown error"))
        return 1
    core.log(f"Done - {result['new_hits']} new, {result['scanned']} matching listings.")
    return 0


def list_watches() -> int:
    from dealhunter import core

    cfg = core.load_config()
    watches = cfg.get("watches", [])
    groups: dict[str, list] = {}
    for w in watches:
        groups.setdefault(w.get("group", "Other"), []).append(w)
    on = sum(1 for w in watches if w.get("enabled", True))
    print(f"\n{len(watches)} watches in {len(groups)} groups ({on} switched on)\n")
    for group in sorted(groups):
        print(f"  {group}")
        for w in groups[group]:
            mark = "on " if w.get("enabled", True) else "off"
            print(f"    [{mark}] {w['name']:<28} up to GBP {str(w.get('max_price', '-')):<6}"
                  f" {w.get('min_discount_pct', 0)}%+ under market")
        print()
    return 0


# --------------------------------------------------------------------------- #
# self-test
# --------------------------------------------------------------------------- #

def _backend_module() -> str:
    """The pywebview backend this platform is expected to load."""
    if sys.platform == "darwin":
        return "webview.platforms.cocoa"
    if os.name == "nt":
        return "webview.platforms.winforms"
    return "webview.platforms.gtk"


def selftest() -> int:
    """Report what this build actually has. Run by the build scripts.

    A windowed build has no console, so the report is also written to
    dealhunter-selftest.txt beside the app - that file is the thing to send on
    when a build misbehaves.
    """
    lines = []

    def say(text=""):
        lines.append(text)
        try:
            if sys.__stdout__ is not None:
                sys.__stdout__.write(text + "\n")
        except Exception:
            pass

    frozen = bool(getattr(sys, "frozen", False))
    say("executable : {}".format(sys.executable))
    say("python     : {}".format(sys.version.replace("\n", " ")))
    say("frozen     : {}".format(frozen))
    say("app folder : {}".format(_app_folder()))
    ok = True

    # -- the native window ------------------------------------------------- #
    # Without a backend the app still runs, in the browser - so outside a
    # packaged build this is only a warning. Inside one it is a real problem:
    # the build script installed the backend on purpose.
    try:
        import webview
        say("pywebview  : {}".format(getattr(webview, "__version__", "unknown")))
        try:
            __import__(_backend_module())
            say("  backend  : {} ok".format(_backend_module()))
        except Exception as exc:
            if frozen:
                ok = False
            say("  backend  : {} FAILED - {}".format(_backend_module(), exc))
        for label, mod in (("pyobjc (macOS)", "objc"), ("WebKit (macOS)", "WebKit"),
                           ("pythonnet (Windows)", "clr")):
            want = ("macOS" in label and sys.platform == "darwin") or \
                   ("Windows" in label and os.name == "nt")
            if not want:
                continue
            try:
                __import__(mod)
                say("  {:<20} yes".format(label))
            except Exception as exc:
                say("  {:<20} no - {}".format(label, exc))
    except Exception as exc:
        if frozen:
            ok = False
        say("pywebview  : unavailable - the app would fall back to the browser ({})".format(exc))

    # -- where the data lives ----------------------------------------------- #
    try:
        from dealhunter.paths import DATA_DIR
        folder = str(DATA_DIR)
        say("data folder: {}".format(folder))
        writable = os.access(folder, os.W_OK)
        say("  writable : {}".format("yes" if writable else "NO"))
        if not writable:
            ok = False
        # Data inside the .app would invalidate its signature on first write.
        marker = ".app" + os.sep
        if sys.platform == "darwin" and marker in folder + os.sep:
            ok = False
            say("  PROBLEM  : the data folder is inside the app bundle")
    except Exception as exc:
        ok = False
        say("data folder: FAILED - {}".format(exc))

    # -- the engine ---------------------------------------------------------- #
    for label, mod in (("engine", "dealhunter.core"),
                       ("server", "dealhunter.server")):
        try:
            __import__(mod)
            say("{:<11}: {} imports cleanly".format(label, mod))
        except Exception as exc:
            ok = False
            say("{:<11}: FAILED - {}".format(label, exc))

    say("RESULT: {}".format("ok" if ok else "PROBLEMS FOUND"))

    report = os.path.join(_report_dir(), "dealhunter-selftest.txt")
    try:
        with open(report, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except Exception:
        pass
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# the app
# --------------------------------------------------------------------------- #

def open_window(url: str) -> bool:
    """Native window via pywebview. Returns False if it isn't usable here."""
    from dealhunter import APP_TITLE, core

    try:
        import webview
    except ImportError:
        return False
    try:
        webview.create_window(
            APP_TITLE, url,
            width=1340, height=900, min_size=(900, 620),
            confirm_close=False,
        )
        webview.start()  # blocks until the window is closed
        return True
    except Exception as exc:  # no GUI backend, headless machine, etc.
        core.log(f"Native window unavailable ({exc}) - falling back to the browser.")
        return False


def run(argv) -> int:
    import webbrowser

    from dealhunter import APP_TITLE, __version__
    from dealhunter import core, server
    from dealhunter.paths import DATA_DIR, LOG_PATH

    parser = argparse.ArgumentParser(description=f"{APP_TITLE} {__version__}")
    parser.add_argument("--browser", action="store_true", help="use the default browser instead of a window")
    parser.add_argument("--scan", action="store_true", help="run one scan in the terminal and exit")
    parser.add_argument("--list", action="store_true", help="list every watch and exit")
    parser.add_argument("--watch", help="with --scan: only these watches, comma separated")
    parser.add_argument("--group", help="with --scan: only this category")
    parser.add_argument("--demo", action="store_true", help="use demo data instead of calling eBay")
    parser.add_argument("--port", type=int, default=8756, help="preferred local port")

    # parse_known_args, not parse_args: an unexpected argument must never be
    # able to exit(2) a windowed build, which would close with no window and
    # no message at all.
    args, unknown = parser.parse_known_args(argv)

    # Mirror the log to a file so problems are diagnosable after the fact.
    try:
        log_file = open(LOG_PATH, "a", encoding="utf-8")
        original_sink = core.LOG_SINK

        def sink(line):
            log_file.write(line + "\n")
            log_file.flush()
            if original_sink:
                original_sink(line)

        core.LOG_SINK = sink
    except OSError:
        pass

    if unknown:
        core.log("Ignoring unrecognised arguments: " + " ".join(unknown))

    if args.list:
        return list_watches()
    if args.scan:
        return run_headless_scan(args)

    core.load_config()  # writes the starter config on a fresh install
    httpd, url = server.start(args.port)
    core.log(f"Data folder: {DATA_DIR}")

    if args.browser or not open_window(url):
        # No window of our own, so there is nothing to close. The page shows a
        # Quit button in this mode - a packaged build has no console for
        # Ctrl-C and would otherwise keep running invisibly.
        server.STATE.browser_mode = True
        webbrowser.open(url)
        core.log(f"Open in your browser: {url}")
        core.log("Use the Quit button at the top of the page (or Ctrl-C here) to stop.")
        try:
            while not server.STATE.quit_requested.wait(1):
                pass
        except KeyboardInterrupt:
            pass

    server.STATE.shutdown()
    httpd.shutdown()
    core.log("Closed.")
    return 0


def main() -> int:
    # macOS hands a Finder-launched .app an extra "-psn_0_12345" argument.
    # argparse treats it as an error and exits(2), which in a windowed build
    # looks exactly like the app refusing to open.
    argv = [a for a in sys.argv[1:] if not a.startswith("-psn_")]

    if argv and argv[0] == "selftest":
        return selftest()

    try:
        return run(argv)
    except SystemExit:
        raise
    except BaseException as exc:      # noqa: BLE001 - last chance to say why
        _report(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())

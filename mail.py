#!/usr/bin/env python3
"""
Dogbox Mailman — AI Email Client
Usage: python web_server.py [--port 5200]

Stores all data in postbox.pbox in the app directory.
"""
import sys
import os
import argparse
import threading
import subprocess
import webbrowser
import logging
import atexit

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")
logging.getLogger("werkzeug").setLevel(logging.ERROR)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_DATA_DIR = os.path.dirname(os.path.abspath(__file__))
_CHROME_PROFILE = os.path.join(_DATA_DIR, ".postbox-chrome-profile")
_browser_proc = None

import web.server as _srv
from core.database import initialise_database
from core.imap_sync import start_all


def _close_browser():
    if not _browser_proc or _browser_proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            subprocess.call(
                ["taskkill", "/F", "/T", "/PID", str(_browser_proc.pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            _browser_proc.terminate()
    except Exception:
        pass


atexit.register(_close_browser)


def _server_already_running(host: str, port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        try:
            s.connect((host, port))
            return True
        except (ConnectionRefusedError, OSError):
            return False


def _open_app_browser(url: str) -> bool:
    global _browser_proc

    if sys.platform == "win32":
        _CHROME_PATHS = [
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
        ]
        _EDGE_PATHS = [
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        ]
        _BRAVE_PATHS = [
            os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
        ]
        _CHROMIUM_PATHS = [
            os.path.expandvars(r"%LOCALAPPDATA%\Chromium\Application\chrome.exe"),
        ]
    elif sys.platform == "darwin":
        _CHROME_PATHS = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
        _EDGE_PATHS = ["/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
        _BRAVE_PATHS = ["/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"]
        _CHROMIUM_PATHS = ["/Applications/Chromium.app/Contents/MacOS/Chromium"]
    else:
        _CHROME_PATHS = ["/usr/bin/google-chrome", "/usr/bin/google-chrome-stable"]
        _EDGE_PATHS = ["/usr/bin/microsoft-edge"]
        _BRAVE_PATHS = ["/usr/bin/brave-browser"]
        _CHROMIUM_PATHS = ["/usr/bin/chromium-browser", "/usr/bin/chromium"]

    def _find(paths):
        for p in paths:
            if p and os.path.isfile(p):
                return p
        return None

    def _launch(exe):
        try:
            proc = subprocess.Popen(
                [exe, f"--app={url}", f"--user-data-dir={_CHROME_PROFILE}",
                 "--no-first-run", "--no-default-browser-check",
                 "--disable-session-crashed-bubble"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return proc
        except Exception:
            return None

    # Prefer default Chromium browser on Windows
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice") as k:
                prog_id = winreg.QueryValueEx(k, "ProgId")[0].lower()
            _CHROMIUM_IDS = ("chromehtml", "chromiumhtm", "msedgehtm", "bravehtml")
            if any(prog_id.startswith(p) for p in _CHROMIUM_IDS):
                if "chrome" in prog_id:
                    exe = _find(_CHROME_PATHS)
                elif "edge" in prog_id:
                    exe = _find(_EDGE_PATHS)
                elif "brave" in prog_id:
                    exe = _find(_BRAVE_PATHS)
                else:
                    exe = _find(_CHROME_PATHS + _EDGE_PATHS + _BRAVE_PATHS)
                if exe:
                    proc = _launch(exe)
                    if proc:
                        _browser_proc = proc
                        return True
        except Exception:
            pass

    for paths in (_EDGE_PATHS, _CHROME_PATHS, _BRAVE_PATHS, _CHROMIUM_PATHS):
        exe = _find(paths)
        if exe:
            proc = _launch(exe)
            if proc:
                _browser_proc = proc
                return True

    webbrowser.open(url)
    return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dogbox Mailman — AI Email Client")
    parser.add_argument("--port", type=int, default=5200)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"

    if _server_already_running(args.host, args.port):
        print(f"\n  Dogbox Mailman: already running at {url}")
        _open_app_browser(url)
        sys.exit(0)

    db_path = os.path.join(_DATA_DIR, "postbox.pbox")
    _srv.DB_PATH = db_path
    _srv.app.config["DB_PATH"] = db_path

    initialise_database(db_path)

    print(f"\n  Dogbox Mailman - AI Email Client")
    print(f"  {'-' * 35}")
    print(f"  Database : {db_path}")
    print(f"  Open     : {url}\n")

    # Start background sync for all configured accounts
    threading.Thread(
        target=start_all, args=(db_path,), daemon=True
    ).start()

    # Purge trash messages older than 30 days (by email date)
    def _purge_old_trash():
        from core.imap_actions import purge_old_trash
        try:
            n = purge_old_trash(db_path)
            if n:
                print(f"  Purged {n} trash message{'s' if n != 1 else ''} older than 30 days")
        except Exception as e:
            logging.getLogger(__name__).error("purge_old_trash: %s", e)

    threading.Thread(target=_purge_old_trash, daemon=True).start()

    def _open_browser():
        import time
        time.sleep(1.2)
        _open_app_browser(url)

    threading.Thread(target=_open_browser, daemon=True).start()

    _srv.app.run(host=args.host, port=args.port, debug=False, threaded=True)

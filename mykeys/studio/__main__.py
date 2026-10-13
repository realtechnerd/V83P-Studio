"""MyKeys Studio: `python -m mykeys.studio` (use pythonw to run without a console)."""
import argparse
import json
import logging
import os
import secrets
import shutil
import subprocess
import threading
import time
from pathlib import Path

import psutil

from .server import serve
from .service import KeyboardService

EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_edge():
    return next((p for p in EDGE_PATHS if os.path.exists(p)), shutil.which("msedge"))


def open_window(url):
    edge = find_edge()
    profile = Path(os.environ.get("LOCALAPPDATA", ".")) / "MyKeysStudio" / "edge"
    if edge:
        return subprocess.Popen([edge, f"--app={url}", f"--user-data-dir={profile}",
                                 "--window-size=1440,900", "--no-first-run", "--disable-features=Translate"])
    import webbrowser
    webbrowser.open(url)
    return None


def main():
    p = argparse.ArgumentParser(prog="mykeys.studio")
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--no-window", action="store_true", help="only start the server")
    p.add_argument("--json-ready", action="store_true", help="print {port, token} as JSON when listening (Electron)")
    p.add_argument("--parent-pid", type=int, help="exit when this process exits (Electron)")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO if a.verbose else logging.WARNING,
                        format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")

    svc = KeyboardService()
    token = secrets.token_urlsafe(16)
    httpd = serve(svc, token, a.port)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    if a.json_ready:
        print(json.dumps({"port": httpd.server_address[1], "token": token}), flush=True)
    else:
        print(f"MyKeys Studio at {url}")

    win = None if a.no_window else open_window(url)
    try:
        if win:
            win.wait()  # app window closed -> quit
        elif a.parent_pid:
            while psutil.pid_exists(a.parent_pid):
                time.sleep(2)
        else:
            threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()
        svc.shutdown()


if __name__ == "__main__":
    main()

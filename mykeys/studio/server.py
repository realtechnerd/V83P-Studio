"""Local JSON API + static file server for MyKeys Studio (127.0.0.1 only)."""
import json
import logging
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..apps import list_apps
from ..device import DeviceNotFound
from .service import KeyboardService, NotWired

log = logging.getLogger(__name__)
WEB = Path(__file__).resolve().parent / "web"
KEYCODES = Path(__file__).resolve().parent.parent / "data" / "keycodes.json"


def open_backups():
    """Show the firmware backups folder in File Explorer."""
    import os
    from ..config import BACKUPS
    BACKUPS.mkdir(parents=True, exist_ok=True)
    os.startfile(BACKUPS)


def make_routes(svc: KeyboardService):
    def body(b, *keys):
        return [b.get(k) for k in keys]

    return {
        ("GET", "/api/state"): lambda b: svc.state(lite=b.get("lite") == "1"),
        ("GET", "/api/keycodes"): lambda b: json.loads(KEYCODES.read_text(encoding="utf-8")),
        ("POST", "/api/lighting"): lambda b: vars(svc.set_lighting(b.get("fields", {}), b.get("save", False))),
        ("POST", "/api/perkey"): lambda b: svc.set_perkey(**{k: b[k] for k in
                                                             ("colors", "fill", "clear", "enabled", "save") if k in b}),
        ("GET", "/api/keymap"): lambda b: svc.get_keymap(),
        ("POST", "/api/key"): lambda b: svc.set_key(*body(b, "layer", "row", "col", "keycode")),
        ("POST", "/api/encoder"): lambda b: svc.set_encoder(*body(b, "layer", "clockwise", "keycode")),
        ("GET", "/api/macros"): lambda b: svc.get_macros(),
        ("POST", "/api/macros"): lambda b: svc.set_macros(b["slots"], b.get("names")),
        ("GET", "/api/rules"): lambda b: svc.get_rules(),
        ("POST", "/api/rules"): lambda b: svc.set_rules(b),
        ("GET", "/api/processes"): lambda b: svc.processes(),
        ("GET", "/api/apps"): lambda b: list_apps(),
        ("GET", "/api/firmware"): lambda b: svc.firmware_info(),
        ("POST", "/api/firmware/start"): lambda b: svc.firmware_start(b["action"], b.get("backup")),
        ("POST", "/api/firmware/cancel"): lambda b: svc.firmware_cancel(),
        ("POST", "/api/firmware/open-backups"): lambda b: open_backups(),
        ("POST", "/api/prefs"): lambda b: svc.set_prefs(b),
        ("GET", "/api/indicators"): lambda b: svc.get_indicators(),
        ("POST", "/api/indicators"): lambda b: svc.set_indicators(b),
        ("POST", "/api/indicators/preview"): lambda b: svc.preview_indicator(),
        ("GET", "/api/profiles"): lambda b: svc.list_profiles(),
        ("POST", "/api/profiles/save"): lambda b: svc.save_profile(b["name"]),
        ("POST", "/api/profiles/apply"): lambda b: svc.apply_profile(b["name"], b.get("to_keyboard", True),
                                                                     b.get("lighting_only", False)) and None,
        ("GET", "/api/autoprofiles"): lambda b: svc.get_autoprofiles(),
        ("POST", "/api/autoprofiles"): lambda b: svc.set_autoprofiles(b),
        ("POST", "/api/pause"): lambda b: svc.set_paused(b.get("paused", True)),
        ("GET", "/api/music"): lambda b: svc.music.public(),
        ("POST", "/api/music"): lambda b: svc.set_music(b),
        ("GET", "/api/music/frame"): lambda b: svc.music.snapshot(),
        ("POST", "/api/profiles/delete"): lambda b: svc.delete_profile(b["name"]),
    }


class Handler(BaseHTTPRequestHandler):
    routes = {}
    token = ""
    svc = None

    def log_message(self, fmt, *args):
        log.debug(fmt, *args)

    def _send(self, code, payload, ctype="application/json"):
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle(self, method):
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            # Only our own page may call the API (blocks other local sites/processes guessing the port).
            if self.headers.get("X-MyKeys-Token") != self.token:
                return self._send(403, {"error": "forbidden"})
            fn = self.routes.get((method, path))
            if not fn:
                return self._send(404, {"error": "no such endpoint"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
                b = json.loads(self.rfile.read(n) or b"{}") if n else {}
                if method == "GET":  # query string, e.g. /api/state?lite=1
                    b.update({k: v[-1] for k, v in parse_qs(urlparse(self.path).query).items()})
                result = fn(b)
                return self._send(200, {"ok": True, "data": result})
            except NotWired as e:
                return self._send(409, {"ok": False, "error": str(e), "code": "not_wired"})
            except (OSError, TimeoutError, DeviceNotFound) as e:
                # The keyboard left USB mid-change (switched to 2.4G/BT or unplugged): react right away
                # instead of waiting for the next connection check, and say so plainly.
                if self.svc.device_lost():
                    return self._send(409, {"ok": False, "code": "not_wired",
                                            "error": "The keyboard switched to wireless (or was unplugged), "
                                                     "so this change wasn't applied."})
                log.exception("API %s %s failed", method, path)
                return self._send(500, {"ok": False, "error": str(e)})
            except Exception as e:
                log.exception("API %s %s failed", method, path)
                return self._send(500, {"ok": False, "error": str(e)})
        if method != "GET":
            return self._send(405, {"error": "method not allowed"})
        f = (WEB / ("index.html" if path == "/" else path.lstrip("/"))).resolve()
        if WEB not in f.parents or not f.is_file():
            return self._send(404, b"not found", "text/plain")
        data = f.read_bytes()
        if f.name == "index.html":
            data = data.replace(b"__TOKEN__", self.token.encode())
        self._send(200, data, mimetypes.guess_type(f.name)[0] or "application/octet-stream")

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


def serve(svc, token, port=0):
    Handler.routes, Handler.token, Handler.svc = make_routes(svc), token, svc
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    return httpd

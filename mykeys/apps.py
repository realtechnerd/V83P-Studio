"""Apps the user can pick for reactions / auto profiles: Start-menu shortcuts plus apps with an open window.

Shortcuts (.lnk) are parsed directly (MS-SHLLINK format) so no COM / pywin32 is needed.
"""
import os
import re
import struct
import time
from pathlib import Path

import psutil

from .triggers import pids_with_windows

START_MENUS = [Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), r"Microsoft\Windows\Start Menu\Programs"),
               Path(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs")]
SKIP_NAME = re.compile(r"uninstall|readme|help|documentation|release notes|website|license", re.I)
SKIP_EXE = re.compile(r"^(unins\d*|uninstall.*|msiexec|explorer|cmd|powershell|rundll32|hh|notepad\+\+uninstall)\.exe$", re.I)
WINDIR = os.environ.get("WINDIR", r"C:\Windows").lower() + "\\"
_cache = {"t": 0.0, "apps": []}


def _lnk_target(path):
    """(target path, arguments) of a .lnk, or (None, "")."""
    try:
        d = Path(path).read_bytes()
        if len(d) < 0x4C or d[:4] != b"\x4c\x00\x00\x00":
            return None, ""
        flags = struct.unpack_from("<I", d, 0x14)[0]
        pos, target = 0x4C, None
        if flags & 0x01:                                   # LinkTargetIDList
            pos += 2 + struct.unpack_from("<H", d, pos)[0]
        if flags & 0x02:                                   # LinkInfo
            size, hdr = struct.unpack_from("<II", d, pos)
            li_flags = struct.unpack_from("<I", d, pos + 8)[0]
            if li_flags & 0x01:                            # VolumeIDAndLocalBasePath
                if hdr >= 0x24:
                    off = struct.unpack_from("<I", d, pos + 0x1C)[0]
                    end = d.find(b"\x00\x00", pos + off)
                    while end >= 0 and (end - pos - off) % 2:
                        end = d.find(b"\x00\x00", end + 1)
                    target = d[pos + off:end].decode("utf-16-le", "ignore")
                else:
                    off = struct.unpack_from("<I", d, pos + 0x10)[0]
                    target = d[pos + off:d.index(b"\x00", pos + off)].decode("mbcs", "ignore")
            pos += size
        strings, wide = {}, bool(flags & 0x80)
        for bit, key in ((0x04, "name"), (0x08, "rel"), (0x10, "dir"), (0x20, "args"), (0x40, "icon")):
            if flags & bit:
                n = struct.unpack_from("<H", d, pos)[0]
                raw = d[pos + 2:pos + 2 + n * (2 if wide else 1)]
                strings[key] = raw.decode("utf-16-le" if wide else "mbcs", "ignore")
                pos += 2 + n * (2 if wide else 1)
        if not target:                                     # EnvironmentVariableDataBlock (e.g. %ProgramFiles%\...)
            i = d.find(struct.pack("<I", 0xA0000001), pos)
            if i >= 4:
                w = d[i + 4 + 260:i + 4 + 260 + 520]
                target = os.path.expandvars(w.decode("utf-16-le", "ignore").split("\x00")[0]) or None
        return target, strings.get("args", "")
    except (OSError, struct.error, ValueError):
        return None, ""


def _start_menu_apps():
    apps = {}
    for root in START_MENUS:
        if not root.is_dir():
            continue
        for lnk in root.rglob("*.lnk"):
            name = lnk.stem
            if SKIP_NAME.search(name):
                continue
            target, args = _lnk_target(lnk)
            if not target or not target.lower().endswith(".exe") or target.lower().startswith(WINDIR):
                continue                                      # Windows' own tools (regedit, charmap, ...) aren't useful here
            exe = Path(target).name
            m = re.search(r"--processStart\s+\"?([^\s\"]+\.exe)", args, re.I)   # Squirrel launchers (Discord, Slack...)
            if exe.lower() == "update.exe" and m:
                exe = m.group(1)
            if SKIP_EXE.match(exe):
                continue
            apps.setdefault(exe.lower(), {"name": name, "exe": exe})
    return apps


def list_apps():
    """[{name, exe, running}] — installed (Start menu) apps plus anything with an open window, A–Z."""
    if time.monotonic() - _cache["t"] > 60:
        _cache["apps"], _cache["t"] = _start_menu_apps(), time.monotonic()
    apps = {k: dict(v, running=False) for k, v in _cache["apps"].items()}
    for pid in pids_with_windows():
        try:
            exe = psutil.Process(pid).name()
        except psutil.Error:
            continue
        if not exe.lower().endswith(".exe") or SKIP_EXE.match(exe) or exe.lower() in ("applicationframehost.exe", "textinputhost.exe", "systemsettings.exe", "shellexperiencehost.exe"):
            continue
        a = apps.setdefault(exe.lower(), {"name": exe[:-4], "exe": exe, "running": True})
        a["running"] = True
    return sorted(apps.values(), key=lambda a: a["name"].lower())

"""Firmware install / update / restore for the Studio app (the Device page wizard).

Steps of a job (status["step"]):
  driver      install the WinUSB driver for flash mode (one-time, Windows asks for admin)
  bootloader  get the keyboard into flash mode: automatic on our firmware, Esc + plug-in on the stock one
  backup      read the whole flash to DATA/backup/ (only when the keyboard isn't already on our firmware)
  flashing    write the new firmware
  replug      wait for the user to unplug + replug the cable (the tool's reset flag fails on this chip)
  done / error
Never uses the tool's -t (toolbox mode: disables read protection).
"""
import hashlib
import logging
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from .boards import current as BOARD
from .config import BACKUPS, ROOT

log = logging.getLogger(__name__)
NO_WINDOW = 0x08000000                     # CREATE_NO_WINDOW
FLASH_SIZE = 256 * 1024                    # WB32FQ95
DFU_ID = "VID_342D&PID_DFA0"


def tool(name):
    for p in (ROOT / "vendor" / name, shutil.which(name), Path(r"C:\QMK_MSYS\opt\qmk\bin") / name, Path(r"C:\QMK_MSYS") / name):
        if p and Path(p).is_file():
            return str(p)
    return None


def _run(args, timeout=120):
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def bundled_firmware():
    fw = BOARD.info.get("firmware", {})
    path = ROOT / "firmware" / fw.get("file", "")
    return {"file": fw.get("file"), "version": fw.get("version"), "release": fw.get("release"),
            "available": path.is_file()}, path


def driver_installed():
    """The flash-mode driver is in Windows' driver store (QMK MSYS, Zadig and our wizard all use libwdi)."""
    try:
        _, out = _run(["pnputil", "/enum-drivers"], timeout=30)
        return DFU_ID in out.upper()
    except (OSError, subprocess.SubprocessError):
        return False


def in_flash_mode():
    """The keyboard is in flash mode (its ROM bootloader is on USB). The tool's --list exits 0 either way,
    printing "Not found device!" or "Found DFU: [0x342D:0xDFA0] ...", so read its output."""
    dfu = tool("wb32-dfu-updater_cli.exe")
    try:
        return bool(dfu) and "found dfu: [0x342d:0xdfa0]" in _run([dfu, "--list"], timeout=10)[1].lower()
    except (OSError, subprocess.SubprocessError):
        return False


def list_backups():
    BACKUPS.mkdir(parents=True, exist_ok=True)
    out = []
    for p in sorted(BACKUPS.glob("*.bin"), key=lambda p: p.stat().st_mtime, reverse=True):
        if p.stat().st_size == FLASH_SIZE:     # only full-flash dumps can be restored
            out.append({"name": p.name, "date": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")})
    return out


class Flasher:
    def __init__(self, svc):
        self.svc = svc
        self.status = {"step": "idle"}
        self._cancel = threading.Event()
        self._thread = None

    @property
    def busy(self):
        return self._thread is not None and self._thread.is_alive()

    def info(self):
        fw, _ = bundled_firmware()
        return {"bundled": fw, "tools": bool(tool("wb32-dfu-updater_cli.exe")), "backups": list_backups(),
                "backup_dir": str(BACKUPS), "job": self.status}

    def start(self, action, backup=None):
        """action: 'install' (bundled firmware) or 'restore' (a backup file name from list_backups)."""
        if self.busy:
            raise RuntimeError("A firmware job is already running.")
        if action == "restore":
            if not backup or Path(backup).name != backup or not (BACKUPS / backup).is_file():
                raise ValueError("Choose a backup to restore.")
            image = BACKUPS / backup
        else:
            fw, image = bundled_firmware()
            if not fw["available"]:
                raise RuntimeError("The firmware file is missing from this install.")
        if not tool("wb32-dfu-updater_cli.exe"):
            raise RuntimeError("The flash tool is missing from this install.")
        self._cancel.clear()
        self._set("starting", "Starting…", action=action)
        self._thread = threading.Thread(target=self._job, args=(action, image), daemon=True, name="flasher")
        self._thread.start()

    def cancel(self):
        """Only possible while waiting for the user (driver prompt / Esc + plug / replug). Never mid-write."""
        if self.status.get("step") in ("bootloader", "replug", "starting", "driver"):
            self._cancel.set()

    def _set(self, step, message, **extra):
        keep = {k: self.status[k] for k in ("action", "backup", "manual") if k in self.status and step != "starting"}
        self.status = {"step": step, "message": message, **keep, **extra}
        log.info("flash: %s: %s", step, message)

    def _wait(self, cond, timeout, every=0.5):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self._cancel.is_set():
                raise InterruptedError
            if cond():
                return True
            time.sleep(every)
        return False

    def _job(self, action, image):
        svc, dfu = self.svc, tool("wb32-dfu-updater_cli.exe")
        try:
            # 1. driver (one-time)
            if not driver_installed():
                self._set("driver", "Installing the flash-mode driver. Windows will ask for permission: click Yes.")
                inst = tool("qmk_driver_installer.exe")
                if not inst:
                    raise RuntimeError("The driver installer is missing from this install.")
                lst = ROOT / "vendor" / "drivers.txt"
                ps = (f"$p = Start-Process -FilePath '{inst}' -ArgumentList '--all','\"{lst}\"' -Verb RunAs -Wait -PassThru "
                      f"-WindowStyle Hidden; exit $p.ExitCode")
                code, out = _run(["powershell", "-NoProfile", "-Command", ps], timeout=300)
                if not driver_installed():
                    raise RuntimeError("The driver wasn't installed (permission was declined, or the installer failed). "
                                       "Try again and click Yes on the Windows prompt.")

            # 2. flash mode
            fw = svc.firmware or {}
            ours = bool(fw.get("mykeys")) and (fw.get("protocol") or 0) >= 2
            backup_needed = action == "install" and not fw.get("mykeys")
            if in_flash_mode():
                pass
            elif ours and svc.kb is not None:
                self._set("bootloader", "Switching the keyboard to flash mode…", manual=False)
                svc.enter_flash_mode()
                if not self._wait(in_flash_mode, 15):
                    raise RuntimeError("The keyboard didn't enter flash mode. Unplug and replug it, then try again.")
            else:
                svc.release_for_flash()
                self._set("bootloader", "Unplug the keyboard's cable. Then hold Esc and plug it back in. Keep holding "
                                        "Esc for 2 seconds.", manual=True)
                if not self._wait(in_flash_mode, 300):
                    raise RuntimeError("Flash mode didn't appear within 5 minutes.")

            # 3. backup of the original firmware
            if backup_needed:
                self._set("backup", "Backing up the keyboard's current firmware…")
                BACKUPS.mkdir(parents=True, exist_ok=True)
                dest = BACKUPS / f"original_{datetime.now():%Y%m%d_%H%M%S}.bin"
                code, out = _run([dfu, "-U", str(dest), "-Z", str(FLASH_SIZE)], timeout=180)
                data = dest.read_bytes() if dest.is_file() else b""
                if code != 0 or len(data) != FLASH_SIZE or data.count(0xFF) == len(data):
                    dest.unlink(missing_ok=True)
                    raise RuntimeError("Couldn't back up the current firmware, so nothing was changed. "
                                       "Unplug and replug the keyboard to use it normally.")
                self.status["backup"] = dest.name
                log.info("backup %s sha256 %s", dest.name, hashlib.sha256(data).hexdigest())

            # 4. write
            if not in_flash_mode():
                raise RuntimeError("The keyboard left flash mode before the firmware was written, so nothing was "
                                   "changed. Unplug and replug it, then try again.")
            self._set("flashing", "Writing the firmware. Don't unplug the keyboard…")
            code, out = _run([dfu, "-D", str(image)], timeout=300)
            if code != 0 and "dfu_cmd_read" in out.lower():
                # The write went through; the tool's read-back at the very end failed (seen when restoring a full
                # 256 KB backup). Don't call it a failure: what the keyboard starts with after the replug decides.
                log.warning("flash: read-back after writing failed, checking the result after replug: %s", out.strip()[-200:])
                code = 0
            if code != 0:
                last = out.strip().splitlines()[-1] if out.strip() else "no output"
                still = in_flash_mode()
                raise RuntimeError("Writing failed. " + (
                    "The keyboard is still in flash mode, so nothing is lost: try again." if still else
                    "Unplug and replug the keyboard. If it doesn't start normally, hold Esc while plugging it in "
                    "and try again: flash mode always works.") + f" ({last})")

            # 5. replug
            svc.resume_after_flash()
            self._set("replug", "Done writing. Unplug the cable and plug it back in.")
            if not self._wait(lambda: svc.connection == "wired" and svc.firmware, 600):
                raise RuntimeError("The keyboard didn't come back. Unplug and replug the cable.")
            got = svc.firmware
            if action == "install":
                want = (BOARD.info.get("firmware") or {}).get("release")
                if not got.get("mykeys") or (want and got.get("release") != want):
                    raise RuntimeError(f"The keyboard came back with firmware {got.get('release')}, not the new one. "
                                       "Try the install again.")
                self._set("done", f"Installed V83P Studio firmware {(BOARD.info.get('firmware') or {}).get('version', '')}.")
            else:
                kind = "V83P Studio firmware" if got.get("mykeys") else "original firmware"
                self._set("done", f"The backup was restored. The keyboard is running its {kind} (release {got.get('release')}).")
        except InterruptedError:
            svc.resume_after_flash()
            self._set("idle", "Cancelled.")
        except Exception as e:
            log.exception("firmware job failed")
            svc.resume_after_flash()
            self._set("error", str(e) or e.__class__.__name__)

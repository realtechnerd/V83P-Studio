"""Freeze the Python backend into dist/backend/ (v83p-backend.exe + its files) for the installer.

    python tools/build_backend.py            (or: cd electron && npm run dist  → backend + installer)

Bundles: the mykeys package (with its web UI, board definitions and keycodes), the current firmware for the
board, and the flash tools in vendor/. Nothing personal: user data lives in %APPDATA%\\V83P Studio.
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from mykeys.boards import current as BOARD  # noqa: E402

DIST, WORK = ROOT / "dist", ROOT / "build" / "pyinstaller"
firmware = ROOT / "firmware" / BOARD.info["firmware"]["file"]
vendor = [ROOT / "vendor" / n for n in ("wb32-dfu-updater_cli.exe", "qmk_driver_installer.exe", "drivers.txt")]
for f in [firmware, *vendor]:
    if not f.is_file():
        sys.exit(f"missing: {f}")

sep = ";"  # PyInstaller --add-data separator on Windows
args = [
    sys.executable, "-m", "PyInstaller", str(ROOT / "packaging" / "backend_main.py"),
    "--name", "v83p-backend", "--onedir", "--console",   # console app; Electron starts it hidden (stdout = handshake)
    "--noconfirm", "--clean", "--log-level", "WARN",
    "--distpath", str(DIST), "--workpath", str(WORK), "--specpath", str(WORK),
    "--icon", str(ROOT / "electron" / "assets" / "icon.ico"),
    "--collect-submodules", "mykeys", "--collect-data", "mykeys",
    "--collect-all", "soundcard", "--collect-submodules", "winrt",
    "--exclude-module", "tkinter", "--exclude-module", "pystray", "--exclude-module", "mykeys.tray",
    "--add-data", f"{firmware}{sep}firmware",
    *[x for f in vendor for x in ("--add-binary" if f.suffix == ".exe" else "--add-data", f"{f}{sep}vendor")],
]
print("building backend...")
subprocess.run(args, check=True, cwd=ROOT)
out = DIST / "v83p-backend"
target = DIST / "backend"
if target.exists():
    shutil.rmtree(target)
out.rename(target)
size = sum(p.stat().st_size for p in target.rglob("*") if p.is_file()) / 1e6
print(f"backend ready: {target} ({size:.0f} MB)")

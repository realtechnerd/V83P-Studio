"""Where things live.

ROOT: the program's own files (firmware, flash tools). The project folder when run from source, the bundled
      folder in the installed app.
DATA: the user's files (settings, reactions, profiles, firmware backups). The project folder when run from
      source; %APPDATA%\\V83P Studio in the installed app (the app passes it in MYKEYS_DATA).
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
DATA = Path(os.environ["MYKEYS_DATA"]) if os.environ.get("MYKEYS_DATA") else ROOT
RULES_PATH = DATA / "config" / "rules.json"
STATE_PATH = DATA / "config" / "studio_state.json"
PROFILES = DATA / "profiles"
BACKUPS = DATA / "backup"
for _d in (RULES_PATH.parent, PROFILES):
    _d.mkdir(parents=True, exist_ok=True)


def load_rules(path=RULES_PATH):
    """The user's reactions. None yet (fresh install) = an empty list."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"rules": []}

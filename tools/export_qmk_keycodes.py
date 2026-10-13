"""Run with QMK MSYS python from the qmk_mykeys root: dumps QMK's merged keycode spec to JSON."""
import json
import sys

sys.path.insert(0, "lib/python")
from qmk.keycodes import load_spec  # noqa: E402

spec = load_spec("latest")
json.dump(spec, open(sys.argv[1], "w"), indent=1)
print(len(spec["keycodes"]), "keycodes,", len(spec["ranges"]), "ranges")

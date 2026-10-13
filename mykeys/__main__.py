"""MyKeys command line.

  python -m mykeys info
  python -m mykeys set --effect solid_color --color "#ff0000" --brightness 200 [--save]
  python -m mykeys effects [--cycle]
  python -m mykeys play pulse '{"color": "#0080ff", "period": 1.5}' --seconds 5
  python -m mykeys run            # background service with triggers (Ctrl+C to stop)
  python -m mykeys tray           # same, with a system-tray icon
"""
import argparse
import json
import logging
import time

from .animations import from_spec, state_from_dict
from .device import Keyboard
from .via import EFFECTS, RGBMatrix


def cmd_info(rgb, a):
    info = rgb.kb.info
    print(f"{info['manufacturer_string']} {info['product_string']}  "
          f"release 0x{info['release_number']:04X}")
    print(f"VIA protocol {rgb.protocol_version()}, {rgb.layer_count()} layers")
    st = rgb.read()
    print(f"effect={st.effect} ({EFFECTS.get(st.effect, '?')}) brightness={st.brightness} "
          f"speed={st.speed} hue={st.hue} sat={st.sat}")


def cmd_set(rgb, a):
    fields = {k: v for k, v in [("effect", a.effect), ("brightness", a.brightness),
                                ("speed", a.speed), ("color", a.color),
                                ("hue", a.hue), ("sat", a.sat)] if v is not None}
    st = state_from_dict(fields, rgb.read())
    rgb.apply(st)
    if a.save:
        rgb.save()
    print("now:", st, "(saved)" if a.save else "(until replug; add --save to keep)")


def cmd_effects(rgb, a):
    if not a.cycle:
        for i, n in EFFECTS.items():
            print(f"{i:>3}  {n}")
        return
    orig = rgb.read()
    try:
        for i, n in EFFECTS.items():
            if i == 0:
                continue
            rgb.apply(orig.with_(effect=i))
            input(f"effect {i:>2} (assumed {n}). Enter = next, Ctrl+C = stop")
    except KeyboardInterrupt:
        print()
    finally:
        rgb.apply(orig, force=True)


def cmd_play(rgb, a):
    from .engine import Engine
    spec = {"type": a.type, **json.loads(a.params)}
    eng = Engine(rgb).start()
    eng.play(from_spec(spec))
    try:
        time.sleep(a.seconds)
    except KeyboardInterrupt:
        pass
    finally:
        eng.stop()


def cmd_keys(rgb, a):
    from .perkey import PerKey
    pk = PerKey(rgb.kb)
    info = pk.detect()
    if info is None:
        raise SystemExit("This keyboard runs stock firmware: per-key colors need the MyKeys firmware.")
    if a.clear:
        pk.clear()
    if a.fill:
        pk.fill(a.fill)
    if a.assign:
        colors = {}
        for item in a.assign:
            names, _, color = item.partition("=")
            for name in names.split(","):
                colors[name] = color
        pk.set_keys(colors)
    if a.off:
        pk.enable(False)
    elif a.fill or a.on:
        pk.enable(True)
    if a.save:
        pk.save()
    proto, leds, enabled, mode = pk.detect()
    print(f"MyKeys firmware v{proto}: {leds} LEDs, per-key {'ON' if enabled else 'off'}, "
          f"connection={['USB', 'BT1', 'BT2', 'BT3', '2.4G'][mode] if mode < 5 else mode}"
          + (" (saved to keyboard)" if a.save else ""))


def cmd_flash(rgb, a):
    """Put the keyboard in flash mode (without wiping settings when the firmware supports it) and flash."""
    import shutil
    import subprocess
    from pathlib import Path
    from .perkey import PerKey
    tool = shutil.which("wb32-dfu-updater_cli") or r"C:\QMK_MSYS\opt\qmk\bin\wb32-dfu-updater_cli.exe"
    from .boards import current as board
    fw = Path(a.firmware) if a.firmware else Path(__file__).resolve().parent.parent / "firmware" / board.info["firmware"]["file"]
    if not fw.is_file() or not Path(tool).is_file():
        raise SystemExit(f"missing: {fw if not fw.is_file() else tool}")
    info = PerKey(rgb.kb).detect()
    if not info or info[0] < 2:
        raise SystemExit("This firmware can't enter flash mode by command: hold Esc while plugging in, then run\n"
                         f'  "{tool}" -D "{fw}"')
    PerKey(rgb.kb).bootloader()
    rgb.kb.close()
    print("Keyboard is entering flash mode (settings are kept)…")
    for _ in range(40):
        time.sleep(0.25)
        if "found dfu: [0x342d:0xdfa0]" in subprocess.run([tool, "--list"], capture_output=True, text=True).stdout.lower():
            break  # (--list exits 0 even when nothing is found)
    else:
        raise SystemExit("Flash mode didn't appear; unplug and replug the keyboard to recover.")
    subprocess.run([tool, "-D", str(fw)], check=True)  # (its -R reset flag fails on this chip: exit 74)
    print("Done. Unplug and replug the cable to start the new firmware.")


def build_service(rgb):
    from .config import load_rules
    from .engine import Engine
    from .triggers import TriggerManager
    cfg = load_rules()
    eng = Engine(rgb)
    if "base" in cfg:
        eng.set_base(state_from_dict(cfg["base"], eng.original))
    trig = TriggerManager(eng, cfg.get("rules", []))
    return eng, trig


def cmd_run(rgb, a):
    eng, trig = build_service(rgb)
    eng.start()
    trig.start()
    print("MyKeys running. Ctrl+C to stop (original lighting is restored).")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        trig.stop()
        eng.stop()


def cmd_tray(rgb, a):
    from .tray import run_tray
    run_tray(rgb, build_service)


def main():
    p = argparse.ArgumentParser(prog="mykeys", description="Inland MK PRO V2 lighting control")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info")
    s = sub.add_parser("set")
    s.add_argument("--effect")
    s.add_argument("--brightness", type=int)
    s.add_argument("--speed", type=int)
    s.add_argument("--color", help="#rrggbb")
    s.add_argument("--hue", type=int)
    s.add_argument("--sat", type=int)
    s.add_argument("--save", action="store_true", help="persist to keyboard EEPROM")
    e = sub.add_parser("effects")
    e.add_argument("--cycle", action="store_true", help="step through effects on the keyboard")
    pl = sub.add_parser("play")
    pl.add_argument("type", help="pulse | flash | hue_sweep | fade | firmware | static")
    pl.add_argument("params", nargs="?", default="{}", help="JSON parameters")
    pl.add_argument("--seconds", type=float, default=5)
    k = sub.add_parser("keys", help="per-key colors (MyKeys firmware)")
    k.add_argument("assign", nargs="*", help="KEY=#rrggbb, e.g. W,A,S,D=#ff0000 ESC=#00ff00")
    k.add_argument("--fill", help="set every key to #rrggbb first")
    k.add_argument("--clear", action="store_true", help="remove per-key colors (show effect)")
    k.add_argument("--on", action="store_true")
    k.add_argument("--off", action="store_true", help="hide per-key colors without forgetting them")
    k.add_argument("--save", action="store_true", help="keep after unplugging")
    f = sub.add_parser("flash", help="flash MyKeys firmware without losing settings (firmware 2.1+)")
    f.add_argument("firmware", nargs="?", help="path to the .bin (default: the board's current MyKeys firmware)")
    sub.add_parser("run")
    sub.add_parser("tray")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO if a.verbose else logging.WARNING,
                        format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")

    with Keyboard() as kb:
        globals()[f"cmd_{a.cmd}"](RGBMatrix(kb), a)


if __name__ == "__main__":
    main()

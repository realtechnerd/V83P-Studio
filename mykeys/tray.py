"""System-tray front end: pause/resume, reload rules, quick test animations, quit."""
import logging

import pystray
from PIL import Image, ImageDraw

from .animations import Flash, HueSweep, Pulse

log = logging.getLogger(__name__)


def _icon():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((4, 14, 60, 50), 8, fill=(140, 200, 120))  # matcha
    for i, x in enumerate(range(10, 56, 9)):
        d.rectangle((x, 22, x + 6, 28), fill=(255, 255, 255))
        d.rectangle((x, 34, x + 6, 40), fill=(255, 255, 255))
    return img


def run_tray(rgb, build_service):
    state = {}

    def start():
        eng, trig = build_service(rgb)
        state.update(eng=eng, trig=trig)
        eng.start()
        trig.start()

    def stop():
        state["trig"].stop()
        state["eng"].stop()

    def toggle_pause(icon, item):
        eng = state["eng"]
        eng.paused = not eng.paused
        if eng.paused:
            rgb.apply(eng.original, force=True)

    def reload(icon, item):
        stop()
        start()
        log.info("rules reloaded")

    def test(anim):
        return lambda icon, item: state["eng"].play(anim())

    def quit_(icon, item):
        stop()
        icon.stop()

    start()
    menu = pystray.Menu(
        pystray.MenuItem("Paused", toggle_pause, checked=lambda i: state["eng"].paused),
        pystray.MenuItem("Reload rules", reload),
        pystray.MenuItem("Test", pystray.Menu(
            pystray.MenuItem("Flash", test(lambda: Flash("#ffffff", count=3))),
            pystray.MenuItem("Pulse (5s)", test(lambda: Pulse("#0080ff", duration=5, priority=70))),
            pystray.MenuItem("Rainbow (5s)", test(lambda: HueSweep(2.0, duration=5, priority=70))),
        )),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit (restore lighting)", quit_),
    )
    pystray.Icon("mykeys", _icon(), "MyKeys", menu).run()

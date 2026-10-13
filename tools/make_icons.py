"""Render the MyKeys icon (same design as mykeys/studio/web/icon.svg) to PNG/ICO for Electron."""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "electron" / "assets"
A, B = (182, 242, 143), (92, 201, 167)  # matcha gradient ends


def grad(size):
    g = Image.new("RGBA", (size, size))
    px = g.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size - 2)
            px[x, y] = tuple(round(A[i] + (B[i] - A[i]) * t) for i in range(3)) + (255,)
    return g


def icon(size, tray=False):
    s = size / 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    r = lambda x, y, w, h, rad: d.rounded_rectangle([x * s, y * s, (x + w) * s, (y + h) * s], rad * s, fill=255)
    body = Image.new("L", (size, size), 0)
    ImageDraw.Draw(body).rounded_rectangle([4 * s, 14 * s, 60 * s, 50 * s], 9 * s, fill=255)
    img.paste((21, 26, 20, 255), mask=body)
    # outline
    outline = Image.new("L", (size, size), 0)
    ImageDraw.Draw(outline).rounded_rectangle([4 * s, 14 * s, 60 * s, 50 * s], 9 * s, outline=255,
                                              width=max(1, round(3 * s)))
    for k in [(11, 21, 7, 6), (21, 21, 7, 6), (31, 21, 7, 6), (41, 21, 12, 6), (11, 31, 12, 6),
              (26, 31, 7, 6), (36, 31, 7, 6), (46, 31, 7, 6), (17, 41, 30, 4)]:
        r(*k, 1.5)
    both = Image.new("L", (size, size), 0)
    both.paste(255, mask=outline)
    both.paste(255, mask=mask)
    img.paste(grad(size), mask=both)
    return img


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    big = icon(512)
    big.save(OUT / "icon.png")
    big.save(OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    icon(32).save(OUT / "tray.png")
    print("icons ->", OUT)


if __name__ == "__main__":
    main()

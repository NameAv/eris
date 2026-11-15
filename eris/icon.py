"""Draws Eris's icon (eris.ico) so the window and desktop shortcut have one."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ICO = Path(__file__).with_name("eris.ico")


def make():
    s = 256
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((8, 8, s - 8, s - 8), fill=(22, 9, 12, 255), outline=(227, 38, 63, 255), width=18)
    font = None
    for name in ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            font = ImageFont.truetype(name, 150)
            break
        except OSError:
            pass
    font = font or ImageFont.load_default()
    d.text((s / 2, s / 2 + 4), "E", fill=(255, 255, 255, 255), font=font, anchor="mm")
    img.save(ICO, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return ICO


def path():
    return ICO if ICO.exists() else make()


if __name__ == "__main__":
    print(make())

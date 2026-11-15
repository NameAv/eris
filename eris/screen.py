"""Screenshots of whichever monitor your mouse is on."""
import base64
import io
from dataclasses import dataclass

import mss
from PIL import Image
from pynput.mouse import Controller

from . import config

_mouse = Controller()


@dataclass
class Shot:
    b64: str          # JPEG, base64
    left: int         # monitor position on the desktop (physical pixels)
    top: int
    width: int        # monitor size (physical pixels)
    height: int
    scale: float      # monitor px per image px
    img_w: int
    img_h: int

    def to_screen(self, box):
        """Image coords from Claude -> real desktop coords, clamped and padded."""
        x1, y1, x2, y2 = box
        x1 = max(0, min(self.img_w, x1)); x2 = max(0, min(self.img_w, x2))
        y1 = max(0, min(self.img_h, y1)); y2 = max(0, min(self.img_h, y2))
        p = config.BOX_PADDING
        return (int(self.left + x1 * self.scale) - p, int(self.top + y1 * self.scale) - p,
                int(self.left + x2 * self.scale) + p, int(self.top + y2 * self.scale) + p)


def monitor_under_mouse(sct):
    mx, my = _mouse.position
    for m in sct.monitors[1:]:
        if m["left"] <= mx < m["left"] + m["width"] and m["top"] <= my < m["top"] + m["height"]:
            return m
    return sct.monitors[1]


def grab() -> Shot:
    with mss.mss() as sct:
        mon = monitor_under_mouse(sct)
        raw = sct.grab(mon)
    img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    scale = 1.0
    if img.width > config.SHOT_MAX_WIDTH:
        scale = img.width / config.SHOT_MAX_WIDTH
        img = img.resize((config.SHOT_MAX_WIDTH, round(img.height / scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=config.SHOT_JPEG_QUALITY)
    return Shot(base64.standard_b64encode(buf.getvalue()).decode(), mon["left"], mon["top"],
                mon["width"], mon["height"], scale, img.width, img.height)

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
    sx: float         # monitor px per image px, horizontally
    sy: float         # ...and vertically
    img_w: int
    img_h: int

    def to_screen(self, box):
        """Image coords from the brain -> real desktop coords, clamped and padded."""
        x1, y1, x2, y2 = box
        x1 = max(0, min(self.img_w, x1)); x2 = max(0, min(self.img_w, x2))
        y1 = max(0, min(self.img_h, y1)); y2 = max(0, min(self.img_h, y2))
        p = config.BOX_PADDING
        return (int(self.left + x1 * self.sx) - p, int(self.top + y1 * self.sy) - p,
                int(self.left + x2 * self.sx) + p, int(self.top + y2 * self.sy) + p)


def new_sct():
    """mss renamed its entry point; support both spellings."""
    return mss.MSS() if hasattr(mss, "MSS") else mss.mss()


def monitor_under_mouse(sct):
    mx, my = _mouse.position
    for m in sct.monitors[1:]:
        if m["left"] <= mx < m["left"] + m["width"] and m["top"] <= my < m["top"] + m["height"]:
            return m
    return sct.monitors[1]


def grab(snap=1) -> Shot:
    """snap=28 makes both sides multiples of 28, which local Qwen-VL models
    need so their coordinates line up exactly with the image we sent."""
    with new_sct() as sct:
        mon = monitor_under_mouse(sct)
        raw = sct.grab(mon)
    img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    w, h = img.size
    if w > config.SHOT_MAX_WIDTH:
        w, h = config.SHOT_MAX_WIDTH, round(h * config.SHOT_MAX_WIDTH / w)
    if snap > 1:
        w, h = max(snap, round(w / snap) * snap), max(snap, round(h / snap) * snap)
    if (w, h) != img.size:
        img = img.resize((w, h), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=config.SHOT_JPEG_QUALITY)
    return Shot(base64.standard_b64encode(buf.getvalue()).decode(), mon["left"], mon["top"],
                mon["width"], mon["height"], mon["width"] / w, mon["height"] / h, w, h)

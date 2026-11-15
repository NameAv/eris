"""Screenshots of whichever monitor your mouse is on."""
import base64
import io
from dataclasses import dataclass, field

import mss
from PIL import Image, ImageDraw
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
    full: object = field(default=None, repr=False)   # full-sharpness PIL image of the monitor

    def to_screen(self, box):
        """Image coords from the brain -> real desktop coords, clamped and padded."""
        x1, y1, x2, y2 = box
        x1 = max(0, min(self.img_w, x1)); x2 = max(0, min(self.img_w, x2))
        y1 = max(0, min(self.img_h, y1)); y2 = max(0, min(self.img_h, y2))
        p = config.BOX_PADDING
        return (int(self.left + x1 * self.sx) - p, int(self.top + y1 * self.sy) - p,
                int(self.left + x2 * self.sx) + p, int(self.top + y2 * self.sy) + p)


def zoom(shot, box, snap=1, max_w=900):
    """Crop the full-sharpness screenshot around a box (screen coords) so the brain
    can place it precisely. Returns (b64 jpeg, crop_left, crop_top, sx, sy, w, h)
    where screen_x = crop_left + x * sx and screen_y = crop_top + y * sy."""
    if shot.full is None:
        return None
    x1, y1, x2, y2 = box
    cx, cy = (x1 + x2) / 2 - shot.left, (y1 + y2) / 2 - shot.top
    bw, bh = max(x2 - x1, 40), max(y2 - y1, 24)
    cw = int(min(max(bw * 3, 360), shot.width, 1400))
    ch = int(min(max(bh * 5, 240), shot.height, 900))
    left = int(min(max(cx - cw / 2, 0), shot.width - cw))
    top = int(min(max(cy - ch / 2, 0), shot.height - ch))
    crop = shot.full.crop((left, top, left + cw, top + ch))
    w, h = crop.size
    if w > max_w:
        w, h = max_w, round(h * max_w / w)
    if snap > 1:
        w, h = max(snap, round(w / snap) * snap), max(snap, round(h / snap) * snap)
    if (w, h) != crop.size:
        crop = crop.resize((w, h), Image.LANCZOS)
    buf = io.BytesIO()
    crop.save(buf, "JPEG", quality=85)
    return (base64.standard_b64encode(buf.getvalue()).decode(), shot.left + left,
            shot.top + top, cw / w, ch / h, w, h)


def new_sct():
    """mss renamed its entry point; support both spellings."""
    return mss.MSS() if hasattr(mss, "MSS") else mss.mss()


def monitor_under_mouse(sct):
    mx, my = _mouse.position
    for m in sct.monitors[1:]:
        if m["left"] <= mx < m["left"] + m["width"] and m["top"] <= my < m["top"] + m["height"]:
            return m
    return sct.monitors[1]


def _black_out(img, rects, mon):
    """Cover private fields (screen coords) with a solid block labelled 'hidden'."""
    d = ImageDraw.Draw(img)
    for x1, y1, x2, y2 in rects:
        a, b = x1 - mon["left"] - 2, y1 - mon["top"] - 2
        c, e = x2 - mon["left"] + 2, y2 - mon["top"] + 2
        if c <= 0 or e <= 0 or a >= img.width or b >= img.height:
            continue
        d.rectangle((a, b, c, e), fill=(20, 20, 20))
        d.text((a + 6, b + max(2, (e - b) // 2 - 6)), "hidden", fill=(200, 200, 200))


def grab(snap=1, max_w=None, hide=()) -> Shot:
    """snap=28 makes both sides multiples of 28, which local Qwen-VL models
    need so their coordinates line up exactly with the image we sent."""
    with new_sct() as sct:
        mon = monitor_under_mouse(sct)
        raw = sct.grab(mon)
    img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    if hide:   # before anything else touches it, so private fields never leave the PC
        _black_out(img, hide, mon)
    full = img
    w, h = img.size
    max_w = max_w or config.SHOT_MAX_WIDTH
    if w > max_w:
        w, h = max_w, round(h * max_w / w)
    if snap > 1:
        w, h = max(snap, round(w / snap) * snap), max(snap, round(h / snap) * snap)
    if (w, h) != img.size:
        img = img.resize((w, h), Image.LANCZOS, reducing_gap=2.0)   # fast high-quality shrink
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=config.SHOT_JPEG_QUALITY)
    return Shot(base64.standard_b64encode(buf.getvalue()).decode(), mon["left"], mon["top"],
                mon["width"], mon["height"], mon["width"] / w, mon["height"] / h, w, h, full)

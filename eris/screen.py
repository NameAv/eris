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
    left: int         # the captured area on the desktop (physical pixels): the monitor,
    top: int          # or just the app's window (then `monitor` says which monitor)
    width: int
    height: int
    sx: float         # screen px per image px, horizontally
    sy: float         # ...and vertically
    img_w: int
    img_h: int
    full: object = field(default=None, repr=False)   # full-sharpness PIL image of that area
    elements: list = field(default_factory=list)     # clickable things (see elements.py)
    app: object = None                               # the app in front (see apps.py)
    monitor: tuple = None   # (left, top, w, h) of the whole monitor, if only a window was sent

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


def monitor_for(sct, rect=None):
    """The monitor your app is on (the one with most of its window), else the one your
    mouse is on. (Not just the mouse: it's often over Eris on another screen.)"""
    if rect:
        def overlap(m):
            w = min(rect[2], m["left"] + m["width"]) - max(rect[0], m["left"])
            h = min(rect[3], m["top"] + m["height"]) - max(rect[1], m["top"])
            return max(0, w) * max(0, h)
        best = max(sct.monitors[1:], key=overlap)
        if overlap(best) > 0:
            return best
    return monitor_under_mouse(sct)


def window_area(rect, mon, margin=0.03, most=0.7, least=0.2):
    """Just the app's window (plus a little around it) as a capture area, or None when
    the window fills most of the screen anyway (or is too small to be the whole task)."""
    if not rect:
        return None
    mx, my = int(mon["width"] * margin), int(mon["height"] * margin)
    l, t = max(mon["left"], rect[0] - mx), max(mon["top"], rect[1] - my)
    r = min(mon["left"] + mon["width"], rect[2] + mx)
    b = min(mon["top"] + mon["height"], rect[3] + my)
    share = max(0, r - l) * max(0, b - t) / (mon["width"] * mon["height"])
    if not least <= share <= most:
        return None
    return {"left": l, "top": t, "width": r - l, "height": b - t}


def monitor_under_mouse(sct):
    mx, my = _mouse.position
    for m in sct.monitors[1:]:
        if m["left"] <= mx < m["left"] + m["width"] and m["top"] <= my < m["top"] + m["height"]:
            return m
    return sct.monitors[1]


def black_out(img, rects, mon):
    """Cover private fields (screen coords) with a solid block labelled 'hidden'."""
    d = ImageDraw.Draw(img)
    for x1, y1, x2, y2 in rects:
        a, b = x1 - mon["left"] - 2, y1 - mon["top"] - 2
        c, e = x2 - mon["left"] + 2, y2 - mon["top"] + 2
        if c <= 0 or e <= 0 or a >= img.width or b >= img.height:
            continue
        d.rectangle((a, b, c, e), fill=(20, 20, 20))
        d.text((a + 6, b + max(2, (e - b) // 2 - 6)), "hidden", fill=(200, 200, 200))


def capture(rect=None):
    """The raw screen of the monitor your app is on (stays on your PC until finish())."""
    with new_sct() as sct:
        mon = monitor_for(sct, rect)
        raw = sct.grab(mon)
    return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX"), mon


def grab(snap=1, max_w=None, hide=()) -> Shot:
    img, mon = capture()
    return finish(img, mon, snap, max_w, hide)


def finish(img, mon, snap=1, max_w=None, hide=()) -> Shot:
    """Black out private fields, shrink and encode. snap=28 makes both sides multiples
    of 28, which Qwen2.5-VL needs so its coordinates line up with the image we sent."""
    if hide:   # before anything else touches it, so private fields never leave the PC
        black_out(img, hide, mon)
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

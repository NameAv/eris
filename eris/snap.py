"""Snap a box exactly onto the real thing on screen.

The AI's box is a good guess but its edges are never pixel-perfect. Two
helpers measure the real edges instead of guessing:

1. Windows UI Automation (see uia.py): asks Windows for the exact rectangle of
   the button / link / text field at that spot. Pixel-perfect in browsers and
   most Windows apps, but apps that draw their own UI (like Unity) don't say.
2. Pixel snapping (here): looks at the screenshot around the box and pulls each
   edge onto the element's real border. Works everywhere, so it's the fallback.

Both are careful: if they aren't confident, the AI's box is kept as-is.
"""
import sys

import numpy as np

from . import config

INK = 12            # how different from the background a pixel must be to count as "something"
MAX_MOVE = 14       # an edge may move at most this many pixels (we only fix small errors)
MARGIN = 16         # look this far outside the box for the background and the real edges


def _bg(img, x1, y1, x2, y2):
    """Background colour = the most typical colour in a ring around the box."""
    W, H = img.shape[1], img.shape[0]
    ring = []
    for (a, b, c, d) in ((x1, y1, x2, y1 + 3), (x1, y2 - 3, x2, y2), (x1, y1, x1 + 3, y2), (x2 - 3, y1, x2, y2)):
        a, b, c, d = max(0, a), max(0, b), min(W, c), min(H, d)
        if c > a and d > b:
            ring.append(img[b:d, a:c].reshape(-1, 3))
    return np.median(np.concatenate(ring), axis=0)


def _edges(mask, x1, y1, x2, y2):
    """Find the element's real edges near the rough ones: a line that is mostly
    'something' with mostly background just outside it (a border or the edge of a
    filled button/field/image). Returns new (x1, y1, x2, y2), None where not found."""
    H, W = mask.shape
    w, h = x2 - x1, y2 - y1
    cols = slice(max(0, x1 + w // 6), min(W, x2 - w // 6))
    rows = slice(max(0, y1 + h // 5), min(H, y2 - h // 5))
    row_fill = lambda y: mask[y, cols].mean() if 0 <= y < H else 0.0
    col_fill = lambda x: mask[rows, x].mean() if 0 <= x < W else 0.0

    def find(start, step_out, fill):
        best = None
        for d in range(0, MAX_MOVE + 1):
            for y in (start - d, start + d):
                if fill(y) > 0.75 and fill(y + step_out) < 0.3:
                    return y
        return best
    top = find(y1, -1, row_fill)
    bottom = find(y2 - 1, +1, row_fill)
    left = find(x1, -1, col_fill)
    right = find(x2 - 1, +1, col_fill)
    return (left, top, None if right is None else right + 1, None if bottom is None else bottom + 1)


def _grow(seed, mask, rx=3, ry=2, limit=300):
    """Grow the seed through matching pixels, bridging gaps between letters (but
    not the wider gaps between separate words/things)."""
    cur = seed & mask
    for _ in range(limit):
        d = cur.copy()
        for dx in range(1, rx + 1):
            d[:, dx:] |= cur[:, :-dx]
            d[:, :-dx] |= cur[:, dx:]
        for dy in range(1, ry + 1):
            d[dy:, :] |= cur[:-dy, :]
            d[:-dy, :] |= cur[dy:, :]
        nxt = d & mask
        if (nxt == cur).all():
            return cur
        cur = nxt
    return cur


def _accept(old, new):
    (x1, y1, x2, y2), (nx1, ny1, nx2, ny2) = old, new
    if max(abs(nx1 - x1), abs(ny1 - y1), abs(nx2 - x2), abs(ny2 - y2)) > MAX_MOVE:
        return False
    if nx2 - nx1 < 6 or ny2 - ny1 < 6:
        return False
    ratio = (nx2 - nx1) * (ny2 - ny1) / max(1, (x2 - x1) * (y2 - y1))
    return 0.35 <= ratio <= 1.8


def pixel_snap(full, box, left=0, top=0):
    """full: PIL image of the monitor. box: screen coords incl. padding.
    left/top: monitor position. Returns a snapped box (screen coords, padded) or None."""
    p = config.BOX_PADDING
    x1, y1, x2, y2 = box[0] + p - left, box[1] + p - top, box[2] - p - left, box[3] - p - top
    W, H = full.size
    if x2 - x1 < 4 or y2 - y1 < 4:
        return None
    rx1, ry1 = max(0, x1 - MARGIN), max(0, y1 - MARGIN)
    rx2, ry2 = min(W, x2 + MARGIN), min(H, y2 + MARGIN)
    img = np.asarray(full.crop((rx1, ry1, rx2, ry2)).convert("RGB"), dtype=np.int16)
    if img.shape[0] < 8 or img.shape[1] < 8:
        return None
    bx1, by1, bx2, by2 = x1 - rx1, y1 - ry1, x2 - rx1, y2 - ry1
    bg = _bg(img, 0, 0, img.shape[1], img.shape[0])
    mask = np.abs(img - bg).max(axis=2) > INK
    new = None

    # 1) Borders / filled shapes: snap each edge onto a real edge nearby.
    e = _edges(mask, bx1, by1, bx2, by2)
    if sum(v is not None for v in e) >= 3:
        new = tuple(o if v is None else v for v, o in zip(e, (bx1, by1, bx2, by2)))
        if not _accept((bx1, by1, bx2, by2), new):
            new = None

    # 2) No borders (a text link, an icon): take the thing in the middle of the
    #    box, following only pixels of the same colour (so a blue link doesn't
    #    merge with the black words around it).
    if new is None:
        seed = np.zeros_like(mask)
        cx1, cx2 = bx1 + (bx2 - bx1) // 5, bx2 - (bx2 - bx1) // 5
        cy1, cy2 = by1 + (by2 - by1) // 4, by2 - (by2 - by1) // 4
        seed[cy1:cy2 + 1, cx1:cx2 + 1] = True
        core = seed & mask
        if not core.any():
            return None
        colour = np.median(img[core], axis=0)
        same = mask & (np.abs(img - colour).max(axis=2) < 110)   # incl. soft text edges
        thing = _grow(seed, same)
        if not thing.any():
            return None
        ys, xs = np.nonzero(thing)
        new = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)
        if not _accept((bx1, by1, bx2, by2), new):
            return None

    nx1, ny1, nx2, ny2 = (int(v) for v in new)
    return (nx1 + rx1 + left - p, ny1 + ry1 + top - p, nx2 + rx1 + left + p, ny2 + ry1 + top + p)


_uia = None


def snap(shot, box):
    """Best exact box for `box` (screen coords), or None to keep it."""
    global _uia
    if sys.platform == "win32" and config.USE_UIA:
        try:
            if _uia is None:
                from .uia import UIA
                _uia = UIA()
            exact = _uia.snap(box)
            if exact:
                return exact
        except Exception:
            pass
    if shot is not None and getattr(shot, "full", None) is not None:
        try:
            return pixel_snap(shot.full, box, shot.left, shot.top)
        except Exception:
            return None
    return None

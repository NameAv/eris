"""Windows' list of clickable things, turned into a numbered list for the AI.

Small local models are much better at reading ("[7] link 'Wikipedia'") than at
guessing exact pixel positions. When the thing to click is in this list, the AI
answers ELEMENT 7 and Eris draws the box on its exact rectangle.
Apps that draw their own UI (like Unity) don't report anything, so there she
falls back to pointing by sight, with the pixel snapping to tidy the edges.
"""
from . import config

LIMIT = 80


def pick(elements, mon):
    """Keep what's on the screenshot's monitor, top-to-bottom, left-to-right, numbered."""
    if not elements:
        return []
    left, top, w, h = mon
    keep = []
    for e in elements:
        x1, y1, x2, y2 = e["rect"]
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        if left <= cx < left + w and top <= cy < top + h:
            keep.append(e)
    keep.sort(key=lambda e: (round(e["rect"][1] / 12), e["rect"][0]))
    return keep[:LIMIT]


def describe(elements, shot, coords="pixels"):
    """The list as text, with positions in the same coordinates the AI uses."""
    from .uia import TYPE_NAMES
    if not elements:
        return ""
    lines = []
    for i, e in enumerate(elements, 1):
        x1, y1, x2, y2 = e["rect"]
        a, b = (x1 - shot.left) / shot.sx, (y1 - shot.top) / shot.sy
        c, d = (x2 - shot.left) / shot.sx, (y2 - shot.top) / shot.sy
        if coords == "norm1000":
            a, c = a * 1000 / shot.img_w, c * 1000 / shot.img_w
            b, d = b * 1000 / shot.img_h, d * 1000 / shot.img_h
        kind = TYPE_NAMES.get(e["type"], "item")
        name = f' "{e["name"]}"' if e["name"] else ""
        lines.append(f"[{i}] {kind}{name} at {int(a)},{int(b)} to {int(c)},{int(d)}")
    return ("Clickable things Windows reports on this screen. If the thing to click is one "
            "of these, reply ELEMENT <number> instead of BOX (it's exact):\n" + "\n".join(lines))


def rect(elements, n):
    """Screen box (with padding) for element number n, or None."""
    if not elements or not 1 <= n <= len(elements):
        return None
    x1, y1, x2, y2 = elements[n - 1]["rect"]
    p = config.BOX_PADDING
    return (x1 - p, y1 - p, x2 + p, y2 + p)

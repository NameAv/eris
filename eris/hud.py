"""The Neon HUD style: everything Eris draws on your screen, as angular glowing HUD
pieces. The box takes a shape that suits what it points at:
    ring   small square things (icons, play / close buttons): a circle with tick marks
    bar    long thin things (search bars, text fields, list rows): a slim frame with end brackets
    frame  ordinary buttons and items: cut corners, a tab on top, a few slashes
    panel  big things (images, panels): corner brackets and side tabs
plus the drag connector, its "drop here" tab, and plates for "scroll down" / "press Ctrl + S".
Every picture is drawn sharp at twice the size, shrunk, and given a soft red glow."""
import math

from PIL import Image, ImageDraw, ImageFilter

from . import config

SS = 2           # drawn at 2x then shrunk = smooth edges
DARK = (14, 3, 6)
WHITE = (255, 236, 232)


def _red():
    c = config.BOX_COLOR
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def _font(size):
    from PIL import ImageFont
    try:
        return ImageFont.truetype("bahnschrift.ttf", size)    # Windows' condensed HUD-style font
    except OSError:
        from .glowbox import _font as f
        return f(size)


FIELDS = {"text box", "dropdown", "list item", "tree item", "item", "menu item", "header", "slider"}
PRESSABLE = {"button", "checkbox", "option", "tab", "link"}


def shape_for(w, h, kind=None):
    """Which HUD shape suits a w x h target (box size, padding included). kind: what
    Windows says it is ("button", "text box"...), when she picked it from the list."""
    if max(w, h) <= 44 and 0.7 <= w / max(h, 1) <= 1.45:
        return "ring"
    if kind in FIELDS:
        return "bar"
    if kind == "image":
        return "panel" if w >= 160 and h >= 100 else "frame"
    if kind in PRESSABLE:
        return "panel" if w >= 300 and h >= 180 else "frame"
    if w / max(h, 1) >= 4.5 and h <= 64:
        return "bar"
    if w >= 300 and h >= 180:
        return "panel"
    return "frame"


class _Canvas:
    """Draws in final pixels on a 2x canvas; finish() shrinks it and adds the glow."""

    def __init__(self, w, h):
        self.size = (int(w), int(h))
        self.img = Image.new("RGBA", (int(w) * SS, int(h) * SS), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)

    @staticmethod
    def _p(pts):
        return [(x * SS, y * SS) for x, y in pts]

    def line(self, pts, colour, width, closed=False):
        pts = list(pts) + ([pts[0]] if closed else [])
        self.d.line(self._p(pts), fill=colour, width=int(width * SS), joint="curve")

    def poly(self, pts, fill, outline=None, width=1):
        self.d.polygon(self._p(pts), fill=fill)
        if outline:
            self.line(pts, outline, width, closed=True)

    def arc(self, cx, cy, r, start, end, colour, width):
        self.d.arc([(cx - r) * SS, (cy - r) * SS, (cx + r) * SS, (cy + r) * SS], start, end,
                   fill=colour, width=int(width * SS))

    def text(self, xy, s, size, colour, anchor="mm"):
        self.d.text((xy[0] * SS, xy[1] * SS), s, font=_font(size * SS), fill=colour, anchor=anchor)

    def text_width(self, s, size):
        return _font(size).getlength(s)

    def finish(self, glow=True):
        crisp = self.img.resize(self.size, Image.LANCZOS)
        if not glow:
            return crisp
        halo = crisp.filter(ImageFilter.GaussianBlur(5))
        a = halo.getchannel("A").point(lambda v: min(255, int(v * 1.6)))
        halo.putalpha(a)
        return Image.alpha_composite(halo, crisp)


def _cut(x1, y1, x2, y2, c):
    """A rectangle with the top-left and bottom-right corners cut off."""
    return [(x1 + c, y1), (x2, y1), (x2, y2 - c), (x2 - c, y2), (x1, y2), (x1, y1 + c)]


# ---------------- the box ----------------
def _ring(cv, x1, y1, x2, y2, red, alpha):
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    r = max(x2 - x1, y2 - y1) / 2 + 3
    cv.arc(cx, cy, r, 0, 360, red + (alpha,), 2.5)
    cv.arc(cx, cy, r + 4, 0, 360, red + (alpha // 3,), 1)
    for start in (-60, 30, 120, 210):                     # four bright tick arcs
        cv.arc(cx, cy, r + 4, start, start + 30, red + (alpha,), 3)


def _bar(cv, x1, y1, x2, y2, red, alpha):
    c = min(8, (y2 - y1) / 3)
    cv.line(_cut(x1, y1, x2, y2, c), red + (alpha,), 2, closed=True)
    acc = min(70, (x2 - x1) / 4)
    cv.line([(x1 + c, y1 - 4), (x1 + c + acc, y1 - 4)], red + (alpha,), 3)          # top-left strip
    cv.line([(x2 - c - acc, y2 + 4), (x2 - c, y2 + 4)], red + (alpha,), 3)          # bottom-right strip
    for x in (x1 - 5, x2 + 5):                                                       # end brackets
        cv.line([(x, y1 + 3), (x, y2 - 3)], red + (alpha,), 3)


def _frame(cv, x1, y1, x2, y2, red, alpha):
    c = max(4, min(10, (x2 - x1) / 6, (y2 - y1) / 3))
    cv.line(_cut(x1, y1, x2, y2, c), red + (alpha,), 2.5, closed=True)
    w = x2 - x1
    tx1, tx2 = x1 + w * 0.3, x1 + w * 0.7                                            # the top tab
    cv.poly([(tx1, y1), (tx1 + 5, y1 - 5), (tx2 - 5, y1 - 5), (tx2, y1)], red + (alpha,))
    for i in range(3):                                                               # slashes, top right
        sx = x2 - 14 - i * 6
        if sx > tx2 + 4:
            cv.line([(sx, y1 - 2), (sx + 4, y1 - 7)], red + (alpha,), 1.5)
    cv.line([(x1 + w * 0.4, y2 + 4), (x1 + w * 0.6, y2 + 4)], red + (alpha // 2,), 2)  # underline


def _panel(cv, x1, y1, x2, y2, red, alpha):
    cv.line(_cut(x1, y1, x2, y2, 12), red + (alpha // 2,), 1.2, closed=True)
    arm = min(46, (x2 - x1) / 5, (y2 - y1) / 5)
    o = 2
    for (cx, cy, dx, dy) in ((x1 - o, y1 - o, 1, 1), (x2 + o, y1 - o, -1, 1),
                             (x1 - o, y2 + o, 1, -1), (x2 + o, y2 + o, -1, -1)):     # corner brackets
        cv.line([(cx + dx * arm, cy), (cx, cy), (cx, cy + dy * arm)], red + (alpha,), 3.5)
    mid, side = (y1 + y2) / 2, min(40, (y2 - y1) / 6)
    for x in (x1 - 5, x2 + 5):                                                       # side tabs
        cv.line([(x, mid - side), (x, mid + side)], red + (alpha,), 4)
    w = x2 - x1                                                                      # header tab
    hx1, hx2 = x1 + w * 0.35, x1 + w * 0.65
    cv.poly([(hx1, y1 - o), (hx1 + 6, y1 - o - 5), (hx2 - 6, y1 - o - 5), (hx2, y1 - o)], red + (alpha,))


SHAPES = {"ring": _ring, "bar": _bar, "frame": _frame, "panel": _panel}


def _plate(cv, x, y, text, size, red, arrow=None, prefix=None):
    """The one label design: an angular, solid red plate with white text and a little end
    bracket ("DROP HERE", "DRAG", the notes, what to type). prefix: a small pale word
    before the text (e.g. TYPE). Returns its size."""
    small = max(9, int(size * 0.55))
    pw = cv.text_width(prefix, small) + 10 if prefix else 0
    tw = cv.text_width(text, size)
    aw = size + 10 if arrow else 0
    w, h = pw + aw + tw + 22, size + 12
    cv.poly(_cut(x, y, x + w, y + h, 6), red + (240,))
    cv.line([(x + w + 3, y + 3), (x + w + 3, y + h - 3)], red + (255,), 2)           # the end bracket
    tx = x + 11
    if prefix:
        cv.text((tx, y + h / 2), prefix, small, (255, 205, 205, 255), anchor="lm")
        tx += pw
    if arrow:
        _chevrons(cv, tx + size / 2 - 1, y + h / 2, arrow, WHITE + (255,), max(6, size * 0.45))
        tx += aw
    cv.text((tx, y + h / 2), text, size, WHITE + (255,), anchor="lm")
    return w, h


def _chevrons(cv, cx, cy, way, colour, s):
    turn = {"down": 90, "up": 270, "right": 0, "left": 180}[way]
    rad = math.radians(turn)
    for off in (-s * 0.55, s * 0.55):
        pts = [(-s / 2 + off, -s), (s / 2 + off, 0), (-s / 2 + off, s)]
        cv.line([(cx + px * math.cos(rad) - py * math.sin(rad), cy + px * math.sin(rad) + py * math.cos(rad))
                 for px, py in pts], colour, 2.5)


def label(text, size=17, prefix=None, arrow=None):
    """A plate on its own transparent picture, with the glow (what to type, the notes)."""
    probe = _Canvas(1, 1)
    small = max(9, int(size * 0.55))
    w = probe.text_width(text, size) + (probe.text_width(prefix, small) + 10 if prefix else 0) \
        + (size + 10 if arrow else 0) + 22
    m = 10
    cv = _Canvas(w + 2 * m + 6, size + 12 + 2 * m)
    _plate(cv, m, m, text, size, _red(), arrow, prefix)
    return cv.finish()


def box(w, h, hint="", grow=0, glow_margin=16, kind=None):
    """The HUD box for a w x h target, laid out like glowbox.render (target at
    glow_margin, glow_margin). What to type hangs under it on a red plate."""
    red = _red()
    G = glow_margin
    kind = shape_for(w, h, kind)
    tag = label(hint, 17, prefix="TYPE") if hint else None
    width = w + 2 * G if tag is None else max(w + 2 * G, G - 10 + tag.width)
    cv = _Canvas(width, h + 2 * G + (tag.height - 6 if tag else 0))
    x1, y1, x2, y2 = G - grow, G - grow, G + w + grow, G + h + grow
    SHAPES[kind](cv, x1, y1, x2, y2, red, 255)
    img = cv.finish()
    if tag:
        img.alpha_composite(tag, (max(0, G - 10), G + h + 2))
    return img


# ---------------- drag, notes ----------------
DROP_FRAMES = 12         # the drag beam is animated: its streaks flow toward the target
BEAM = 14                # how wide the beam of light streaks is, at most
ROOM = 8                 # space each side of it, for glitches to jump into


def _beam(length, frame, glitch):
    """A narrow strip of red light streaks (the banner's texture), `length` long, as
    RGBA: the streaks flow forward, its width swells and thins along it and over time,
    soft at the edges and not too bright; when glitching, a few chunks jump sideways and
    small blocks flicker. Lies along +x (drop() turns it toward the target)."""
    import random
    import numpy as np
    from . import theme
    L = max(8, int(length))
    tex = np.asarray(theme.streaks(L, BEAM, seed=11, density=3.4), dtype=np.float32)
    tex = np.roll(tex, int(frame * L / DROP_FRAMES / 3) % L, axis=1)     # flowing toward the target
    x = np.arange(L)
    t = frame / DROP_FRAMES * 2 * np.pi
    width = 0.62 + 0.22 * np.sin(x / 37.0 + t) + 0.14 * np.sin(x / 13.0 - 2 * t)  # breathing width
    rows = np.abs(np.linspace(-1, 1, BEAM))[:, None]
    across = np.clip(1 - rows / np.maximum(width, 0.15)[None, :], 0, 1) ** 0.8
    along = np.clip(np.minimum(x, L - 1 - x) / 18.0, 0.3, 1)                    # soft ends
    alpha = np.clip(tex.max(axis=2) * 2.4, 0, 235) * across * along[None, :]
    mid = BEAM // 2                                                             # a faint core: the path
    alpha[mid - 1:mid + 1] = np.maximum(alpha[mid - 1:mid + 1], 95 * along[None, :])
    tex[mid - 1:mid + 1] = np.maximum(tex[mid - 1:mid + 1], [200, 30, 45])
    H = BEAM + 2 * ROOM
    rgba = np.zeros((H, L, 4), dtype=np.float32)
    rgba[ROOM:ROOM + BEAM, :, :3] = np.clip(tex * 1.4, 0, 255)
    rgba[ROOM:ROOM + BEAM, :, 3] = alpha
    if glitch:
        rnd = random.Random(frame * 37)
        for _ in range(rnd.randint(2, 4)):                                 # a few chunks jump sideways
            c1 = rnd.randrange(0, L)
            c2 = min(L, c1 + rnd.randint(8, max(10, L // 8)))
            rgba[:, c1:c2] = np.roll(rgba[:, c1:c2], rnd.randint(-ROOM + 2, ROOM - 2), axis=0)
        for _ in range(rnd.randint(2, 5)):                                 # small blocks flicker
            bx, by = rnd.randrange(0, L), rnd.randrange(0, H - 2)
            rgba[by:by + 2, bx:bx + rnd.randint(4, 14)] = [255, 40, 60, 200]
    return Image.fromarray(np.clip(rgba, 0, 255).astype(np.uint8), "RGBA")


def drop(src, dst, frame=0):
    """A drag: the drop target framed (shape to suit it), a DROP HERE tab beside it, and
    a beam of red light streaks from what to drag to an arrowhead at the target, with a
    DRAG tag at the start. The streaks flow toward the target; some frames glitch.
    frame: 0..DROP_FRAMES-1 (cycle them). Returns (image, x, y)."""
    red = _red()
    pad = 44
    label_w = _Canvas(1, 1).text_width("DROP HERE", 12) + 70
    x0, y0 = int(min(src[0], dst[0]) - pad), int(min(src[1], dst[1]) - pad)
    x1 = int(max(src[2], dst[2] + label_w) + pad)
    y1 = int(max(src[3], dst[3]) + pad)
    cv = _Canvas(x1 - x0, y1 - y0)
    s = [v - o for v, o in zip(src, (x0, y0, x0, y0))]
    d = [v - o for v, o in zip(dst, (x0, y0, x0, y0))]
    SHAPES[shape_for(d[2] - d[0], d[3] - d[1])](cv, *d, red, 230)
    glitch = frame in (3, 4, 9) and config.GLITCH
    a = _edge(s, ((d[0] + d[2]) / 2, (d[1] + d[3]) / 2))
    b = _edge(d, ((s[0] + s[2]) / 2, (s[1] + s[3]) / 2))
    length = math.hypot(b[0] - a[0], b[1] - a[1])
    beam = None
    if length > 30:
        ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
        end = (b[0] - ux * 8, b[1] - uy * 8)
        base = (end[0] - ux * 18, end[1] - uy * 18)
        notch = (end[0] - ux * 11, end[1] - uy * 11)
        cv.poly([end, (base[0] - uy * 10, base[1] + ux * 10), notch,
                 (base[0] + uy * 10, base[1] - ux * 10)], red + (255,))     # angular arrowhead
        cv.poly([(a[0] - 4, a[1] - 4), (a[0] + 4, a[1] - 4), (a[0] + 4, a[1] + 4), (a[0] - 4, a[1] + 4)],
                red + (255,))                                          # a node where it starts
        lx, ly = s[2] + 8, s[1] - 22 if s[1] > 30 else s[3] + 6         # the DRAG tag
        _plate(cv, lx, ly, "DRAG", 10, red)
        run = length - 20                                              # the beam: start to arrowhead
        strip = _beam(run, frame, glitch).rotate(-math.degrees(math.atan2(uy, ux)), Image.BICUBIC, expand=True)
        mx, my = a[0] + ux * run / 2, a[1] + uy * run / 2
        beam = (strip, int(mx - strip.width / 2), int(my - strip.height / 2))
    tx, ty = d[2] + 10, (d[1] + d[3]) / 2 - 12                          # DROP HERE, beside the target
    cv.line([(d[2] + 2, ty + 12), (tx, ty + 12)], red + (255,), 2)
    _plate(cv, tx, ty, "DROP HERE", 12, red, arrow="left")
    img = cv.finish()
    if beam:
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        layer.paste(*beam[:1], beam[1:])
        img = Image.alpha_composite(layer, img)                         # under the arrowhead and tags
    return img, x0, y0


def note(text, way=None):
    """ "scroll down" / "press Ctrl + S": the same red plate, a little bigger."""
    return label(text.upper(), 17, arrow=way)


def _edge(rect, toward):
    cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
    dx, dy = toward[0] - cx, toward[1] - cy
    hw, hh = (rect[2] - rect[0]) / 2, (rect[3] - rect[1]) / 2
    t = min(hw / abs(dx) if dx else 1e9, hh / abs(dy) if dy else 1e9, 1.0)
    return cx + dx * t, cy + dy * t

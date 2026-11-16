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
def _ring(cv, x1, y1, x2, y2, red, alpha, v=0):
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    r = max(x2 - x1, y2 - y1) / 2 + 3
    col, dim = red + (alpha,), red + (alpha // 3,)
    if v == 1:                                            # two long arcs, like the close button
        cv.arc(cx, cy, r, 0, 360, col, 2)
        for start in (200, 20):
            cv.arc(cx, cy, r + 2.5, start, start + 100, col, 2)
    elif v == 2:                                          # notched ring with little spokes
        for start in (10, 100, 190, 280):
            cv.arc(cx, cy, r, start, start + 70, col, 2.5)
        for k in range(8):
            a = math.radians(k * 45 + 22.5)
            cv.line([(cx + math.cos(a) * (r + 2), cy + math.sin(a) * (r + 2)),
                     (cx + math.cos(a) * (r + 5), cy + math.sin(a) * (r + 5))], col, 1.5)
    else:                                                 # ring, faint halo, four tick arcs
        cv.arc(cx, cy, r, 0, 360, col, 2.5)
        cv.arc(cx, cy, r + 4, 0, 360, dim, 1)
        for start in (-60, 30, 120, 210):
            cv.arc(cx, cy, r + 4, start, start + 30, col, 3)


def _bar(cv, x1, y1, x2, y2, red, alpha, v=0):
    c = min(8, (y2 - y1) / 3)
    col = red + (alpha,)
    acc = min(70, (x2 - x1) / 4)
    cv.line(_cut(x1, y1, x2, y2, c), col, 2, closed=True)
    if v == 1:                                            # a step on top, a long strip underneath
        cv.line([(x1 + c, y1 - 4), (x1 + c + acc * 0.6, y1 - 4), (x1 + c + acc * 0.6 + 4, y1 - 8),
                 (x1 + c + acc * 1.4, y1 - 8)], col, 2)
        cv.line([(x1 + (x2 - x1) * 0.25, y2 + 4), (x2 - c, y2 + 4)], red + (alpha // 2,), 2)
        cv.line([(x2 + 5, y1 + 3), (x2 + 5, y2 - 3)], col, 3)
    elif v == 2:                                          # nodes at the ends, a tab in the middle
        for x in (x1 - 6, x2 + 2):
            cv.poly([(x, y1 + (y2 - y1) / 2 - 2), (x + 4, y1 + (y2 - y1) / 2 - 2),
                     (x + 4, y1 + (y2 - y1) / 2 + 2), (x, y1 + (y2 - y1) / 2 + 2)], col)
        mx = (x1 + x2) / 2
        cv.poly([(mx - acc / 2, y2), (mx - acc / 2 + 4, y2 + 4), (mx + acc / 2 - 4, y2 + 4), (mx + acc / 2, y2)], col)
        cv.line([(x2 - c - acc, y1 - 4), (x2 - c, y1 - 4)], col, 2)
    else:                                                 # strips at two corners, end brackets
        cv.line([(x1 + c, y1 - 4), (x1 + c + acc, y1 - 4)], col, 3)
        cv.line([(x2 - c - acc, y2 + 4), (x2 - c, y2 + 4)], col, 3)
        for x in (x1 - 5, x2 + 5):
            cv.line([(x, y1 + 3), (x, y2 - 3)], col, 3)


def _frame(cv, x1, y1, x2, y2, red, alpha, v=0):
    c = max(4, min(10, (x2 - x1) / 6, (y2 - y1) / 3))
    col = red + (alpha,)
    w, h = x2 - x1, y2 - y1
    cv.line(_cut(x1, y1, x2, y2, c), col, 2.5, closed=True)
    if v == 1:                                            # a tab underneath, brackets on the sides
        bx1, bx2 = x1 + w * 0.3, x1 + w * 0.7
        cv.poly([(bx1, y2), (bx1 + 5, y2 + 5), (bx2 - 5, y2 + 5), (bx2, y2)], col)
        for x in (x1 - 5, x2 + 5):
            cv.line([(x, y1 + h * 0.25), (x, y2 - h * 0.25)], col, 2.5)
        cv.line([(x1 + c, y1 - 4), (x1 + c + min(30, w / 5), y1 - 4)], red + (alpha // 2,), 2)
    elif v == 2:                                          # doubled corners and slashes
        d = 4
        cv.line([(x2 - 18, y1 - d), (x2 + d, y1 - d), (x2 + d, y1 + 10)], col, 2)
        cv.line([(x1 + 18, y2 + d), (x1 - d, y2 + d), (x1 - d, y2 - 10)], col, 2)
        for i in range(3):
            sx = x1 + c + 6 + i * 6
            cv.line([(sx, y1 - 2), (sx + 4, y1 - 7)], col, 1.5)
    else:                                                 # a tab on top, slashes, underline
        tx1, tx2 = x1 + w * 0.3, x1 + w * 0.7
        cv.poly([(tx1, y1), (tx1 + 5, y1 - 5), (tx2 - 5, y1 - 5), (tx2, y1)], col)
        for i in range(3):
            sx = x2 - 14 - i * 6
            if sx > tx2 + 4:
                cv.line([(sx, y1 - 2), (sx + 4, y1 - 7)], col, 1.5)
        cv.line([(x1 + w * 0.4, y2 + 4), (x1 + w * 0.6, y2 + 4)], red + (alpha // 2,), 2)


def _panel(cv, x1, y1, x2, y2, red, alpha, v=0):
    col = red + (alpha,)
    w, h = x2 - x1, y2 - y1
    o = 2
    arm = min(46, w / 5, h / 5)
    cv.line(_cut(x1, y1, x2, y2, 12), red + (alpha // 2,), 1.2, closed=True)
    if v != 1:                                            # corner brackets
        for (cx, cy, dx, dy) in ((x1 - o, y1 - o, 1, 1), (x2 + o, y1 - o, -1, 1),
                                 (x1 - o, y2 + o, 1, -1), (x2 + o, y2 + o, -1, -1)):
            cv.line([(cx + dx * arm, cy), (cx, cy), (cx, cy + dy * arm)], col, 3.5)
    mid, side = (y1 + y2) / 2, min(40, h / 6)
    if v == 1:                                            # header and footer tabs, a second outline
        cv.line(_cut(x1 - 3, y1 - 3, x2 + 3, y2 + 3, 14), col, 1.5, closed=True)
        for y, d in ((y1 - 3, -1), (y2 + 3, 1)):
            hx1, hx2 = x1 + w * 0.35, x1 + w * 0.65
            cv.poly([(hx1, y), (hx1 + 5, y + d * 4), (hx2 - 5, y + d * 4), (hx2, y)], col)
    elif v == 2:                                          # double side tabs and corner nodes
        for x in (x1 - 5, x2 + 5):
            for off in (-side * 0.6, side * 0.6):
                cv.line([(x, mid + off - side * 0.3), (x, mid + off + side * 0.3)], col, 3)
        for cx, cy in ((x1 + arm + 6, y1 - o), (x2 - arm - 6, y2 + o)):
            cv.poly([(cx - 3, cy - 3), (cx + 3, cy - 3), (cx + 3, cy + 3), (cx - 3, cy + 3)], col)
    else:                                                 # side tabs and a header tab
        for x in (x1 - 5, x2 + 5):
            cv.line([(x, mid - side), (x, mid + side)], col, 4)
        hx1, hx2 = x1 + w * 0.35, x1 + w * 0.65
        cv.poly([(hx1, y1 - o), (hx1 + 6, y1 - o - 5), (hx2 - 6, y1 - o - 5), (hx2, y1 - o)], col)


VARIANTS = 3


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


def box(w, h, hint="", grow=0, glow_margin=16, kind=None, variant=0):
    """The HUD box for a w x h target, laid out like glowbox.render (target at
    glow_margin, glow_margin). What to type hangs under it on a red plate."""
    red = _red()
    G = glow_margin
    kind = shape_for(w, h, kind)
    tag = label(hint, 17, prefix="TYPE") if hint else None
    width = w + 2 * G if tag is None else max(w + 2 * G, G - 10 + tag.width)
    cv = _Canvas(width, h + 2 * G + (tag.height - 6 if tag else 0))
    x1, y1, x2, y2 = G - grow, G - grow, G + w + grow, G + h + grow
    SHAPES[kind](cv, x1, y1, x2, y2, red, 255, variant % VARIANTS)
    img = cv.finish()
    if tag:
        img.alpha_composite(tag, (max(0, G - 10), G + h + 2))
    return img


# ---------------- drag, notes ----------------
LINE_H = 26              # height of a connector strip (it lies along +x, centre line in the middle)


def _hatch(cv, x1, x2, y1, y2, col, gap=4):
    """A block of slanted stripes //// between x1 and x2."""
    x = x1
    while x + (y2 - y1) < x2:
        cv.line([(x, y2), (x + (y2 - y1), y1)], col, 1.2)
        x += gap


def _connector(length, variant):
    """One of three HUD connector lines (thin lines, raised steps, hatching, ring nodes,
    tapered bars), `length` long, along +x, as a glowing RGBA strip."""
    L = max(40, int(length))
    red = _red()
    col = red + (255,)
    cv = _Canvas(L, LINE_H)
    c = LINE_H / 2
    at = lambda f: L * f
    size = lambda f, most: min(L * f, most)
    if variant == 0:                      # stepped: the line rises onto a hatched step, a node, a small step
        s1, s2 = at(0.12), at(0.12) + size(0.25, 120)
        n = max(s2 + 30, at(0.55))
        pts = [(0, c), (s1, c), (s1 + 5, c - 5), (s2, c - 5), (s2 + 5, c), (n - 4, c)]
        cv.line(pts, col, 1.5)
        _hatch(cv, s1 + 10, s2 - 6, c - 4, c, col)
        cv.arc(n, c, 4, 0, 360, col, 1.5)
        k1 = n + max(20, (L - n) * 0.45)
        k2 = min(L - 12, k1 + size(0.12, 60))
        if k2 > k1 + 12:
            cv.line([(n + 4, c), (k1, c), (k1 + 4, c - 4), (k2, c - 4), (k2 + 4, c), (L, c)], col, 1.5)
        else:
            cv.line([(n + 4, c), (L, c)], col, 1.5)
    elif variant == 1:                    # one line with an outlined slanted tab, a node and a small square
        cv.line([(0, c), (L, c)], col, 1.5)
        bw = size(0.2, 90)
        tab = [(4, c - 9), (4 + bw, c - 9), (11 + bw, c - 1), (11, c - 1)]
        cv.line(tab, col, 1.2, closed=True)
        _hatch(cv, 14, 4 + bw, c - 8, c - 2, red + (190,), gap=5)
        n = max(18 + bw + 20, at(0.6))
        if n < L - 20:
            cv.arc(n, c, 4, 0, 360, col, 1.5)
    else:                                 # peaked: a sharp peak, a notched plateau, ticks, a diamond, chevrons
        p0 = at(0.1)
        q1, q2 = p0 + 26, p0 + 26 + size(0.22, 110)               # the raised plateau
        notch = (q1 + q2) / 2
        n = max(q2 + 40, at(0.6))                                # the diamond node
        pts = [(0, c), (p0, c), (p0 + 7, c - 9), (p0 + 14, c - 4), (q1, c - 4),
               (notch - 4, c - 4), (notch, c - 1), (notch + 4, c - 4), (q2, c - 4), (q2 + 4, c), (n - 5, c)]
        cv.line(pts, col, 1.5)
        t0 = q2 + 12                                             # a row of little ticks
        for i in range(5):
            x = t0 + i * 5
            if x < n - 10:
                cv.line([(x, c - 3), (x, c)], col, 1.2)
        cv.line([(n - 5, c), (n, c - 5), (n + 5, c), (n, c + 5)], col, 1.3, closed=True)
        cv.line([(n + 5, c), (L, c)], col, 1.5)
        if L - 40 > n + 20:                                      # thin chevrons toward the arrow
            for x in (L - 40, L - 32):
                cv.line([(x, c - 4), (x + 4, c), (x, c + 4)], col, 1.3)
    return cv.finish()


def drop(src, dst, variant=1):
    """A drag: the drop target framed (shape to suit it), a DROP HERE tab beside it, a
    DRAG tag at the start, and a HUD connector line from what to drag to an arrowhead at
    the target. variant: which version of the target's shape and of the line (3 each).
    Returns (image, x, y)."""
    red = _red()
    pad = 44
    label_w = _Canvas(1, 1).text_width("DROP HERE", 12) + 70
    x0, y0 = int(min(src[0], dst[0]) - pad), int(min(src[1], dst[1]) - pad)
    x1 = int(max(src[2], dst[2] + label_w) + pad)
    y1 = int(max(src[3], dst[3]) + pad)
    cv = _Canvas(x1 - x0, y1 - y0)
    s = [v - o for v, o in zip(src, (x0, y0, x0, y0))]
    d = [v - o for v, o in zip(dst, (x0, y0, x0, y0))]
    SHAPES[shape_for(d[2] - d[0], d[3] - d[1])](cv, *d, red, 230, variant % VARIANTS)
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
        run = length - 20                                              # the line: start to arrowhead
        strip = _connector(run, variant % VARIANTS)
        if ux < 0:                         # pointing left: keep its bumps on the upper side
            strip = strip.transpose(Image.FLIP_TOP_BOTTOM)
        strip = strip.rotate(-math.degrees(math.atan2(uy, ux)), Image.BICUBIC, expand=True)
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

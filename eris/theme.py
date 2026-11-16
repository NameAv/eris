"""Eris's look: a neon-red HUD. Black, glowing red lines, sharp corners, a condensed font,
and streaks of red light across the top of the window."""
import random
import sys

FONT = "Bahnschrift" if sys.platform == "win32" else "DejaVu Sans Condensed"
RADIUS = 3              # no corner rounder than this: the HUD keeps its corners sharp

BG = "#040102"          # window background
CARD = "#0a0304"        # cards / chat area
CARD_2 = "#120507"      # Eris bubbles, inputs
BORDER = "#6b1019"
ACCENT = "#ff2236"      # neon red
ACCENT_HOVER = "#c9182a"
ACCENT_DIM = "#3d0910"  # your bubbles
GLOW = "#ff5b68"
TEXT = "#ffe4e1"
MUTED = "#b8706c"
GOLD = "#ffb04a"
ERROR = "#ff8a8a"
CAPTION_BG = "#130306"

STATES = {  # state -> (label, dot colour)
    "loading": ("Waking up", MUTED),
    "ready": ("Ready", "#4fd18b"),
    "listening": ("Listening", GLOW),
    "thinking": ("Thinking", GOLD),
    "guiding": ("Guiding", ACCENT),
    "off": ("Paused", MUTED),
}


def r(n):
    """A corner radius, kept HUD-sharp."""
    return min(n, RADIUS)


def streaks(w, h, seed=7, density=1.0):
    """Sparse streaks of red light on black, with soft red glows behind (the
    banner). Wraps around seamlessly left-right, so it can scroll forever."""
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
    rnd = random.Random(seed)
    pad = 24                                            # drawn wider, so the blur wraps too
    W = w + 2 * pad
    blobs = Image.new("RGB", (W, h), (0, 0, 0))
    glow = Image.new("RGB", (W, h), (0, 0, 0))
    lines = Image.new("RGB", (W, h), (0, 0, 0))
    bd, gd, d = ImageDraw.Draw(blobs), ImageDraw.Draw(glow), ImageDraw.Draw(lines)

    def twice(draw, x1, y1, x2, y2, **kw):              # once here, once a whole width along
        for shift in (0, -w, w):
            draw((x1 + shift + pad, y1, x2 + shift + pad, y2), **kw)
    for _ in range(max(2, int(w * h / 4000 * density))):          # soft red glows
        x, y = rnd.uniform(0, w), rnd.uniform(0, h)
        rw, rh = rnd.uniform(30, 120), rnd.uniform(6, 18)
        twice(bd.ellipse, x - rw, y - rh, x + rw, y + rh, fill=(rnd.randint(40, 90), 2, 6))
    for _ in range(max(8, int(w * h / 650 * density))):
        y = rnd.uniform(0, h)
        x = rnd.uniform(0, w)
        length = rnd.uniform(15, w * 0.45)
        heat = rnd.random() ** 1.6                      # most streaks are dim
        col = (int(60 + 170 * heat), int(4 + 30 * heat ** 3), int(8 + 26 * heat ** 3))
        twice(gd.line, x, y, x + length, y, fill=col, width=rnd.choice((2, 3, 4)))
        twice(d.line, x + length * 0.1, y, x + length * 0.9, y, fill=col, width=1)
        if heat > 0.8:                                   # a hot white-pink core
            twice(d.line, x + length * 0.4, y, x + length * 0.7, y, fill=(255, 190, 180), width=1)
    for _ in range(int(w * h / 1500 * density)):        # a few sparks
        x, y = rnd.uniform(0, w), rnd.uniform(0, h)
        twice(d.ellipse, x, y, x + 1, y + 1, fill=(255, 80, 70))
    out = ImageChops.add(ImageChops.add(blobs.filter(ImageFilter.GaussianBlur(10)),
                                        glow.filter(ImageFilter.GaussianBlur(3))), lines)
    return out.crop((pad, 0, pad + w, h))


_fonts = {}


def font(size=13, weight="normal", underline=False, family=None):
    """Shared font objects. They're made once and reused, never thrown away: Tk objects
    must only ever be created and destroyed on the window's own thread."""
    import customtkinter as ctk
    key = (size, weight, underline, family)
    if key not in _fonts:
        _fonts[key] = ctk.CTkFont(family=family or FONT, size=size, weight=weight,
                                  underline=underline)
    return _fonts[key]


def tint_titlebar(win):
    """A black title bar with a red outline on Windows 11, so the window looks seamless."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes
        u32 = ctypes.windll.user32
        u32.GetParent.restype = wintypes.HWND
        hwnd = u32.GetParent(win.winfo_id())
        dwm = ctypes.windll.dwmapi
        on = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), 4)          # dark mode
        r, g, b = (int(BG[i:i + 2], 16) for i in (1, 3, 5))
        caption = ctypes.c_int(r | g << 8 | b << 16)
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption), 4)     # title bar colour
        r, g, b = (int(ACCENT[i:i + 2], 16) for i in (1, 3, 5))
        border = ctypes.c_int(r | g << 8 | b << 16)
        dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(border), 4)      # red outline
    except Exception:
        pass



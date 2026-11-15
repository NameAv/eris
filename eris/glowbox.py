"""The pretty red box: rounded corners, a soft crimson glow, smooth edges, a quick
pop-in and a gentle pulse. Drawn as an image and shown in a click-through
"layered window" (each pixel has its own transparency). Windows only; anything
goes wrong and the overlay falls back to the plain bars.
"""
import math
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import config

GLOW = 16          # room around the box for the glow
SS = 2             # draw at 2x then shrink = smooth (anti-aliased) edges


def _font(size):
    for name in ("seguisb.ttf", "segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _rgb(hexcol):
    return tuple(int(hexcol[i:i + 2], 16) for i in (1, 3, 5))


def render(w, h, hint="", grow=0):
    """RGBA image of the box for a w x h target, with the glow around it.
    grow: draw the box this many px bigger (for the pop-in)."""
    red = _rgb(config.BOX_COLOR)
    W, H = w + 2 * GLOW, h + 2 * GLOW
    radius = max(4, min(10, min(w, h) // 3))
    x1, y1, x2, y2 = GLOW - grow, GLOW - grow, GLOW + w + grow, GLOW + h + grow

    # soft glow
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).rounded_rectangle((x1 - 1, y1 - 1, x2 + 1, y2 + 1), radius + 2,
                                           outline=red + (210,), width=6)
    glow = glow.filter(ImageFilter.GaussianBlur(6))
    # only glow outwards: never dim the thing you need to see
    inside = Image.new("L", (W, H), 0)
    ImageDraw.Draw(inside).rounded_rectangle((x1 + 1, y1 + 1, x2 - 1, y2 - 1), radius, fill=255)
    a = np.asarray(glow.getchannel("A"), dtype=np.uint8).copy()
    a[np.asarray(inside) > 0] = 0
    glow.putalpha(Image.fromarray(a))

    # crisp outline, drawn big then shrunk for smooth corners
    big = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    s = lambda *v: [int(round(a * SS)) for a in v]
    d.rounded_rectangle(s(x1 - 1.5, y1 - 1.5, x2 + 1.5, y2 + 1.5), (radius + 2) * SS,
                        outline=(25, 4, 8, 95), width=SS)                 # thin dark edge: shows on light/red UIs
    d.rounded_rectangle(s(x1, y1, x2, y2), radius * SS, outline=red + (255,), width=3 * SS)
    d.rounded_rectangle(s(x1 + 3, y1 + 3, x2 - 3, y2 - 3), max(1, radius - 3) * SS,
                        outline=(255, 255, 255, 70), width=SS)             # faint inner highlight
    crisp = big.resize((W, H), Image.LANCZOS)
    img = Image.alpha_composite(glow, crisp)

    if hint:   # "type: wikipedia" pill inside the right end of the box (or under it)
        f = _font(13)
        tw = int(f.getlength(hint)) + 18
        th = 22
        if w >= tw + 90 and h >= th + 4:
            px, py = GLOW + w - tw - 6, GLOW + (h - th) // 2
        else:
            px, py = GLOW, GLOW + h + 6
            if py + th > H:
                pad = Image.new("RGBA", (W, py + th + 2), (0, 0, 0, 0))
                pad.paste(img, (0, 0))
                img = pad
        pill = ImageDraw.Draw(img)
        pill.rounded_rectangle((px, py, px + tw, py + th), 11, fill=red + (240,))
        pill.text((px + 9, py + 3), hint, font=f, fill=(255, 255, 255, 255))
    return img


def premultiplied_bgra(img):
    """Windows layered windows want blue-green-red-alpha with colour pre-multiplied."""
    a = np.asarray(img, dtype=np.uint16)
    rgb = (a[..., :3] * a[..., 3:4] // 255).astype(np.uint8)
    out = np.empty(a.shape, dtype=np.uint8)
    out[..., 0], out[..., 1], out[..., 2] = rgb[..., 2], rgb[..., 1], rgb[..., 0]
    out[..., 3] = a[..., 3]
    return out.tobytes()


class GlowBox:
    """One layered window showing the rendered box. Call from the Tk thread."""

    def __init__(self, master):
        import ctypes
        from ctypes import wintypes
        import tkinter as tk
        self.master = master
        self.win = tk.Toplevel(master)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.geometry("1x1+-32000+-32000")
        self.win.deiconify()
        self.win.update_idletasks()
        self.hwnd = int(self.win.wm_frame(), 16)
        u32, g32 = ctypes.windll.user32, ctypes.windll.gdi32
        self.u32, self.g32, self.ct, self.wt = u32, g32, ctypes, wintypes

        class BLEND(ctypes.Structure):
            _fields_ = [("op", ctypes.c_ubyte), ("flags", ctypes.c_ubyte),
                        ("alpha", ctypes.c_ubyte), ("fmt", ctypes.c_ubyte)]

        class BIH(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                        ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                        ("biClrImportant", wintypes.DWORD)]
        self.BLEND, self.BIH = BLEND, BIH
        u32.GetDC.restype = wintypes.HDC
        u32.GetDC.argtypes = [wintypes.HWND]
        u32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        g32.CreateCompatibleDC.restype = wintypes.HDC
        g32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        g32.CreateDIBSection.restype = wintypes.HBITMAP
        g32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                         ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE,
                                         wintypes.DWORD]
        g32.SelectObject.restype = wintypes.HGDIOBJ
        g32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        g32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        g32.DeleteDC.argtypes = [wintypes.HDC]
        u32.UpdateLayeredWindow.restype = wintypes.BOOL
        u32.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC,
                                            ctypes.POINTER(wintypes.POINT),
                                            ctypes.POINTER(wintypes.SIZE), wintypes.HDC,
                                            ctypes.POINTER(wintypes.POINT), wintypes.COLORREF,
                                            ctypes.POINTER(BLEND), wintypes.DWORD]
        u32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        u32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
        # layered + click-through + never takes focus + not in the taskbar
        ex = u32.GetWindowLongW(self.hwnd, -20)
        u32.SetWindowLongW(self.hwnd, -20, ex | 0x80000 | 0x20 | 0x80 | 0x8000000 | 0x8)
        self.rect, self.hint, self.alpha = None, "", 255
        self.jobs = []
        self.shown_at = 0.0
        if not self._show_image(Image.new("RGBA", (2, 2), (0, 0, 0, 0)), -32000, -32000):
            raise OSError("layered window not supported")
        self._pulse()

    # ---- drawing ----
    def _show_image(self, img, x, y, alpha=255):
        ct, wt = self.ct, self.wt
        w, h = img.size
        screen = self.u32.GetDC(None)
        mem = self.g32.CreateCompatibleDC(screen)
        bih = self.BIH(ct.sizeof(self.BIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)   # top-down 32-bit
        bits = ct.c_void_p()
        bmp = self.g32.CreateDIBSection(mem, ct.byref(bih), 0, ct.byref(bits), None, 0)
        ok = False
        if bmp and bits:
            ct.memmove(bits, premultiplied_bgra(img), w * h * 4)
            old = self.g32.SelectObject(mem, bmp)
            blend = self.BLEND(0, 0, alpha, 1)          # AC_SRC_OVER, per-pixel alpha
            ok = bool(self.u32.UpdateLayeredWindow(
                self.hwnd, screen, ct.byref(wt.POINT(int(x), int(y))), ct.byref(wt.SIZE(w, h)),
                mem, ct.byref(wt.POINT(0, 0)), 0, ct.byref(blend), 2))      # ULW_ALPHA
            self.g32.SelectObject(mem, old)
            self.g32.DeleteObject(bmp)
        self.g32.DeleteDC(mem)
        self.u32.ReleaseDC(None, screen)
        return ok

    def _set_alpha(self, alpha):
        blend = self.BLEND(0, 0, int(alpha), 1)
        self.u32.UpdateLayeredWindow(self.hwnd, None, None, None, None, None, 0,
                                     self.ct.byref(blend), 2)

    def _draw(self, grow=0, alpha=255):
        x1, y1, x2, y2 = self.rect
        img = render(x2 - x1, y2 - y1, self.hint, grow)
        self._show_image(img, x1 - GLOW, y1 - GLOW, alpha)
        self.alpha = alpha

    def _cancel(self):
        for j in self.jobs:
            self.master.after_cancel(j)
        self.jobs = []

    # ---- public ----
    def show(self, rect, hint=""):
        """Pop in: starts a little bigger and transparent, settles onto the target."""
        self._cancel()
        self.rect, self.hint = tuple(int(v) for v in rect), hint
        self.shown_at = time.time()
        frames = [(10, 90), (6, 160), (3, 220), (1, 250), (0, 255)]
        for i, (grow, alpha) in enumerate(frames):
            self.jobs.append(self.master.after(i * 40, lambda g=grow, a=alpha: self._draw(g, a)))

    def move(self, rect):
        if self.rect is None:
            return
        self._cancel()
        self.rect = tuple(int(v) for v in rect)
        self._draw()

    def set_hint(self, hint):
        self.hint = hint
        if self.rect:
            self._draw(alpha=self.alpha)

    def hide(self):
        self._cancel()
        self.rect, self.hint = None, ""
        self._show_image(Image.new("RGBA", (2, 2), (0, 0, 0, 0)), -32000, -32000)

    def _pulse(self):
        """Gentle breathing glow so it stays noticeable without being annoying."""
        if self.rect and time.time() - self.shown_at > 0.3:
            t = time.time() - self.shown_at
            self._set_alpha(205 + 50 * (0.5 + 0.5 * math.cos(t * 2 * math.pi / 1.6)))
        self.master.after(70, self._pulse)

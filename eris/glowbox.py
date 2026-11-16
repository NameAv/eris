"""Shows the box on screen: a click-through "layered window" (each pixel has its own
transparency) that displays a picture from hud.py, with a quick pop-in and a gentle
pulse. Windows only; if anything goes wrong the overlay falls back to the plain bars."""
import math
import time

import numpy as np
from PIL import Image

GLOW = 16          # room around the box for its glow and decorations


def render(w, h, hint="", grow=0, kind=None, variant=0):
    """The box for a w x h target (the HUD shape that suits it, see hud.py), with the
    target at GLOW, GLOW in the picture. grow: draw it bigger (for the pop-in)."""
    from . import hud
    return hud.box(w, h, hint, grow, GLOW, kind, variant)


def render_drop(src, dst, variant=1):
    """A drag: (picture, x, y) of the line, arrow and drop target."""
    from . import hud
    return hud.drop(src, dst, variant)


def render_note(text, way=None):
    """ "scroll down" / "press Ctrl + S"."""
    from . import hud
    return hud.note(text, way)


def premultiplied_bgra(img):
    """Windows layered windows want blue-green-red-alpha with colour pre-multiplied."""
    a = np.asarray(img, dtype=np.uint16)
    rgb = (a[..., :3] * a[..., 3:4] // 255).astype(np.uint8)
    out = np.empty(a.shape, dtype=np.uint8)
    out[..., 0], out[..., 1], out[..., 2] = rgb[..., 2], rgb[..., 1], rgb[..., 0]
    out[..., 3] = a[..., 3]
    return out.tobytes()


_API = None


def _api():
    """The Windows drawing calls, set up once for the whole app. (Every box window must
    share these: if each set up its own, the last one's definitions would replace the
    others' and Windows would refuse their drawing calls.)"""
    global _API
    if _API is not None:
        return _API
    import ctypes
    import types
    from ctypes import wintypes
    u32, g32 = ctypes.windll.user32, ctypes.windll.gdi32

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
    u32.GetDC.restype = wintypes.HDC
    u32.GetDC.argtypes = [wintypes.HWND]
    u32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    g32.CreateCompatibleDC.restype = wintypes.HDC
    g32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    g32.CreateDIBSection.restype = wintypes.HBITMAP
    g32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                     ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
    g32.SelectObject.restype = wintypes.HGDIOBJ
    g32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    g32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    g32.DeleteDC.argtypes = [wintypes.HDC]
    u32.UpdateLayeredWindow.restype = wintypes.BOOL
    u32.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT),
                                        ctypes.POINTER(wintypes.SIZE), wintypes.HDC,
                                        ctypes.POINTER(wintypes.POINT), wintypes.COLORREF,
                                        ctypes.POINTER(BLEND), wintypes.DWORD]
    u32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    u32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
    _API = types.SimpleNamespace(u32=u32, g32=g32, ct=ctypes, wt=wintypes, BLEND=BLEND, BIH=BIH)
    return _API


class GlowBox:
    """One layered window showing the rendered box. Call from the Tk thread."""

    def __init__(self, master, on_fail=None):
        """on_fail(error): called (once) if drawing ever fails, so the overlay can fall back
        to the plain box instead of silently showing nothing."""
        self.on_fail = on_fail
        import tkinter as tk
        self.master = master
        self.win = tk.Toplevel(master)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.geometry("1x1+-32000+-32000")
        self.win.deiconify()
        self.win.update_idletasks()
        self.hwnd = int(self.win.wm_frame(), 16)
        api = _api()
        u32 = api.u32
        self.u32, self.g32, self.ct, self.wt = api.u32, api.g32, api.ct, api.wt
        self.BLEND, self.BIH = api.BLEND, api.BIH
        # layered + click-through + never takes focus + not in the taskbar
        ex = u32.GetWindowLongW(self.hwnd, -20)
        u32.SetWindowLongW(self.hwnd, -20, ex | 0x80000 | 0x20 | 0x80 | 0x8000000 | 0x8)
        self.rect, self.hint, self.alpha, self.kind, self.variant = None, "", 255, None, 0
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
        try:
            blend = self.BLEND(0, 0, int(alpha), 1)
            self.u32.UpdateLayeredWindow(self.hwnd, None, None, None, None, None, 0,
                                         self.ct.byref(blend), 2)
        except Exception as e:
            self._failed(e)

    def _draw(self, grow=0, alpha=255):
        if self.rect is None:
            return
        x1, y1, x2, y2 = self.rect
        try:
            img = render(x2 - x1, y2 - y1, self.hint, grow, kind=self.kind, variant=self.variant)
            if not self._show_image(img, x1 - GLOW, y1 - GLOW, alpha):
                raise OSError("Windows wouldn't show the box window (UpdateLayeredWindow failed)")
        except Exception as e:
            self._failed(e)
            return
        self.alpha = alpha

    def _failed(self, e):
        self._cancel()
        if self.on_fail:
            fail, self.on_fail = self.on_fail, None
            fail(e)

    def _cancel(self):
        for j in self.jobs:
            self.master.after_cancel(j)
        self.jobs = []

    # ---- public ----
    def show(self, rect, hint="", kind=None, variant=0):
        """Pop in: starts a little bigger and transparent, settles onto the target.
        kind: what it is ("button", "text box"...), for the HUD box's shape."""
        self._cancel()
        self.rect, self.hint, self.kind, self.variant = tuple(int(v) for v in rect), hint, kind, variant
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

    def show_picture(self, img, x, y):
        """Show any picture (a drag arrow, a scroll arrow...) at a spot on screen."""
        self._cancel()
        self.rect = None
        try:
            if not self._show_image(img, x, y):
                raise OSError("Windows wouldn't show the picture (UpdateLayeredWindow failed)")
        except Exception as e:
            self._failed(e)

    def hide(self):
        self._cancel()
        self.rect, self.hint = None, ""
        try:
            self._show_image(Image.new("RGBA", (2, 2), (0, 0, 0, 0)), -32000, -32000)
        except Exception as e:
            self._failed(e)

    def _pulse(self):
        """Gentle breathing glow so it stays noticeable without being annoying."""
        if self.rect and time.time() - self.shown_at > 0.3:
            t = time.time() - self.shown_at
            self._set_alpha(205 + 50 * (0.5 + 0.5 * math.cos(t * 2 * math.pi / 1.6)))
        self.master.after(70, self._pulse)

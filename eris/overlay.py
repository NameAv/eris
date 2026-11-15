"""The red box, drawn as four thin solid bars (+ a caption bubble) around the target.

No see-through full-screen window: each piece is a small solid always-on-top
window, which works reliably on every Windows setup. Only call these methods
from the Tk main thread (the app forwards commands to it from its queue).
"""
import sys
import tkinter as tk

from . import config, theme

OFF = -32000  # parked off-screen when hidden (hiding/showing windows can steal focus)


def _click_through(win):
    """Make a small window ignore the mouse and never take focus (Windows)."""
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.windll.user32
    u32.GetParent.restype = wintypes.HWND
    u32.GetParent.argtypes = [wintypes.HWND]
    GWL_EXSTYLE = -20
    WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x80000, 0x20
    WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80, 0x8000000
    LWA_ALPHA = 0x2
    win.update_idletasks()
    handles = set()
    try:
        handles.add(int(win.wm_frame(), 16))
    except Exception:
        pass
    parent = u32.GetParent(win.winfo_id())
    if parent:
        handles.add(parent)
    for hwnd in handles:
        style = u32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        u32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT
                           | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        # A layered window is invisible until this is called - set it fully opaque.
        u32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)


def _piece(master, bg):
    w = tk.Toplevel(master)
    w.overrideredirect(True)
    w.attributes("-topmost", True)
    w.configure(bg=bg)
    w.geometry(f"1x1+{OFF}+{OFF}")
    return w


class Overlay:
    def __init__(self, master):
        self.master = master
        self.bars = [_piece(master, config.BOX_COLOR) for _ in range(4)]
        self.cap = _piece(master, theme.ACCENT)
        self.cap_label = tk.Label(self.cap, text="", bg=theme.CAPTION_BG, fg="white",
                                  font=(theme.FONT, 11, "bold"), padx=10, pady=5,
                                  justify="left", wraplength=420)
        self.cap_label.pack(padx=2, pady=2)
        self.pill = _piece(master, theme.ACCENT)
        self.pill_label = tk.Label(self.pill, text="", bg=theme.CAPTION_BG, fg="white",
                                   font=(theme.FONT, 12, "bold"), padx=14, pady=6)
        self.pill_label.pack(padx=2, pady=2)
        self.pieces = self.bars + [self.cap, self.pill]
        master.update_idletasks()
        for p in self.pieces:
            p.deiconify()
            _click_through(p)
        self.geom = (0, 0, master.winfo_screenwidth(), master.winfo_screenheight())
        self.rect = None
        self.box_timer = None
        self.flash_jobs = []
        master.after(1500, self._keep_on_top)

    def _keep_on_top(self):
        for p in self.pieces:
            p.attributes("-topmost", True)
            p.lift()
        self.master.after(1500, self._keep_on_top)

    @staticmethod
    def _place(win, x, y, w, h):
        win.geometry(f"{max(1, int(w))}x{max(1, int(h))}{int(x):+d}{int(y):+d}")

    def _park(self, win):
        win.geometry(f"1x1+{OFF}+{OFF}")

    # ---- commands (names match app.cmd(...)) ----
    def monitor(self, left, top, w, h):
        self.geom = (left, top, w, h)

    def box(self, x1, y1, x2, y2, caption=""):
        """Screen coords. Replaces any existing box."""
        self.clear_box()
        t = config.BOX_WIDTH
        x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
        self.rect = (x1, y1, x2, y2)
        top, bottom, left, right = self.bars
        self._place(top, x1 - t, y1 - t, x2 - x1 + 2 * t, t)
        self._place(bottom, x1 - t, y2, x2 - x1 + 2 * t, t)
        self._place(left, x1 - t, y1, t, y2 - y1)
        self._place(right, x2, y1, t, y2 - y1)
        for p in self.bars + [self.cap]:
            p.lift()
        self._flash()
        if caption:
            self.caption(caption)
        self.box_timer = self.master.after(int(config.BOX_TIMEOUT * 1000), self.clear_box)

    def _flash(self):
        """Blink a few times so your eye snaps to it."""
        for j in self.flash_jobs:
            self.master.after_cancel(j)
        self.flash_jobs = []
        colours = ["#ffffff", config.BOX_COLOR] * 3
        for i, c in enumerate(colours):
            self.flash_jobs.append(self.master.after(
                90 * (i + 1), lambda c=c: [b.configure(bg=c) for b in self.bars]))

    def caption(self, text):
        if not self.rect:
            return
        text = text if len(text) < 120 else text[:117] + "..."
        self.cap_label.configure(text=text)
        self.cap.update_idletasks()
        w, h = self.cap.winfo_reqwidth(), self.cap.winfo_reqheight()
        x1, y1, x2, y2 = self.rect
        gap = config.BOX_WIDTH + 6
        y = y1 - gap - h if y1 - gap - h > self.geom[1] else y2 + gap
        x = min(max(x1 - config.BOX_WIDTH, self.geom[0] + 4), self.geom[0] + self.geom[2] - w - 4)
        self._place(self.cap, x, y, w, h)

    def clear_box(self):
        if self.box_timer:
            self.master.after_cancel(self.box_timer)
            self.box_timer = None
        for j in self.flash_jobs:
            self.master.after_cancel(j)
        self.flash_jobs = []
        self.rect = None
        for p in self.bars + [self.cap]:
            self._park(p)

    def status(self, text):
        """Little pill bottom-right, so you see Eris react even with her window hidden."""
        if not text:
            self._park(self.pill)
            return
        self.pill_label.configure(text="●  " + text)
        self.pill.update_idletasks()
        w, h = self.pill.winfo_reqwidth(), self.pill.winfo_reqheight()
        left, top, sw, sh = self.geom
        self._place(self.pill, left + sw - w - 24, top + sh - h - 64, w, h)

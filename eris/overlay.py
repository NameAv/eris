"""Transparent, click-through, always-on-top window that draws the red box.

It's a child window of the main app. Only call its methods from the Tk main
thread (the app forwards commands to it from its queue).
"""
import sys
import tkinter as tk

from . import config

KEY = "#010101"  # this colour is see-through


class Overlay:
    def __init__(self, master):
        self.root = tk.Toplevel(master)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=KEY)
        if sys.platform == "win32":
            self.root.attributes("-transparentcolor", KEY)
        self.canvas = tk.Canvas(self.root, bg=KEY, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.geom = None
        self.box_ids = []
        self.box_timer = None
        self.status_ids = []
        self.set_geometry(0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight())
        self.root.update_idletasks()
        self._make_click_through()
        self.root.after(2000, self._keep_on_top)

    def _make_click_through(self):
        if sys.platform != "win32":
            return
        import ctypes
        GWL_EXSTYLE = -20
        WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x80000, 0x20
        WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80, 0x8000000
        u32 = ctypes.windll.user32
        hwnd = u32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        style = u32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        u32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT
                           | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)

    def _keep_on_top(self):
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.root.after(2000, self._keep_on_top)

    def set_geometry(self, left, top, w, h):
        g = (left, top, w, h)
        if g != self.geom:
            self.geom = g
            self.root.geometry(f"{w}x{h}{left:+d}{top:+d}")

    # ---- commands (names match app.cmd(...)) ----
    def monitor(self, left, top, w, h):
        self.set_geometry(left, top, w, h)

    def box(self, x1, y1, x2, y2, caption=""):
        """Screen coords. Replaces any existing box."""
        self.clear_box()
        ox, oy = self.geom[0], self.geom[1]
        x1, y1, x2, y2 = x1 - ox, y1 - oy, x2 - ox, y2 - oy
        self.box_ids.append(self.canvas.create_rectangle(
            x1, y1, x2, y2, outline=config.BOX_COLOR, width=config.BOX_WIDTH))
        if caption:
            self._caption_ids(x1, y1, x2, y2, caption)
        self.box_timer = self.root.after(int(config.BOX_TIMEOUT * 1000), self.clear_box)

    def _caption_ids(self, x1, y1, x2, y2, text):
        c = self.canvas
        text = text if len(text) < 90 else text[:87] + "..."
        ty = y1 - 16 if y1 > 40 else y2 + 16
        t = c.create_text(x1 + 6, ty, text=text, anchor="w", fill="white",
                          font=("Segoe UI", 11, "bold"))
        bx = c.bbox(t)
        bg = c.create_rectangle(bx[0] - 6, bx[1] - 3, bx[2] + 6, bx[3] + 3,
                                fill="#2a0a0a", outline=config.BOX_COLOR)
        c.tag_raise(t)
        self.box_ids += [bg, t]

    def caption(self, text):
        if not self.box_ids:
            return
        x1, y1, x2, y2 = self.canvas.coords(self.box_ids[0])
        for i in self.box_ids[1:]:
            self.canvas.delete(i)
        self.box_ids = self.box_ids[:1]
        self._caption_ids(x1, y1, x2, y2, text)

    def clear_box(self):
        if self.box_timer:
            self.root.after_cancel(self.box_timer)
            self.box_timer = None
        for i in self.box_ids:
            self.canvas.delete(i)
        self.box_ids = []

    def status(self, text):
        """Little pill bottom-right, so you see Eris react even with her window hidden."""
        c = self.canvas
        for i in self.status_ids:
            c.delete(i)
        self.status_ids = []
        if not text:
            return
        w, h = self.geom[2], self.geom[3]
        t = c.create_text(w - 24, h - 70, text=text, anchor="e", fill="white",
                          font=("Segoe UI", 12, "bold"))
        bx = c.bbox(t)
        bg = c.create_rectangle(bx[0] - 14, bx[1] - 8, bx[2] + 14, bx[3] + 8,
                                fill="#1b1b1f", outline=config.BOX_COLOR, width=2)
        c.tag_raise(t)
        self.status_ids = [bg, t]

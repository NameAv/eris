"""The red box: the rounded glowing one (glowbox.py), or plain bars as a fallback.

No see-through full-screen window: each piece is a small solid always-on-top
window, which works reliably on every Windows setup. Only call these methods
from the Tk main thread (the app forwards commands to it from its queue).
"""
import sys
import tkinter as tk

from . import config, theme

OFF = -32000  # parked off-screen when hidden (hiding/showing windows can steal focus)


def _click_through(win):
    """Make a small window ignore the mouse and never take focus (Windows).
    Returns its window handles so we can keep it on top without activating it."""
    if sys.platform != "win32":
        return []
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
    return list(handles)


def _hide_from_capture(handles, hidden):
    """Keep windows out of every screenshot and recording (Windows 10 2004 and later), so
    her own screenshots and the box tracker never see the box. True if Windows agreed."""
    if sys.platform != "win32" or not handles:
        return False
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.windll.user32
    WDA_NONE, WDA_EXCLUDEFROMCAPTURE = 0x0, 0x11
    took = [bool(u32.SetWindowDisplayAffinity(wintypes.HWND(h), WDA_EXCLUDEFROMCAPTURE if hidden else WDA_NONE))
            for h in handles]
    return hidden and any(took)


def _raise(win, handles):
    """Bring a piece to the very top WITHOUT taking keyboard focus from your app."""
    if sys.platform != "win32" or not handles:
        win.lift()
        return
    import ctypes
    HWND_TOPMOST = -1
    SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x1, 0x2, 0x10
    for hwnd in handles:
        ctypes.windll.user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                          SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)


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
        # "type this" hint, shown inside the box (e.g. in the search bar)
        self.cap = _piece(master, theme.ACCENT)
        self.cap_label = tk.Label(self.cap, text="", bg=theme.ACCENT, fg="white",
                                  font=(theme.FONT, 11, "bold"), padx=9, pady=2)
        self.cap_label.pack()
        self.pill = _piece(master, theme.ACCENT)
        self.pill_label = tk.Label(self.pill, text="", bg=theme.CAPTION_BG, fg="white",
                                   font=(theme.FONT, 12, "bold"), padx=14, pady=6)
        self.pill_label.pack(padx=2, pady=2)
        # plain stand-ins for the extras (drop box, scroll / key note) when there's no glow
        self.drop_bars = [_piece(master, config.BOX_COLOR) for _ in range(4)]
        self.note = _piece(master, theme.ACCENT)
        self.note_label = tk.Label(self.note, text="", bg=theme.ACCENT, fg="white",
                                   font=(theme.FONT, 14, "bold"), padx=14, pady=6)
        self.note_label.pack()
        self.drop_rect = None
        self.extras_timer = None
        self.variant = -1            # each new box gets the next version of its HUD shape
        self.pieces = self.bars + [self.cap, self.pill] + self.drop_bars + [self.note]
        master.update_idletasks()
        self.handles = {}
        for p in self.pieces:
            p.deiconify()
            self.handles[p] = _click_through(p)
        self.geom = (0, 0, master.winfo_screenwidth(), master.winfo_screenheight())
        self.rect = None
        self.hint = ""
        self.pill_shown = False
        self.box_timer = None
        self.flash_jobs = []
        self.glow = self.extra = None
        if sys.platform == "win32" and config.BOX_STYLE != "bars":
            try:
                from .glowbox import GlowBox
                self.glow = GlowBox(master)
                self.extra = GlowBox(master)   # drag arrows, scroll and key notes
            except Exception:
                self.glow = self.extra = None   # plain bars instead
        self.hidden_from_capture = False
        self.apply_capture()
        master.after(1500, self._keep_on_top)

    def apply_capture(self):
        """Hide the box from screenshots, unless you want it in your recordings."""
        groups = [self.handles.get(p) for p in self.pieces] + [[g.hwnd] for g in (self.glow, self.extra) if g]
        hide = not config.BOX_IN_RECORDINGS
        results = [_hide_from_capture(h, hide) for h in groups if h]
        self.hidden_from_capture = bool(results) and all(results)

    def _keep_on_top(self):
        if self.glow and self.rect:
            _raise(self.glow.win, [self.glow.hwnd])
        visible = list(self.bars) if self.rect and not self.glow else []
        if self.rect and self.hint:
            visible.append(self.cap)
        if self.pill_shown:
            visible.append(self.pill)
        for p in visible:
            _raise(p, self.handles.get(p))
        self.master.after(1500, self._keep_on_top)

    @staticmethod
    def _place(win, x, y, w, h):
        win.geometry(f"{max(1, int(w))}x{max(1, int(h))}{int(x):+d}{int(y):+d}")

    def _park(self, win):
        win.geometry(f"1x1+{OFF}+{OFF}")

    def _draw_bars(self):
        t = config.BOX_WIDTH
        x1, y1, x2, y2 = self.rect
        top, bottom, left, right = self.bars
        self._place(top, x1 - t, y1 - t, x2 - x1 + 2 * t, t)
        self._place(bottom, x1 - t, y2, x2 - x1 + 2 * t, t)
        self._place(left, x1 - t, y1, t, y2 - y1)
        self._place(right, x2, y1, t, y2 - y1)

    # ---- commands (names match app.cmd(...)) ----
    def monitor(self, left, top, w, h):
        self.geom = (left, top, w, h)

    def box(self, x1, y1, x2, y2, caption="", kind=None):
        """Screen coords. Replaces any existing box (and its type hint). kind: what it
        points at ("button", "text box"...), when known: the HUD box's shape suits it."""
        self.clear_box()
        self.rect = (int(x1), int(y1), int(x2), int(y2))
        self.variant = (self.variant + 1) % 3
        if self.glow:
            self.glow.show(self.rect, caption, kind, self.variant)
            _raise(self.glow.win, [self.glow.hwnd])
        else:
            self._draw_bars()
            for p in self.bars:
                _raise(p, self.handles.get(p))
            self._flash()
            if caption:
                self.type_hint(caption, prefix="")
        self.box_timer = self.master.after(int(config.BOX_TIMEOUT * 1000), self.clear_box)

    def move_box(self, x1, y1, x2, y2):
        """Snap the current box onto a more precise spot (no flashing, same timer)."""
        if not self.rect:
            return
        self.rect = (int(x1), int(y1), int(x2), int(y2))
        self._move_extras()
        if self.glow:
            self.glow.move(self.rect)
            return
        self._draw_bars()
        if self.hint:
            self._place_hint()

    def _move_extras(self):
        if self.drop_rect:
            self.drop(*self.drop_rect)

    # ---- extras: where to drop, which way to scroll, which key to press ----
    def drop(self, x1, y1, x2, y2):
        """A drag: a dashed box where to drop the boxed thing, with an arrow to it."""
        if not self.rect:
            return
        self.drop_rect = (int(x1), int(y1), int(x2), int(y2))
        if self.extra:
            from .glowbox import render_drop
            img, x, y = render_drop(self.rect, self.drop_rect, self.variant + 1)   # the target: another version
            self.extra.show_picture(img, x, y)
            return
        t = max(2, config.BOX_WIDTH - 1)
        a, b, c, d = self.drop_rect
        for bar, geo in zip(self.drop_bars, [(a - t, b - t, c - a + 2 * t, t), (a - t, d, c - a + 2 * t, t),
                                             (a - t, b, t, d - b), (c, b, t, d - b)]):
            self._place(bar, *geo)
            _raise(bar, self.handles.get(bar))

    def scroll_hint(self, way, left, top, w, h):
        self._show_note(f"scroll {way}", way, (left, top, w, h))

    def badge(self, text, left, top, w, h):
        self._show_note(text, None, (left, top, w, h))

    def _show_note(self, text, way, area):
        """A big note at the edge of the app's window (the side to scroll toward)."""
        left, top, w, h = area
        if self.extra:
            from .glowbox import render_note
            img = render_note(text, way)
            nw, nh = img.size
        else:
            self.note_label.configure(text={"down": "▼  ", "up": "▲  ", "left": "◀  ", "right": "▶  "}.get(way, "") + text)
            self.note.update_idletasks()
            nw, nh = self.note_label.winfo_reqwidth(), self.note_label.winfo_reqheight()
        spots = {"down": (left + (w - nw) // 2, top + h - nh - 40), "up": (left + (w - nw) // 2, top + 70),
                 "left": (left + 30, top + (h - nh) // 2), "right": (left + w - nw - 30, top + (h - nh) // 2)}
        x, y = spots.get(way, (left + (w - nw) // 2, top + 90))
        if self.extra:
            self.extra.show_picture(img, x, y)
        else:
            self._place(self.note, x, y, nw, nh)
            _raise(self.note, self.handles.get(self.note))
        if self.extras_timer:
            self.master.after_cancel(self.extras_timer)
        self.extras_timer = self.master.after(int(config.BOX_TIMEOUT * 1000), self._clear_extras)

    def _clear_extras(self):
        if self.extras_timer:
            self.master.after_cancel(self.extras_timer)
            self.extras_timer = None
        self.drop_rect = None
        if self.extra:
            self.extra.hide()
        for p in self.drop_bars + [self.note]:
            self._park(p)

    def _flash(self):
        """Blink a few times so your eye snaps to it."""
        for j in self.flash_jobs:
            self.master.after_cancel(j)
        self.flash_jobs = []
        colours = ["#ffffff", config.BOX_COLOR] * 3
        for i, c in enumerate(colours):
            self.flash_jobs.append(self.master.after(
                90 * (i + 1), lambda c=c: [b.configure(bg=c) for b in self.bars]))

    def type_hint(self, text, prefix="type:  "):
        """Show what to type inside the box (right end of a search bar), or just
        under it if the box is too small."""
        if not self.rect:
            return
        text = text if len(text) < 60 else text[:57] + "..."
        self.hint = prefix + text
        if self.glow:
            self.glow.set_hint(self.hint)
            return
        self.cap_label.configure(text=self.hint)
        self._place_hint()
        _raise(self.cap, self.handles.get(self.cap))

    def _place_hint(self):
        self.cap.update_idletasks()
        w, h = self.cap_label.winfo_reqwidth(), self.cap_label.winfo_reqheight()
        x1, y1, x2, y2 = self.rect
        if x2 - x1 >= w + 90 and y2 - y1 >= h + 2:      # fits inside: right end of the box
            x, y = x2 - w - 6, y1 + (y2 - y1 - h) // 2
        else:                                            # too small: just below it
            x, y = x1, y2 + config.BOX_WIDTH + 4
        self._place(self.cap, x, y, w, h)

    def clear_box(self):
        if self.box_timer:
            self.master.after_cancel(self.box_timer)
            self.box_timer = None
        for j in self.flash_jobs:
            self.master.after_cancel(j)
        self.flash_jobs = []
        self.rect = None
        self.hint = ""
        self._clear_extras()
        if self.glow:
            self.glow.hide()
        for p in self.bars + [self.cap]:
            self._park(p)

    def status(self, text):
        """Little pill bottom-right, so you see Eris react even with her window hidden."""
        self.pill_shown = bool(text)
        if not text:
            self._park(self.pill)
            return
        self.pill_label.configure(text="●  " + text)
        self.pill.update_idletasks()
        w, h = self.pill.winfo_reqwidth(), self.pill.winfo_reqheight()
        left, top, sw, sh = self.geom
        self._place(self.pill, left + sw - w - 24, top + sh - h - 64, w, h)
        _raise(self.pill, self.handles.get(self.pill))

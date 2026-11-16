"""Watches your screen while Eris is waiting for you, and asks her to take a
fresh look when something changes (you typed, a page loaded, you clicked
something else...).

It only compares tiny greyscale thumbnails on your PC, so watching itself is
free. The AI is only asked when the screen actually changed and has settled.
Eris's own windows, the red box and its type hint are ignored.

The box's own spot is checked more often (a small grab, a few times a second): when you
scroll or move the window, the box follows its button (tracker.py) and that doesn't
count as "something happened". If the button is gone, she looks again.
"""
import sys
import threading
import time

import numpy as np
from PIL import Image

from . import config, privacy, screen, tracker

TW, TH = 320, 180          # thumbnail size
PIXEL_DIFF = 22            # how different a pixel must be to count (0-255)
CHANGED = 0.0025           # share of pixels that must differ from the start = "something happened"
STILL = 0.0008             # share of pixels changing between looks = "it has settled"
TICK = 0.5                 # seconds between looks at the whole screen
FAST = 0.15                # seconds between looks at the box's own spot
REACH_X, REACH_Y = 250, 450   # how far the quick look searches for a button that moved
MIN_GAP = 4.0              # never ask the AI more often than this
MAX_LOOKS_PER_STEP = 6     # then go quiet until you click the box / press F9


def _cursor_in(box):
    """Is the mouse over the box? (Windows; elsewhere: no.)"""
    if not box or sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes
    p = wintypes.POINT()
    if not ctypes.windll.user32.GetCursorPos(ctypes.byref(p)):
        return False
    return box[0] <= p.x <= box[2] and box[1] <= p.y <= box[3]


def changed(a, b):
    """Share of the screen that differs between two thumbnails (0..1)."""
    return float(np.mean(np.abs(a - b) > PIXEL_DIFF))


class Watcher:
    def __init__(self, eris):
        self.eris = eris
        self.lock = threading.Lock()
        self.last_fire = 0.0
        self.keep_streak = 0
        self.private_at, self.private = 0.0, False
        self.rebase()
        threading.Thread(target=self._loop, daemon=True).start()

    def rebase(self, delay=0.5, kept=False):
        """Start comparing against the screen as it looks `delay` seconds from now.
        (The box, its type hint and Eris's own windows are masked out, so a short
        delay is enough.) kept=True: the last look found nothing new, so be more
        patient with a screen that never stops changing (a video, Unity's Play mode)."""
        with self.lock:
            self.keep_streak = self.keep_streak + 1 if kept else 0
            self.base = None
            self.prev = None
            self.base_after = time.time() + delay
            self.changed_at = None
            self.still_since = None
            self.nudged_at = None

    def nudge(self):
        """You pressed Enter: have a look shortly even if little changed."""
        with self.lock:
            self.nudged_at = time.time()

    def _masks(self, mon, box=True):
        """Screen areas to ignore: Eris's windows, the box + type hint, the status pill."""
        left, top, w, h = mon
        rects = list(self.eris.ui.window_rects())
        if box and self.eris.box:
            x1, y1, x2, y2 = self.eris.box
            rects.append((x1 - 30, y1 - 90, max(x2, x1 + 520) + 30, y2 + 90))
        rects.append((left + w - 420, top + h - 170, left + w, top + h))
        out = []
        for x1, y1, x2, y2 in rects:
            a = int((x1 - left) * TW / w); b = int((y1 - top) * TH / h)
            c = int((x2 - left) * TW / w) + 1; d = int((y2 - top) * TH / h) + 1
            out.append((max(0, a), max(0, b), min(TW, c), min(TH, d)))
        return out

    @staticmethod
    def _grab(sct, left, top, w, h):
        raw = sct.grab({"left": int(left), "top": int(top), "width": int(w), "height": int(h)})
        return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX").convert("L")

    def look(self):
        """A thumbnail of the whole screen right now, for a quick before/after check of a
        step (free: nothing leaves the PC). Eris's own windows are blanked, and her box
        too if screenshots can see it. None if the screen can't be read."""
        mon = self.eris.mon
        if not mon:
            return None
        try:
            with screen.new_sct() as sct:
                img = self._grab(sct, *mon)
        except Exception:
            return None
        arr = np.asarray(img.resize((TW, TH), Image.BILINEAR), dtype=np.int16).copy()
        box_seen = getattr(self.eris.ui, "box_in_screenshots", lambda: True)()
        for a, b, c, d in self._masks(mon, box=box_seen):
            arr[b:d, a:c] = 0
        return arr

    def _thumb(self, img, mon):
        arr = np.asarray(img.resize((TW, TH), Image.BILINEAR), dtype=np.int16).copy()
        for a, b, c, d in self._masks(mon):
            arr[b:d, a:c] = 0
        return arr

    # ---- following the box's button ----
    def _tracker(self):
        e, t = self.eris, self.eris.track
        if config.TRACK and t and e.box and t.box == tuple(int(v) for v in e.box):
            return t
        return None

    def _follow(self, t, img, ox, oy):
        """Look for the box's button in img. Returns True if it's gone."""
        result, box = t.find(tracker.grey(img) if isinstance(img, Image.Image) else img, ox, oy)
        if result == tracker.MOVED:
            self.eris.follow(box)
            self.rebase(delay=0.25)          # scrolling isn't "doing the step"
            return False
        return result == tracker.GONE and not _cursor_in(box)   # a hover effect isn't "gone"

    def _quick_look(self, sct):
        """A small grab around the box. True: something changed there and the button
        wasn't found nearby, so check the whole screen now."""
        t = self._tracker()
        if not t:
            return False
        left, top, w, h = self.eris.mon
        x1, y1, x2, y2 = t.box
        rx1, ry1 = max(left, x1 - REACH_X), max(top, y1 - REACH_Y)
        rx2, ry2 = min(left + w, x2 + REACH_X), min(top + h, y2 + REACH_Y)
        if rx2 - rx1 < 16 or ry2 - ry1 < 16:
            return False
        return self._follow(t, self._grab(sct, rx1, ry1, rx2 - rx1, ry2 - ry1), rx1, ry1)

    def _ready(self):
        e = self.eris
        return (config.WATCH and e.active and e.waiting and not e.busy and e.mon
                and e.auto_looks < MAX_LOOKS_PER_STEP
                and not e.voice.busy())          # let her finish talking before she looks again

    def _private(self):
        """Typing a password / using a private app? Asked at most twice a second (it's
        a question to Windows); the quick looks in between use the last answer."""
        now = time.time()
        if now - self.private_at >= TICK:
            self.private_at, self.private = now, bool(privacy.should_look_away())
        return self.private

    def _loop(self):
        sct, last_full = None, 0.0
        while True:
            time.sleep(FAST)
            try:
                if not self._ready() or self._private():
                    continue
                sct = sct or screen.new_sct()
                urgent = self._quick_look(sct)
                now = time.time()
                if now < self.base_after or (not urgent and now - last_full < TICK):
                    continue
                last_full = now
                mon = self.eris.mon
                img = self._grab(sct, *mon)
                t = self._tracker()
                gone = bool(t) and self._follow(t, img, mon[0], mon[1])
                if self.base_after > time.time():     # it just followed a scroll
                    continue
                if self._step(self._thumb(img, mon), gone=gone):
                    self.eris.auto_look()
            except Exception as ex:   # never let watching crash Eris
                self.eris.ui.log("debug", f"watcher: {ex}")
                sct = None
                time.sleep(2)

    def _step(self, frame, now=None, gone=False):
        """Feed one thumbnail. Returns True when it's time for Eris to look.
        gone: the box's button has disappeared (that counts as a change even though
        the box's area is masked out)."""
        now = now or time.time()
        with self.lock:
            if self.base is None:
                self.base = self.prev = frame
                return False
            different = gone or changed(frame, self.base) > CHANGED
            still = changed(frame, self.prev) <= STILL
            self.prev = frame
            if different and self.changed_at is None:
                self.changed_at = now
            if not still:
                self.still_since = None
            elif self.still_since is None:
                self.still_since = now
            settle = 0.8 if self.eris.waiting == "click" else 1.4
            settled = (self.changed_at is not None and self.still_since is not None
                       and now - self.still_since >= settle)
            patience = 8 * 2 ** min(self.keep_streak, 4)   # 8s, 16s, 32s... for busy screens
            busy_screen = self.changed_at is not None and now - self.changed_at > patience
            nudged = self.nudged_at is not None and now - self.nudged_at > 0.8
            if (settled or busy_screen or nudged) and now - self.last_fire >= MIN_GAP:
                self.last_fire = now
                self.base, self.changed_at, self.still_since, self.nudged_at = frame, None, None, None
                return True
            return False

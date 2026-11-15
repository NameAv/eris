"""Watches your screen while Eris is waiting for you, and asks her to take a
fresh look when something changes (you typed, a page loaded, you clicked
something else...).

It only compares tiny greyscale thumbnails on your PC, so watching itself is
free. The AI is only asked when the screen actually changed and has settled.
Eris's own windows, the red box and its caption are ignored.
"""
import threading
import time

import numpy as np
from PIL import Image

from . import config, privacy, screen

TW, TH = 320, 180          # thumbnail size
PIXEL_DIFF = 22            # how different a pixel must be to count (0-255)
CHANGED = 0.0025           # share of pixels that must differ from the start = "something happened"
STILL = 0.0008             # share of pixels changing between looks = "it has settled"
TICK = 0.5                 # seconds between looks
MIN_GAP = 4.0              # never ask the AI more often than this
MAX_LOOKS_PER_STEP = 6     # then go quiet until you click the box / press F9


def _diff(a, b):
    return float(np.mean(np.abs(a - b) > PIXEL_DIFF))


class Watcher:
    def __init__(self, eris):
        self.eris = eris
        self.lock = threading.Lock()
        self.last_fire = 0.0
        self.keep_streak = 0
        self.rebase()
        threading.Thread(target=self._loop, daemon=True).start()

    def rebase(self, delay=0.5, kept=False):
        """Start comparing against the screen as it looks `delay` seconds from now.
        (The box, its caption and Eris's own windows are masked out, so a short
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

    def _masks(self, mon):
        """Screen areas to ignore: Eris's windows, the box + caption, the status pill."""
        left, top, w, h = mon
        rects = list(self.eris.ui.window_rects())
        if self.eris.box:
            x1, y1, x2, y2 = self.eris.box
            rects.append((x1 - 30, y1 - 90, max(x2, x1 + 520) + 30, y2 + 90))
        rects.append((left + w - 420, top + h - 170, left + w, top + h))
        out = []
        for x1, y1, x2, y2 in rects:
            a = int((x1 - left) * TW / w); b = int((y1 - top) * TH / h)
            c = int((x2 - left) * TW / w) + 1; d = int((y2 - top) * TH / h) + 1
            out.append((max(0, a), max(0, b), min(TW, c), min(TH, d)))
        return out

    def _thumb(self, sct, mon):
        left, top, w, h = mon
        raw = sct.grab({"left": left, "top": top, "width": w, "height": h})
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX").convert("L")
        arr = np.asarray(img.resize((TW, TH), Image.BILINEAR), dtype=np.int16).copy()
        for a, b, c, d in self._masks(mon):
            arr[b:d, a:c] = 0
        return arr

    def _ready(self):
        e = self.eris
        return (config.WATCH and e.active and e.waiting and not e.busy and e.mon
                and e.auto_looks < MAX_LOOKS_PER_STEP and not privacy.should_look_away())

    def _loop(self):
        sct = None
        while True:
            time.sleep(TICK)
            try:
                if not self._ready() or time.time() < self.base_after:
                    continue
                sct = sct or screen.new_sct()
                frame = self._thumb(sct, self.eris.mon)
                if self._step(frame):
                    self.eris.auto_look()
            except Exception as ex:   # never let watching crash Eris
                self.eris.ui.log("debug", f"watcher: {ex}")
                sct = None
                time.sleep(2)

    def _step(self, frame, now=None):
        """Feed one thumbnail. Returns True when it's time for Eris to look."""
        now = now or time.time()
        with self.lock:
            if self.base is None:
                self.base = self.prev = frame
                return False
            changed = _diff(frame, self.base) > CHANGED
            still = _diff(frame, self.prev) <= STILL
            self.prev = frame
            if changed and self.changed_at is None:
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

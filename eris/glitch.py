"""The Neon look's living banner: streaks of red light drifting across the top of the
window (far ones slow, near ones fast) and, every few seconds or when Eris starts
talking, a short glitch: slices jump sideways, the red splits, a bright line tears
through. Each frame is a few small numpy operations, repainted into one image."""
import random
import time

import numpy as np

from . import config, theme

FPS = 24
FAR_SPEED, NEAR_SPEED = 14, 55        # px per second
GLITCH_EVERY = (3.0, 9.0)             # seconds between glitches
GLITCH_LONG = (0.12, 0.35)            # how long one lasts


class Streaks:
    """Banner frames (no window needed, so it can be tested anywhere)."""

    def __init__(self, w, h, seed=7):
        self.w, self.h = w, h
        self.far = np.asarray(theme.streaks(w, h, seed, density=0.7), dtype=np.float32) * 0.55
        self.near = np.asarray(theme.streaks(w, h, seed + 1, density=0.6), dtype=np.float32)
        self.rnd = random.Random(seed)
        self.glitch_until = 0.0
        self.next_glitch = time.time() + self.rnd.uniform(*GLITCH_EVERY)

    def burst(self, now=None, length=0.3):
        """Glitch now (e.g. when Eris starts talking)."""
        now = now or time.time()
        self.glitch_until = max(self.glitch_until, now + length)

    def frame(self, now=None):
        now = now or time.time()
        far = np.roll(self.far, -int(now * FAR_SPEED) % self.w, axis=1)
        near = np.roll(self.near, -int(now * NEAR_SPEED) % self.w, axis=1)
        img = np.maximum(far, near)
        if config.GLITCH:
            if now >= self.next_glitch:
                self.burst(now, self.rnd.uniform(*GLITCH_LONG))
                self.next_glitch = now + self.rnd.uniform(*GLITCH_EVERY)
            if now < self.glitch_until:
                img = self._glitch(img)
        return np.clip(img, 0, 255).astype(np.uint8)

    def _glitch(self, img):
        rnd, h, w = self.rnd, self.h, self.w
        img = img.copy()
        for _ in range(rnd.randint(2, 5)):                       # slices jump sideways
            y1 = rnd.randrange(0, h)
            y2 = min(h, y1 + rnd.randint(2, max(3, h // 3)))
            img[y1:y2] = np.roll(img[y1:y2], rnd.randint(-w // 8, w // 8), axis=1)
        split = rnd.randint(3, 9)                                # the red splits off
        img[..., 0] = np.maximum(img[..., 0], np.roll(img[..., 0], split, axis=1) * 0.9)
        img[..., 1:] = np.roll(img[..., 1:], -split, axis=1)
        y = rnd.randrange(0, h)                                  # a bright tear
        img[y:y + 1] = np.maximum(img[y:y + 1], [255, 120, 110])
        for _ in range(rnd.randint(1, 4)):                       # blocks of hot red / black
            bx, by = rnd.randrange(0, w), rnd.randrange(0, h)
            bw, bh = rnd.randint(8, 50), rnd.randint(2, 6)
            img[by:by + bh, bx:bx + bw] = [255, 30, 45] if rnd.random() < 0.6 else 0
        return img * rnd.uniform(1.0, 1.35)                      # a flash


class Banner:
    """The banner in the window: a canvas showing one image, repainted in place."""

    def __init__(self, master, height=44):
        import tkinter as tk
        import customtkinter as ctk
        self.master = master
        try:
            self.scale = ctk.ScalingTracker.get_window_scaling(master.winfo_toplevel())
        except Exception:
            self.scale = 1.0
        self.h = max(8, int(height * self.scale))
        self.canvas = tk.Canvas(master, height=self.h, bg=theme.BG, highlightthickness=0, bd=0)
        self.streaks = None
        self.photo = None
        self.item = None
        self.frames = 0
        self.canvas.bind("<Configure>", self._resized)

    def pack(self, **kw):
        self.canvas.pack(**kw)
        self.canvas.after(1000 // FPS, self._tick)
        return self

    def burst(self):
        if self.streaks:
            self.streaks.burst()

    def _resized(self, event):
        w = int(event.width)
        if w > 16 and (self.streaks is None or abs(w - self.streaks.w) > 8):
            self.streaks = Streaks(w, self.h)
            self.photo = None

    def _tick(self):
        try:
            if self.streaks and self.canvas.winfo_viewable():
                from PIL import Image, ImageTk
                img = Image.fromarray(self.streaks.frame())
                if self.photo is None or self.photo.width() != img.width:
                    self.photo = ImageTk.PhotoImage(img)
                    if self.item is None:
                        self.item = self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
                    else:
                        self.canvas.itemconfigure(self.item, image=self.photo)
                else:
                    self.photo.paste(img)
                self.frames += 1
        except Exception:
            return                     # the window is closing: stop quietly
        self.canvas.after(1000 // FPS, self._tick)

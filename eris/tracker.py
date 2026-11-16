"""Keeps the box on its button. Scroll the page or move the window and the box slides
along with the thing she pointed at: found by its look alone, in a few milliseconds,
without asking the AI again.

The same idea fast game trackers use: find the target once (slow, the AI), then follow
it cheaply on every frame.
1. When she points at something, remember a small greyscale picture of it.
2. Each look, check the box's own spot first. Unchanged? Done.
3. Otherwise search for the picture with a match score that ignores brightness changes
   (so a hover highlight still matches): on a shrunk copy of the screen first, then
   pixel-exact around the best spot. Several equally good matches (list rows that look
   alike)? The one nearest to where it was.
4. Not found at all: it's gone (you clicked it, or the page changed), so she looks again.
"""
import numpy as np

from . import config

INK = 40            # grey difference (0-255) that makes a pixel part of the text/edges
SAME = 0.03         # share of those that may change and still be "unchanged" (a caret)
MATCH = 0.9         # match score (up to 1.0) needed to say "that's it"
MIN_INK = 0.03      # a target needs this much detail (text, edges, icons) to be followed
COARSE = 0.5        # ...on the shrunk copy (thin text blurs there; the exact check decides)
CANDIDATES = 12     # spots compared pixel-exact before choosing
CLOSE = 0.01        # pixel-exact matches this close to the best count as equally good
INSET = 3           # px kept clear inside the box's own outline and glow
MAX_W, MAX_H = 320, 120   # a bigger target is recognised by its middle (keeps it quick)

SAME_SPOT, MOVED, GONE = "same", "moved", "gone"
AMBIGUOUS = "ambiguous"     # several places match equally well: don't guess


def grey(img):
    """PIL image -> greyscale float array."""
    return np.asarray(img.convert("L"), dtype=np.float32)


def _crop(img, x, y, w, h):
    if x < 0 or y < 0 or y + h > img.shape[0] or x + w > img.shape[1]:
        return None
    return img[y:y + h, x:x + w]


def _shrink(a, f):
    if f == 1:
        return a
    h, w = a.shape[0] // f * f, a.shape[1] // f * f
    return a[:h, :w].reshape(h // f, f, w // f, f).mean(axis=(1, 3))


def _match_map(img, pic):
    """Match score of `pic` at every position in `img` (normalised cross-correlation,
    worked out for the whole image at once with FFTs and running sums)."""
    H, W = img.shape
    h, w = pic.shape
    if h > H or w > W:
        return None
    img = img.astype(np.float64)
    pz = pic - pic.mean()
    pn = np.sqrt((pz * pz).sum())
    if pn < 1e-3:
        return None
    spectrum = np.fft.rfft2(img) * np.fft.rfft2(pz[::-1, ::-1], s=img.shape)
    num = np.fft.irfft2(spectrum, s=img.shape)[h - 1:, w - 1:]
    s1 = np.zeros((H + 1, W + 1))
    s2 = np.zeros((H + 1, W + 1))
    s1[1:, 1:] = img.cumsum(0).cumsum(1)
    s2[1:, 1:] = (img * img).cumsum(0).cumsum(1)
    win = lambda s: s[h:, w:] - s[:-h, w:] - s[h:, :-w] + s[:-h, :-w]
    n = h * w
    a, b = win(s1), win(s2)
    var = np.maximum(b - a * a / n, 0)
    out = np.zeros_like(num)
    textured = var > n * 4.0            # flat spots (blank page) can't match anything
    out[textured] = num[textured] / (np.sqrt(var[textured]) * pn)
    return out


class Tracker:
    def __init__(self, picture, box, offset):
        self.picture = picture
        self.box = box              # the box on screen (screen coords, padding included)
        self.offset = offset        # where the picture sits inside the box
        self.seen = picture         # how the spot looked last time (e.g. hovered)
        self.ink = int((np.abs(picture - np.median(picture)) > INK).sum())
        self._pz = picture - picture.mean()
        self._pn = float(np.sqrt((self._pz * self._pz).sum()))

    @classmethod
    def make(cls, full, left, top, box, hint="", box_visible=False):
        """A tracker for `box`, from the screenshot `full` (a PIL image of the monitor at
        left/top). None if the thing has no shape to recognise (an empty field, a
        blacked-out private field). box_visible: screenshots can see the box, so keep
        clear of the "type:" pill drawn in its right end."""
        if full is None or not box:
            box = None
        else:
            box = tuple(int(v) for v in box)
        if not box:
            return None
        inset = config.BOX_PADDING + INSET
        x1, y1, x2, y2 = box[0] + inset, box[1] + inset, box[2] - inset, box[3] - inset
        if hint and box_visible and x2 - x1 > 160:
            x2 -= min(int((x2 - x1) * 0.6), len(hint) * 8 + 30)
        if x2 - x1 > MAX_W:
            x1 += (x2 - x1 - MAX_W) // 2
            x2 = x1 + MAX_W
        if y2 - y1 > MAX_H:
            y1 += (y2 - y1 - MAX_H) // 2
            y2 = y1 + MAX_H
        cx1, cy1 = x1 - left, y1 - top
        if x2 - x1 < 8 or y2 - y1 < 6 or cx1 < 0 or cy1 < 0 or x2 - left > full.width or y2 - top > full.height:
            return None
        pic = grey(full.crop((cx1, cy1, x2 - left, y2 - top)))
        detail = int((np.abs(pic - np.median(pic)) > INK).sum())
        if pic.std() < 10 or detail < max(30, MIN_INK * pic.size):
            return None          # an empty patch: it would "match" lookalike empty patches
        return cls(pic, box, (x1 - box[0], y1 - box[1]))

    def _score(self, patch):
        pz = patch - patch.mean()
        d = float(np.sqrt((pz * pz).sum())) * self._pn
        return float((pz * self._pz).sum()) / d if d > 1e-3 else 0.0

    def find(self, img, ox, oy):
        """img: greyscale array of (part of) the screen, its top-left at screen ox, oy.
        Returns (SAME_SPOT | MOVED | GONE, box)."""
        h, w = self.picture.shape
        px, py = self.box[0] + self.offset[0] - ox, self.box[1] + self.offset[1] - oy
        here = _crop(img, px, py, w, h)
        if here is not None and (np.abs(here - self.seen) > INK).sum() <= max(3, SAME * self.ink):
            return SAME_SPOT, self.box
        spot = self._search(img, px, py)
        if spot is AMBIGUOUS:
            return SAME_SPOT, self.box      # leave the box where it is rather than guess
        if spot is None:
            return GONE, self.box
        dx, dy = spot[0] - px, spot[1] - py
        self.seen = _crop(img, spot[0], spot[1], w, h)
        if dx == 0 and dy == 0:
            return SAME_SPOT, self.box
        x1, y1, x2, y2 = self.box
        self.box = (x1 + dx, y1 + dy, x2 + dx, y2 + dy)
        return MOVED, self.box

    def _search(self, img, near_x, near_y):
        """Best matching spot: the top few on a shrunk copy, compared pixel-exact. Of
        matches equally good, the one nearest to where it was."""
        h, w = self.picture.shape
        f = int(np.clip(min(h, w) // 6, 1, 6))      # shrink, but keep the picture recognisable
        scores = _match_map(_shrink(img, f), _shrink(self.picture, f))
        if scores is None or scores.size == 0 or scores.max() < COARSE:
            return None
        found = []
        for cx, cy in _peaks(scores, max(1, w // f // 2), max(1, h // f // 2)):
            best, spot = self._best_near(img, cx * f, cy * f, f + 1, max(1, f // 2))
            if spot and f > 1:
                best, spot = self._best_near(img, spot[0], spot[1], max(1, f // 2), 1)
            if spot and best >= MATCH:
                found.append((best, spot))
        if not found:
            return None
        top = max(b for b, _ in found)
        near = [sp for b, sp in found if b >= top - CLOSE]
        if len(near) > 1:          # several equally good: only follow if one is right by the old spot
            close = [sp for sp in near if abs(sp[0] - near_x) <= w and abs(sp[1] - near_y) <= h]
            if len(close) != 1:
                return AMBIGUOUS
            return close[0]
        return near[0]

    def _best_near(self, img, x0, y0, reach, step):
        h, w = self.picture.shape
        best, spot = -1.0, None
        for y in range(y0 - reach, y0 + reach + 1, step):
            for x in range(x0 - reach, x0 + reach + 1, step):
                patch = _crop(img, x, y, w, h)
                if patch is not None:
                    s = self._score(patch)
                    if s > best:
                        best, spot = s, (x, y)
        return best, spot


def _peaks(scores, gap_x, gap_y):
    """The best few separate spots in a score map (each at least a gap apart)."""
    flat = scores.ravel()
    k = min(flat.size, 2000)
    order = np.argpartition(flat, -k)[-k:]
    order = order[np.argsort(flat[order])[::-1]]
    W = scores.shape[1]
    out = []
    for i in order:
        if flat[i] < max(COARSE, flat[order[0]] - 0.1):
            break
        y, x = divmod(int(i), W)
        if all(abs(x - a) > gap_x or abs(y - b) > gap_y for a, b in out):
            out.append((x, y))
            if len(out) == CANDIDATES:
                break
    return out
